from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg

from app.config import ApiSettings


APP_TABLES = (
    "events",
    "runs",
    "messages",
    "conversations",
)


SCHEMA_SQL = """
create table if not exists conversations (
  id text primary key,
  title text not null,
  status text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists messages (
  id text primary key,
  conversation_id text not null references conversations(id) on delete cascade,
  role text not null,
  content text,
  status text not null,
  parent_message_id text references messages(id),
  created_at timestamptz not null,
  completed_at timestamptz
);

create table if not exists runs (
  id text primary key,
  conversation_id text not null references conversations(id) on delete cascade,
  user_message_id text references messages(id),
  assistant_message_id text references messages(id),
  status text not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  cancelled_at timestamptz,
  error text
);

create table if not exists events (
  id text primary key,
  run_id text references runs(id) on delete cascade,
  conversation_id text not null references conversations(id) on delete cascade,
  message_id text references messages(id),
  sequence integer not null,
  type text not null,
  payload_json jsonb not null,
  created_at timestamptz not null
);

create index if not exists events_run_sequence_idx on events(run_id, sequence);
create index if not exists events_conversation_created_idx on events(conversation_id, created_at);
"""


class PersistenceStore:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def ensure_conversation(self, conversation_id: str, title: str) -> None:
        now = _now()
        await self.pool.execute(
            """
            insert into conversations (id, title, status, created_at, updated_at)
            values ($1, $2, 'active', $3, $3)
            on conflict (id) do update set updated_at = excluded.updated_at
            """,
            conversation_id,
            title,
            now,
        )

    async def create_message(
        self,
        *,
        message_id: str,
        conversation_id: str,
        role: str,
        content: str | None,
        status: str,
        parent_message_id: str | None = None,
    ) -> None:
        now = _now()
        await self.pool.execute(
            """
            insert into messages (
              id, conversation_id, role, content, status, parent_message_id,
              created_at, completed_at
            )
            values (
              $1, $2, $3, $4, $5, $6, $7,
              case when $5::text = 'complete' then $7::timestamptz else null::timestamptz end
            )
            on conflict (id) do update set
              content = excluded.content,
              status = excluded.status,
              completed_at = excluded.completed_at
            """,
            message_id,
            conversation_id,
            role,
            content,
            status,
            parent_message_id,
            now,
        )

    async def update_message(
        self,
        *,
        message_id: str,
        content: str | None,
        status: str,
    ) -> None:
        now = _now()
        await self.pool.execute(
            """
            update messages
            set content = $2,
                status = $3,
                completed_at = case when $3 in ('complete', 'error', 'stopped') then $4 else completed_at end
            where id = $1
            """,
            message_id,
            content,
            status,
            now,
        )

    async def create_run(
        self,
        *,
        run_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> None:
        await self.pool.execute(
            """
            insert into runs (
              id, conversation_id, user_message_id, assistant_message_id,
              status, started_at
            )
            values ($1, $2, $3, $4, 'running', $5)
            on conflict (id) do nothing
            """,
            run_id,
            conversation_id,
            user_message_id,
            assistant_message_id,
            _now(),
        )

    async def complete_run(self, run_id: str, status: str, error: str | None = None) -> None:
        await self.pool.execute(
            """
            update runs
            set status = $2,
                completed_at = case when $2 in ('complete', 'error') then $4 else completed_at end,
                cancelled_at = case when $2 = 'cancelled' then $4 else cancelled_at end,
                error = $3
            where id = $1
            """,
            run_id,
            status,
            error,
            _now(),
        )

    async def append_event(self, event: dict[str, Any]) -> None:
        await self.pool.execute(
            """
            insert into events (
              id, run_id, conversation_id, message_id, sequence, type,
              payload_json, created_at
            )
            values ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
            """,
            event["event_id"],
            event.get("run_id"),
            event["conversation_id"],
            event.get("message_id"),
            event["sequence"],
            event["type"],
            json.dumps(event),
            _parse_timestamp(event["timestamp"]),
        )

    async def list_conversations(self) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            select id, title, status, created_at, updated_at
            from conversations
            order by updated_at desc
            limit 100
            """
        )
        return [_record_to_dict(row) for row in rows]

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            select id, title, status, created_at, updated_at
            from conversations
            where id = $1
            """,
            conversation_id,
        )
        return _record_to_dict(row) if row is not None else None

    async def rename_conversation(self, conversation_id: str, title: str) -> bool:
        result = await self.pool.execute(
            """
            update conversations
            set title = $2,
                updated_at = $3
            where id = $1
            """,
            conversation_id,
            title,
            _now(),
        )
        return result == "UPDATE 1"

    async def delete_conversation(self, conversation_id: str) -> bool:
        result = await self.pool.execute(
            "delete from conversations where id = $1",
            conversation_id,
        )
        return result == "DELETE 1"

    async def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            select id, conversation_id, role, content, status, parent_message_id,
                   created_at, completed_at
            from messages
            where conversation_id = $1
            order by created_at asc
            """,
            conversation_id,
        )
        return [_record_to_dict(row) for row in rows]

    async def list_events(
        self, run_id: str, after_event_id: str | None = None
    ) -> list[dict[str, Any]]:
        if after_event_id:
            sequence = await self.pool.fetchval(
                "select sequence from events where id = $1 and run_id = $2",
                after_event_id,
                run_id,
            )
        else:
            sequence = None

        rows = await self.pool.fetch(
            """
            select payload_json
            from events
            where run_id = $1 and ($2::integer is null or sequence > $2)
            order by sequence asc
            """,
            run_id,
            sequence,
        )
        return [_json_payload(row["payload_json"]) for row in rows]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            select id, conversation_id, user_message_id, assistant_message_id,
                   status, started_at, completed_at, cancelled_at, error
            from runs
            where id = $1
            """,
            run_id,
        )
        return _record_to_dict(row) if row is not None else None


async def create_store(settings: ApiSettings) -> PersistenceStore | None:
    if not settings.database_url:
        return None

    pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=5)
    store = PersistenceStore(pool)
    await initialize_database(store, settings)
    return store


async def initialize_database(store: PersistenceStore, settings: ApiSettings) -> None:
    async with store.pool.acquire() as connection:
        await connection.execute(SCHEMA_SQL)
        if settings.reset_db_on_start:
            await connection.execute(
                f"truncate table {', '.join(APP_TABLES)} restart identity cascade"
            )
        else:
            await connection.execute(
                """
                delete from conversations
                where created_at < now() - ($1::text || ' days')::interval
                """,
                str(settings.data_retention_days),
            )


async def close_store(store: PersistenceStore | None) -> None:
    if store is not None:
        await store.pool.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    result = dict(record)
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"value": loaded}
    if isinstance(value, dict):
        return value
    return dict(value)
