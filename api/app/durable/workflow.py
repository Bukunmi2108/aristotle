from __future__ import annotations

import asyncio
import logging
from typing import Any

from dbos import DBOS
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from app.agent.runtime import AristotleAgentRuntime
from app.config import SETTINGS
from app.events import EventSender
from app.models import ClientUserMessage
from app.runtime_services import get_runtime_services

logger = logging.getLogger(__name__)
_durable_agent: Any = None


def set_durable_agent(agent: Any) -> None:
    global _durable_agent
    _durable_agent = agent


@DBOS.step(name="aristotle__load_run")
async def _load_run(run_id: str) -> dict[str, Any]:
    record = await get_runtime_services().store.get_run_request(run_id)
    if record is None:
        raise RuntimeError(f"Run not found: {run_id}")
    await get_runtime_services().store.mark_run_running(run_id)
    history = await get_runtime_services().store.list_model_history(
        record["conversation_id"],
        before_message_id=record["user_message_id"],
        max_messages=SETTINGS.history_max_messages,
        max_chars=SETTINGS.history_max_chars,
    )
    return {**record, "history": history}


@DBOS.step(name="aristotle__complete_run")
async def _complete_run(run_id: str, message_id: str, message: str) -> None:
    store = get_runtime_services().store
    await store.update_message(
        message_id=message_id,
        content=message,
        status="complete",
    )
    await store.complete_run(run_id, "complete")


@DBOS.step(name="aristotle__fail_run")
async def _fail_run(run_id: str, message_id: str, error: str) -> None:
    store = get_runtime_services().store
    await store.update_message(message_id=message_id, content="", status="error")
    await store.complete_run(run_id, "error", error[:2000])


@DBOS.step(name="aristotle__consume_steering")
async def _consume_steering(run_id: str) -> list[str]:
    return await get_runtime_services().store.consume_run_inputs(run_id)


@DBOS.workflow(name="aristotle.run_turn")
async def run_turn(run_id: str) -> str:
    if _durable_agent is None:
        raise RuntimeError("Durable Aristotle agent is not configured.")

    record = await _load_run(run_id)
    user_message = ClientUserMessage.model_validate(record["request"])
    events = EventSender(
        None,
        conversation_id=record["conversation_id"],
        run_id=run_id,
        message_id=record["assistant_message_id"],
        store=get_runtime_services().store,
        namespace="workflow",
    )

    try:
        await events.send("session.started")
        services = get_runtime_services()
        runtime = AristotleAgentRuntime(
            search_client=services.search_client,
            settings=SETTINGS,
            document_store=services.store,
            sandbox_client=services.sandbox_client,
            agent=_durable_agent,
            live_model_events=True,
        )
        history = _model_history(record["history"])
        final_message = await runtime.stream_response(
            user_message,
            events,
            message_history=history,
            execution_pass=0,
        )
        history.extend(
            [
                ModelRequest(parts=[UserPromptPart(content=user_message.message)]),
                ModelResponse(parts=[TextPart(content=final_message)]),
            ]
        )
        execution_pass = 1
        while steering := await _consume_steering(run_id):
            steering_message = "\n\n".join(steering)
            steered_request = user_message.model_copy(
                update={"message": steering_message}
            )
            final_message = await runtime.stream_response(
                steered_request,
                events,
                message_history=history,
                execution_pass=execution_pass,
            )
            execution_pass += 1
            history.extend(
                [
                    ModelRequest(parts=[UserPromptPart(content=steering_message)]),
                    ModelResponse(parts=[TextPart(content=final_message)]),
                ]
            )
        await events.send("message.completed", message=final_message)
        await events.send("session.completed")
        await _complete_run(run_id, record["assistant_message_id"], final_message)
        return final_message
    except asyncio.CancelledError:
        logger.info("Durable run cancelled", extra={"run_id": run_id})
        raise
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        await events.send("error", code="internal_error", message=error)
        await _fail_run(run_id, record["assistant_message_id"], error)
        raise


def _model_history(records: list[dict[str, str]]) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    for record in records:
        content = record["content"].strip()
        if not content:
            continue
        if record["role"] == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=content)]))
    return history
