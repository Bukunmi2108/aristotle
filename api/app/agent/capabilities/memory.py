from __future__ import annotations

import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import ToolDefinition
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets.function import FunctionToolset

from app.agent.deps import AgentDeps

NOTE_TOOL_NAMES = {
    "save_research_note",
    "list_research_notes",
    "read_research_note",
    "compact_research_notes",
}
NoteKind = Literal["progress", "finding", "decision", "todo"]
logger = logging.getLogger(__name__)


class NoteRecord(BaseModel):
    id: str
    kind: str
    title: str
    content: str
    source_run_id: str | None = None


class NotePreview(BaseModel):
    id: str
    kind: str
    title: str
    preview: str


class NoteList(BaseModel):
    notes: list[NotePreview]


@dataclass
class MemoryTools(AbstractCapability[AgentDeps]):
    max_note_chars: int = 12_000
    max_active_notes: int = 50

    def get_instructions(self):
        def instructions(ctx: RunContext[AgentDeps]) -> str | None:
            if ctx.deps.document_store is None or ctx.deps.conversation_id is None:
                return None
            return (
                "Durable research notes survive connection loss, worker restarts, and "
                "context compaction. On a long investigation, call save_research_note "
                "after material findings, decisions, or a meaningful change of plan, "
                "and before starting another expensive branch of work. Keep notes "
                "concise and include source URLs, file paths, commands, or artifact IDs "
                "needed to resume. Use compact_research_notes when several notes can be "
                "replaced by one provenance-preserving summary. Do not save routine "
                "conversation or duplicate notes. Refresh time-sensitive facts before "
                "presenting them as current."
            )

        return instructions

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](id="memory_tools", strict=False)

        @toolset.tool(name="save_research_note", strict=False)
        async def save_research_note(
            ctx: RunContext[AgentDeps],
            kind: NoteKind,
            title: str,
            content: str,
        ) -> NoteRecord:
            """Save a concise durable checkpoint for later steps or turns."""
            store, conversation_id = _scope(ctx)
            note = await store.save_note(
                note_id=_note_id(ctx, "save"),
                conversation_id=conversation_id,
                source_run_id=ctx.deps.run_id,
                kind=kind,
                title=_clean(title, 160),
                content=_clean(content, self.max_note_chars),
            )
            await _mirror_notes(ctx, note)
            return NoteRecord.model_validate(note)

        @toolset.tool(name="list_research_notes", strict=False)
        async def list_research_notes(ctx: RunContext[AgentDeps]) -> NoteList:
            """List active durable research notes for this conversation."""
            store, conversation_id = _scope(ctx)
            notes = await store.list_active_notes(
                conversation_id, limit=self.max_active_notes
            )
            return NoteList(
                notes=[
                    NotePreview(
                        id=note["id"],
                        kind=note["kind"],
                        title=note["title"],
                        preview=" ".join(note["content"].split())[:400],
                    )
                    for note in notes
                ]
            )

        @toolset.tool(name="read_research_note", strict=False)
        async def read_research_note(
            ctx: RunContext[AgentDeps], note_id: str
        ) -> NoteRecord:
            """Read one durable research note by ID."""
            store, conversation_id = _scope(ctx)
            note = await store.get_note(conversation_id, note_id)
            if note is None:
                raise ValueError("Research note not found in this conversation.")
            return NoteRecord.model_validate(note)

        @toolset.tool(name="compact_research_notes", strict=False)
        async def compact_research_notes(
            ctx: RunContext[AgentDeps],
            title: str,
            summary: str,
            source_note_ids: list[str],
        ) -> NoteRecord:
            """Replace several active notes with one durable summary."""
            store, conversation_id = _scope(ctx)
            if not 1 <= len(source_note_ids) <= 30:
                raise ValueError("Select between 1 and 30 research notes to compact.")
            note = await store.compact_notes(
                note_id=_note_id(ctx, "compact"),
                conversation_id=conversation_id,
                source_run_id=ctx.deps.run_id,
                title=_clean(title, 160),
                content=_clean(summary, self.max_note_chars),
                source_note_ids=list(dict.fromkeys(source_note_ids)),
            )
            await _mirror_notes(ctx, note)
            return NoteRecord.model_validate(note)

        return toolset

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if ctx.deps.document_store is not None and ctx.deps.conversation_id:
            return tool_defs
        return [tool for tool in tool_defs if tool.name not in NOTE_TOOL_NAMES]


def _scope(ctx: RunContext[AgentDeps]):
    if ctx.deps.document_store is None or ctx.deps.conversation_id is None:
        raise ValueError("Durable research notes are not configured for this run.")
    return ctx.deps.document_store, ctx.deps.conversation_id


def _note_id(ctx: RunContext[AgentDeps], operation: str) -> str:
    identity = f"{ctx.deps.run_id}:{ctx.tool_call_id}:{operation}"
    return "note_" + sha256(identity.encode()).hexdigest()[:24]


def _clean(value: str, max_chars: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Research notes cannot be empty.")
    return cleaned[:max_chars]


async def _mirror_notes(ctx: RunContext[AgentDeps], note: dict) -> None:
    workspace = ctx.deps.workspace
    store = ctx.deps.document_store
    conversation_id = ctx.deps.conversation_id
    if workspace is None or store is None or conversation_id is None:
        return
    try:
        body = (
            f"# {note['title']}\n\n"
            f"- note_id: {note['id']}\n"
            f"- kind: {note['kind']}\n"
            f"- source_run_id: {note.get('source_run_id') or 'unknown'}\n\n"
            f"{note['content']}\n"
        )
        await workspace.write_file(f".aristotle/notes/{note['id']}.md", body.encode())
        active = await store.list_active_notes(conversation_id, limit=50)
        index = "# Active Aristotle research notes\n\n" + "\n".join(
            f"- [{item['title']}]({item['id']}.md) — {item['kind']}" for item in active
        )
        await workspace.write_file(".aristotle/notes/INDEX.md", index.encode())
    except Exception:
        logger.warning(
            "Failed to mirror durable research note into workspace",
            extra={"run_id": ctx.deps.run_id, "note_id": note.get("id")},
            exc_info=True,
        )
