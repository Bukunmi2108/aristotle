import asyncio
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.agent.runtime import AristotleAgentRuntime
from app.config import SETTINGS
from app.db import PersistenceStore
from app.errors import ServiceWakeTimeoutError
from app.events import EventSender
from app.models import ClientUserMessage
from app.services.model import ModelClient
from app.services.search import SearchClient
from app.services.wake import wait_for_service_ready


router = APIRouter()


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()

    model_client: ModelClient = websocket.app.state.model_client
    search_client: SearchClient = websocket.app.state.search_client
    events: EventSender | None = None

    try:
        raw_message = await websocket.receive_json()
        user_message = ClientUserMessage.model_validate(raw_message)
        conversation_id = user_message.conversation_id or str(uuid4())
        user_message = user_message.model_copy(
            update={"conversation_id": conversation_id}
        )
        store = getattr(websocket.app.state, "store", None)
        run_id = f"run_{uuid4().hex}"
        user_message_id = f"msg_{uuid4().hex}"
        assistant_message_id = f"msg_{uuid4().hex}"

        if store is None and user_message.options.file_ids:
            raise DocumentScopeError("Document persistence is not configured.")

        if store is not None:
            await store.ensure_conversation(
                conversation_id,
                _conversation_title(user_message.message),
            )
            await _validate_attached_files(
                store,
                conversation_id,
                user_message.options.file_ids,
            )
            await store.create_message(
                message_id=user_message_id,
                conversation_id=conversation_id,
                role="user",
                content=user_message.message,
                status="complete",
            )
            await store.attach_files_to_message(
                message_id=user_message_id,
                file_ids=user_message.options.file_ids,
            )
            await store.create_message(
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                role="assistant",
                content="",
                status="streaming",
                parent_message_id=user_message_id,
            )
            await store.create_run(
                run_id=run_id,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            )

        events = EventSender(
            websocket.send_json,
            conversation_id=conversation_id,
            run_id=run_id,
            message_id=assistant_message_id,
            store=store,
        )

        await events.send("session.started")

        await asyncio.gather(
            wait_for_service_ready(
                service="model",
                is_ready=model_client.is_ready,
                settings=SETTINGS,
                events=events,
            ),
            wait_for_service_ready(
                service="search",
                is_ready=search_client.is_ready,
                settings=SETTINGS,
                events=events,
            ),
        )

        agent_runtime = AristotleAgentRuntime(
            search_client=search_client,
            settings=SETTINGS,
            document_store=store,
        )
        final_message = await agent_runtime.stream_response(user_message, events)

        if store is not None:
            await store.update_message(
                message_id=assistant_message_id,
                content=final_message,
                status="complete",
            )
            await store.complete_run(run_id, "complete")

        await events.send("message.completed", message=final_message)
        await events.send("session.completed")
    except WebSocketDisconnect:
        return
    except ValidationError as exc:
        if events is not None:
            await events.send(
                "error", code="invalid_message", message=str(exc.errors())
            )
        else:
            await websocket.send_json(
                {
                    "type": "error",
                    "sequence": 1,
                    "code": "invalid_message",
                    "message": exc.errors(),
                }
            )
    except DocumentScopeError as exc:
        if events is not None:
            await events.send("error", code="invalid_file_scope", message=str(exc))
        else:
            await websocket.send_json(
                {
                    "type": "error",
                    "sequence": 1,
                    "code": "invalid_file_scope",
                    "message": str(exc),
                }
            )
    except ServiceWakeTimeoutError as exc:
        await _mark_failed_run(websocket, events, str(exc))
        if events is not None:
            await events.send(
                "error",
                code="service_wake_timeout",
                message=str(exc),
                service=exc.service,
            )
        else:
            await websocket.send_json(
                {
                    "type": "error",
                    "sequence": 1,
                    "code": "service_wake_timeout",
                    "message": str(exc),
                    "service": exc.service,
                }
            )
    except Exception as exc:
        await _mark_failed_run(websocket, events, str(exc))
        if events is not None:
            await events.send("error", code="internal_error", message=str(exc))
        else:
            await websocket.send_json(
                {
                    "type": "error",
                    "sequence": 1,
                    "code": "internal_error",
                    "message": str(exc),
                }
            )


async def _mark_failed_run(
    websocket: WebSocket,
    events: EventSender | None,
    message: str,
) -> None:
    if events is None:
        return
    store = getattr(websocket.app.state, "store", None)
    if store is None:
        return

    run_id = getattr(events, "_run_id", None)
    message_id = getattr(events, "_message_id", None)
    if run_id is not None:
        await store.complete_run(run_id, "error", message)
    if message_id is not None:
        await store.update_message(
            message_id=message_id,
            content="",
            status="error",
        )


def _conversation_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if len(title) <= 56:
        return title or "New chat"
    return f"{title[:53].rstrip()}..."


class DocumentScopeError(ValueError):
    pass


async def _validate_attached_files(
    store: PersistenceStore,
    conversation_id: str,
    file_ids: list[str],
) -> None:
    if not file_ids:
        return
    attached_files = await store.list_files(conversation_id)
    attached_by_id = {file["id"]: file for file in attached_files}
    attached_ids = set(attached_by_id)
    missing = [file_id for file_id in file_ids if file_id not in attached_ids]
    if missing:
        raise DocumentScopeError(
            "File is not attached to this conversation: " + ", ".join(missing)
        )
    unparsed = [
        file_id
        for file_id in file_ids
        if attached_by_id[file_id]["parse_status"] != "parsed"
    ]
    if unparsed:
        raise DocumentScopeError(
            "File is not ready for document tools: " + ", ".join(unparsed)
        )
