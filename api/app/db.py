from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg

from app.config import ApiSettings


APP_TABLES = (
    "events",
    "runs",
    "message_files",
    "messages",
    "conversation_files",
    "document_chunks",
    "documents",
    "files",
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

create table if not exists files (
  id text primary key,
  owner_id text,
  filename text not null,
  mime_type text not null,
  size_bytes bigint not null,
  storage_path text not null,
  uploaded_at timestamptz not null,
  parse_status text not null,
  parse_error text
);

create table if not exists message_files (
  message_id text not null references messages(id) on delete cascade,
  file_id text not null references files(id) on delete cascade,
  created_at timestamptz not null,
  primary key (message_id, file_id)
);

create table if not exists documents (
  id text primary key,
  file_id text not null references files(id) on delete cascade,
  title text not null,
  text_chars integer not null,
  parser text not null,
  created_at timestamptz not null
);

create table if not exists document_chunks (
  id text primary key,
  document_id text not null references documents(id) on delete cascade,
  file_id text not null references files(id) on delete cascade,
  chunk_index integer not null,
  page integer,
  section text,
  row_start integer,
  row_end integer,
  char_start integer not null,
  char_end integer not null,
  text text not null,
  token_count integer not null,
  embedding_id text
);

create table if not exists conversation_files (
  conversation_id text not null references conversations(id) on delete cascade,
  file_id text not null references files(id) on delete cascade,
  created_at timestamptz not null,
  primary key (conversation_id, file_id)
);

create index if not exists files_uploaded_at_idx on files(uploaded_at desc);
create index if not exists document_chunks_file_idx on document_chunks(file_id, chunk_index);
create index if not exists conversation_files_conversation_idx on conversation_files(conversation_id);
create index if not exists message_files_message_idx on message_files(message_id);
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

    async def attach_files_to_message(
        self,
        *,
        message_id: str,
        file_ids: list[str],
    ) -> None:
        if not file_ids:
            return
        now = _now()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for file_id in dict.fromkeys(file_ids):
                    await connection.execute(
                        """
                        insert into message_files (message_id, file_id, created_at)
                        values ($1, $2, $3)
                        on conflict (message_id, file_id) do nothing
                        """,
                        message_id,
                        file_id,
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
        messages = [_record_to_dict(row) for row in rows]
        if not messages:
            return messages

        message_ids = [message["id"] for message in messages]
        attachment_rows = await self.pool.fetch(
            """
            select mf.message_id, f.id, f.owner_id, f.filename, f.mime_type,
                   f.size_bytes, f.storage_path, f.uploaded_at, f.parse_status,
                   f.parse_error
            from message_files mf
            join files f on f.id = mf.file_id
            where mf.message_id = any($1::text[])
            order by mf.created_at asc
            """,
            message_ids,
        )
        attachments_by_message: dict[str, list[dict[str, Any]]] = {}
        for row in attachment_rows:
            record = _record_to_dict(row)
            message_id = record.pop("message_id")
            attachments_by_message.setdefault(message_id, []).append(record)

        for message in messages:
            message["attachments"] = attachments_by_message.get(message["id"], [])
        return messages

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

    async def create_file(
        self,
        *,
        file_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_path: str,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        row = await self.pool.fetchrow(
            """
            insert into files (
              id, owner_id, filename, mime_type, size_bytes, storage_path,
              uploaded_at, parse_status
            )
            values ($1, $2, $3, $4, $5, $6, $7, 'pending')
            returning id, owner_id, filename, mime_type, size_bytes, storage_path,
                      uploaded_at, parse_status, parse_error
            """,
            file_id,
            owner_id,
            filename,
            mime_type,
            size_bytes,
            storage_path,
            now,
        )
        return _record_to_dict(row)

    async def attach_file_to_conversation(
        self, conversation_id: str, file_id: str
    ) -> None:
        await self.pool.execute(
            """
            insert into conversation_files (conversation_id, file_id, created_at)
            values ($1, $2, $3)
            on conflict (conversation_id, file_id) do nothing
            """,
            conversation_id,
            file_id,
            _now(),
        )

    async def list_files(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            select f.id, f.owner_id, f.filename, f.mime_type, f.size_bytes,
                   f.storage_path, f.uploaded_at, f.parse_status, f.parse_error
            from files f
            join conversation_files cf on cf.file_id = f.id
            where cf.conversation_id = $1
            order by cf.created_at desc
            """,
            conversation_id,
        )
        return [_record_to_dict(row) for row in rows]

    async def get_file(self, file_id: str) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            select id, owner_id, filename, mime_type, size_bytes, storage_path,
                   uploaded_at, parse_status, parse_error
            from files
            where id = $1
            """,
            file_id,
        )
        return _record_to_dict(row) if row is not None else None

    async def delete_file(self, file_id: str) -> bool:
        result = await self.pool.execute("delete from files where id = $1", file_id)
        return result == "DELETE 1"

    async def mark_file_parse_failed(self, file_id: str, error: str) -> None:
        await self.pool.execute(
            """
            update files set parse_status = 'failed', parse_error = $2 where id = $1
            """,
            file_id,
            error[:1000],
        )

    async def replace_document(
        self,
        *,
        document_id: str,
        file_id: str,
        title: str,
        text_chars: int,
        parser: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "delete from documents where file_id = $1",
                    file_id,
                )
                row = await connection.fetchrow(
                    """
                    insert into documents (id, file_id, title, text_chars, parser, created_at)
                    values ($1, $2, $3, $4, $5, $6)
                    returning id, file_id, title, text_chars, parser, created_at
                    """,
                    document_id,
                    file_id,
                    title,
                    text_chars,
                    parser,
                    _now(),
                )
                for chunk in chunks:
                    await connection.execute(
                        """
                        insert into document_chunks (
                          id, document_id, file_id, chunk_index, page, section,
                          row_start, row_end, char_start, char_end, text, token_count,
                          embedding_id
                        )
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        """,
                        chunk["id"],
                        document_id,
                        file_id,
                        chunk["chunk_index"],
                        chunk.get("page"),
                        chunk.get("section"),
                        chunk.get("row_start"),
                        chunk.get("row_end"),
                        chunk["char_start"],
                        chunk["char_end"],
                        chunk["text"],
                        chunk["token_count"],
                        chunk.get("embedding_id"),
                    )
                await connection.execute(
                    """
                    update files
                    set parse_status = 'parsed', parse_error = null
                    where id = $1
                    """,
                    file_id,
                )
        return _record_to_dict(row)

    async def get_document_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            select c.id, c.document_id, c.file_id, c.chunk_index, c.page, c.section,
                   c.row_start, c.row_end, c.char_start, c.char_end, c.text,
                   c.token_count, c.embedding_id, f.filename
            from document_chunks c
            join files f on f.id = c.file_id
            where c.id = $1
            """,
            chunk_id,
        )
        return _record_to_dict(row) if row is not None else None

    async def list_chunks_for_files(
        self, file_ids: list[str], limit: int = 1000
    ) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            select c.id, c.document_id, c.file_id, c.chunk_index, c.page, c.section,
                   c.row_start, c.row_end, c.char_start, c.char_end, c.text,
                   c.token_count, c.embedding_id, f.filename
            from document_chunks c
            join files f on f.id = c.file_id
            where c.file_id = any($1::text[])
            order by c.file_id, c.chunk_index asc
            limit $2
            """,
            file_ids,
            limit,
        )
        return [_record_to_dict(row) for row in rows]


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
