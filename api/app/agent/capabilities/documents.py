from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_ai import ToolDefinition
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.tools import RunContext

from app.agent.deps import AgentDeps


DOCUMENT_TOOL_NAMES = {
    "list_files",
    "read_file",
    "search_document",
    "search_documents",
    "quote_document",
    "summarize_document",
    "compare_documents",
}
WORD_RE = re.compile(r"[a-z0-9]{3,}")


class DocumentFile(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    parse_status: str
    parse_error: str | None = None


class DocumentSearchResult(BaseModel):
    id: str
    source_type: str = "document"
    file_id: str
    chunk_id: str
    filename: str
    title: str
    locator: str
    page: int | None = None
    section: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    text_preview: str
    snippet: str
    score: float
    status: str = "fetched"


class ListFilesResult(BaseModel):
    files: list[DocumentFile]


class ReadFileResult(BaseModel):
    file_id: str
    filename: str
    chunks: list[DocumentSearchResult]


class SearchDocumentResult(BaseModel):
    query: str
    results: list[DocumentSearchResult]


class QuoteDocumentResult(BaseModel):
    chunk_id: str
    file_id: str
    filename: str
    locator: str
    quote: str


class SummarizeDocumentResult(BaseModel):
    file_id: str
    filename: str
    chunks: list[DocumentSearchResult]


@dataclass
class DocumentTools(AbstractCapability[AgentDeps]):
    max_results: int = 5
    max_read_chunks: int = 8

    def get_instructions(self):
        def instructions(ctx: RunContext[AgentDeps]) -> str | None:
            if not ctx.deps.document_tools_enabled:
                return None
            scope = ", ".join(ctx.deps.file_ids)
            return (
                "Attached files are available for this run. Before asking for "
                "clarification about vague references like 'this', 'it', 'the file', "
                "or 'is this true', inspect the uploaded files with DocumentTools. "
                f"Available file IDs for this run: {scope}. Use list_files first "
                "when you need file names, then search_document or read_file for "
                "evidence. For truth or accuracy questions, first answer what the "
                "document itself supports, then distinguish that from any current or "
                "external facts that need web verification. Cite document locators "
                "like [file:1], and say when the answer is not found in the uploaded "
                "files."
            )

        return instructions

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](id="document_tools", strict=False)

        @toolset.tool(name="list_files", strict=False)
        async def list_files(ctx: RunContext[AgentDeps]) -> ListFilesResult:
            """List uploaded files available to this run."""
            await ctx.deps.events.send(
                "tool.started",
                tool="list_files",
                input={"file_ids": ctx.deps.file_ids},
            )
            files = []
            for file_id in ctx.deps.file_ids:
                record = await _get_file(ctx, file_id)
                files.append(_file_result(record))
            return ListFilesResult(files=files)

        @toolset.tool(name="read_file", strict=False)
        async def read_file(ctx: RunContext[AgentDeps], file_id: str) -> ReadFileResult:
            """Read the first chunks of an uploaded file."""
            await ctx.deps.events.send(
                "tool.started", tool="read_file", input={"file_id": file_id}
            )
            _assert_allowed_file(ctx, file_id)
            store = _document_store(ctx)
            file_record = await _get_file(ctx, file_id)
            chunks = await store.list_chunks_for_files(
                [file_id],
                limit=self.max_read_chunks,
            )
            return ReadFileResult(
                file_id=file_id,
                filename=file_record["filename"],
                chunks=[_chunk_result(chunk, score=1.0) for chunk in chunks],
            )

        @toolset.tool(name="search_document", strict=False)
        async def search_document(
            ctx: RunContext[AgentDeps],
            file_id: str,
            query: str,
            max_results: int = 5,
        ) -> SearchDocumentResult:
            """Search one uploaded document by lexical chunk match."""
            await ctx.deps.events.send(
                "tool.started",
                tool="search_document",
                input={"file_id": file_id, "query": query, "max_results": max_results},
            )
            _assert_allowed_file(ctx, file_id)
            store = _document_store(ctx)
            chunks = await store.list_chunks_for_files([file_id])
            return SearchDocumentResult(
                query=query,
                results=_rank_chunks(query, chunks, max_results=max_results),
            )

        @toolset.tool(name="search_documents", strict=False)
        async def search_documents(
            ctx: RunContext[AgentDeps],
            query: str,
            file_ids: list[str] | None = None,
            max_results: int = 5,
        ) -> SearchDocumentResult:
            """Search uploaded documents by lexical chunk match."""
            selected = file_ids or ctx.deps.file_ids
            for file_id in selected:
                _assert_allowed_file(ctx, file_id)
            await ctx.deps.events.send(
                "tool.started",
                tool="search_documents",
                input={
                    "file_ids": selected,
                    "query": query,
                    "max_results": max_results,
                },
            )
            store = _document_store(ctx)
            chunks = await store.list_chunks_for_files(selected)
            return SearchDocumentResult(
                query=query,
                results=_rank_chunks(query, chunks, max_results=max_results),
            )

        @toolset.tool(name="quote_document", strict=False)
        async def quote_document(
            ctx: RunContext[AgentDeps], chunk_id: str
        ) -> QuoteDocumentResult:
            """Return an exact quote from a document chunk."""
            await ctx.deps.events.send(
                "tool.started", tool="quote_document", input={"chunk_id": chunk_id}
            )
            store = _document_store(ctx)
            chunk = await store.get_document_chunk(chunk_id)
            if chunk is None:
                raise ValueError("Document chunk not found.")
            _assert_allowed_file(ctx, chunk["file_id"])
            return QuoteDocumentResult(
                chunk_id=chunk_id,
                file_id=chunk["file_id"],
                filename=chunk["filename"],
                locator=_locator(chunk),
                quote=chunk["text"],
            )

        @toolset.tool(name="summarize_document", strict=False)
        async def summarize_document(
            ctx: RunContext[AgentDeps], file_id: str
        ) -> SummarizeDocumentResult:
            """Return representative chunks for summarizing an uploaded file."""
            await ctx.deps.events.send(
                "tool.started", tool="summarize_document", input={"file_id": file_id}
            )
            _assert_allowed_file(ctx, file_id)
            store = _document_store(ctx)
            file_record = await _get_file(ctx, file_id)
            chunks = await store.list_chunks_for_files(
                [file_id],
                limit=self.max_read_chunks,
            )
            return SummarizeDocumentResult(
                file_id=file_id,
                filename=file_record["filename"],
                chunks=[_chunk_result(chunk, score=1.0) for chunk in chunks],
            )

        @toolset.tool(name="compare_documents", strict=False)
        async def compare_documents(
            ctx: RunContext[AgentDeps],
            file_ids: list[str],
            question: str,
            max_results: int = 8,
        ) -> SearchDocumentResult:
            """Search several uploaded documents for comparison evidence."""
            selected = file_ids or ctx.deps.file_ids
            for file_id in selected:
                _assert_allowed_file(ctx, file_id)
            await ctx.deps.events.send(
                "tool.started",
                tool="compare_documents",
                input={
                    "file_ids": selected,
                    "question": question,
                    "max_results": max_results,
                },
            )
            store = _document_store(ctx)
            chunks = await store.list_chunks_for_files(selected)
            return SearchDocumentResult(
                query=question,
                results=_rank_chunks(question, chunks, max_results=max_results),
            )

        return toolset

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if ctx.deps.document_tools_enabled:
            return tool_defs
        return [tool for tool in tool_defs if tool.name not in DOCUMENT_TOOL_NAMES]


async def _get_file(ctx: RunContext[AgentDeps], file_id: str) -> dict[str, Any]:
    _assert_allowed_file(ctx, file_id)
    store = _document_store(ctx)
    record = await store.get_file(file_id)
    if record is None:
        raise ValueError("Uploaded file not found.")
    if record["parse_status"] != "parsed":
        error = record.get("parse_error")
        raise ValueError(
            f"Uploaded file is not parsed: {error or record['parse_status']}"
        )
    return record


def _assert_allowed_file(ctx: RunContext[AgentDeps], file_id: str) -> None:
    if ctx.deps.document_store is None:
        raise ValueError("Document persistence is not configured.")
    if file_id not in ctx.deps.file_ids:
        raise ValueError("File is not attached to this run.")


def _document_store(ctx: RunContext[AgentDeps]):
    store = ctx.deps.document_store
    if store is None:
        raise ValueError("Document persistence is not configured.")
    return store


def _file_result(record: dict[str, Any]) -> DocumentFile:
    return DocumentFile(
        file_id=record["id"],
        filename=record["filename"],
        mime_type=record["mime_type"],
        parse_status=record["parse_status"],
        parse_error=record.get("parse_error"),
    )


def _rank_chunks(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    max_results: int,
) -> list[DocumentSearchResult]:
    query_terms = _terms(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        chunk_terms = _terms(
            " ".join(
                str(part or "")
                for part in [chunk.get("filename"), chunk.get("section"), chunk["text"]]
            )
        )
        overlap = query_terms & chunk_terms
        if not overlap:
            continue
        score = len(overlap) / max(1, len(query_terms))
        if chunk.get("section") and _terms(chunk["section"]) & query_terms:
            score += 0.2
        scored.append((round(score, 4), chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        _chunk_result(chunk, score=score)
        for score, chunk in scored[: max(1, min(max_results, 20))]
    ]


def _chunk_result(chunk: dict[str, Any], *, score: float) -> DocumentSearchResult:
    locator = _locator(chunk)
    preview = " ".join(chunk["text"].split())[:600]
    return DocumentSearchResult(
        id=chunk["id"],
        file_id=chunk["file_id"],
        chunk_id=chunk["id"],
        filename=chunk["filename"],
        title=chunk["filename"],
        locator=locator,
        page=chunk.get("page"),
        section=chunk.get("section"),
        row_start=chunk.get("row_start"),
        row_end=chunk.get("row_end"),
        text_preview=preview,
        snippet=preview,
        score=score,
    )


def _locator(chunk: dict[str, Any]) -> str:
    if chunk.get("page"):
        return f"page {chunk['page']}"
    if chunk.get("row_start") and chunk.get("row_end"):
        return f"rows {chunk['row_start']}-{chunk['row_end']}"
    if chunk.get("section"):
        return f"section: {chunk['section']}"
    return f"chunk {chunk['chunk_index'] + 1}"


def _terms(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower()))
