from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import ToolDefinition
from pydantic_ai.capabilities import (
    AbstractCapability,
    ValidatedToolArgs,
    WrapToolExecuteHandler,
)
from pydantic_ai.tools import RunContext
from pydantic_core import to_jsonable_python

from app.agent.deps import AgentDeps

NON_REPEATABLE_TOOLS = {"run_command", "run_python", "move_path", "delete_path"}


@dataclass
class ReplaySafeTools(AbstractCapability[AgentDeps]):
    """Journal tool results so DBOS recovery can replay them without repeated I/O."""

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        handler: WrapToolExecuteHandler,
    ) -> Any:
        store = ctx.deps.document_store
        run_id = ctx.deps.run_id
        tool_call_id = ctx.tool_call_id
        if store is None or run_id is None or tool_call_id is None:
            return await handler(args)

        arguments = to_jsonable_python(args)
        record, inserted = await store.begin_tool_execution(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_def.name,
            arguments=arguments,
        )
        if record["status"] == "complete":
            return record.get("result")
        if not inserted and tool_def.name in NON_REPEATABLE_TOOLS:
            raise RuntimeError(
                f"Recovery stopped before repeating non-idempotent tool "
                f"'{tool_def.name}' ({tool_call_id}). Inspect the workspace and retry "
                "explicitly if safe."
            )

        try:
            result = await handler(args)
        except Exception as exc:
            await store.fail_tool_execution(
                run_id=run_id,
                tool_call_id=tool_call_id,
                error=str(exc) or type(exc).__name__,
            )
            raise
        await store.complete_tool_execution(
            run_id=run_id,
            tool_call_id=tool_call_id,
            result=to_jsonable_python(result),
        )
        return result
