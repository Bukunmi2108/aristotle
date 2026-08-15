from __future__ import annotations

from uuid import uuid4

from dbos import DBOSClient

from app.db import PersistenceStore
from app.models import ClientUserMessage, RunCreatedResponse


class DocumentScopeError(ValueError):
    pass


async def create_chat_run(
    store: PersistenceStore,
    dbos_client: DBOSClient,
    user_message: ClientUserMessage,
) -> RunCreatedResponse:
    conversation_id = user_message.conversation_id or str(uuid4())
    user_message = user_message.model_copy(update={"conversation_id": conversation_id})
    run_id = f"run_{uuid4().hex}"
    user_message_id = f"msg_{uuid4().hex}"
    assistant_message_id = f"msg_{uuid4().hex}"

    await validate_active_artifact(
        store, conversation_id, user_message.active_artifact_id
    )
    await store.ensure_conversation(
        conversation_id, conversation_title(user_message.message)
    )
    await validate_attached_files(store, conversation_id, user_message.options.file_ids)
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
    request = user_message.model_dump(exclude={"history"})
    await store.create_run(
        run_id=run_id,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        request=request,
    )

    try:
        await dbos_client.enqueue_async(
            {
                "workflow_name": "aristotle.run_turn",
                "queue_name": "aristotle-agent",
                "workflow_id": run_id,
            },
            run_id,
        )
    except Exception as exc:
        await store.complete_run(run_id, "error", "Failed to enqueue durable run.")
        await store.update_message(
            message_id=assistant_message_id,
            content="",
            status="error",
        )
        raise RuntimeError("Failed to enqueue durable run.") from exc

    return RunCreatedResponse(
        run_id=run_id,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )


def conversation_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if len(title) <= 56:
        return title or "New chat"
    return f"{title[:53].rstrip()}..."


async def validate_attached_files(
    store: PersistenceStore,
    conversation_id: str,
    file_ids: list[str],
) -> None:
    if not file_ids:
        return
    attached_files = await store.list_files(conversation_id)
    attached_by_id = {file["id"]: file for file in attached_files}
    missing = [file_id for file_id in file_ids if file_id not in attached_by_id]
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


async def validate_active_artifact(
    store: PersistenceStore,
    conversation_id: str,
    artifact_id: str | None,
) -> None:
    if artifact_id is None:
        return
    artifact = await store.get_presentation(artifact_id)
    if artifact is None or artifact["conversation_id"] != conversation_id:
        raise DocumentScopeError(
            "Artifact does not belong to this conversation: " + artifact_id
        )
