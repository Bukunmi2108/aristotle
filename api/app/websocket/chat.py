from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.agent.runtime import AristotleAgentRuntime
from app.config import SETTINGS
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
        events = EventSender(websocket.send_json, conversation_id=conversation_id)

        await events.send("session.started")

        await wait_for_service_ready(
            service="model",
            is_ready=model_client.is_ready,
            settings=SETTINGS,
            events=events,
        )

        agent_runtime = AristotleAgentRuntime(
            search_client=search_client, settings=SETTINGS
        )
        final_message = await agent_runtime.stream_response(user_message, events)

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
    except ServiceWakeTimeoutError as exc:
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
