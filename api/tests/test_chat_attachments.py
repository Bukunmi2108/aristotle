import unittest
from typing import Any, cast

from app.agent.runtime import AristotleAgentRuntime
from app.websocket.chat import (
    DocumentScopeError,
    _validate_active_artifact,
    _validate_attached_files,
)


class FakeStore:
    def __init__(self, files, presentations=None):
        self.files = files
        self.presentations = presentations or []

    async def list_files(self, conversation_id: str):
        return self.files

    async def get_file(self, file_id: str):
        for file in self.files:
            if file["id"] == file_id:
                return file
        return None

    async def list_presentations(self, conversation_id: str):
        return self.presentations

    async def get_presentation(self, artifact_id: str):
        return next(
            (item for item in self.presentations if item["id"] == artifact_id),
            None,
        )


class ChatAttachmentTest(unittest.IsolatedAsyncioTestCase):
    async def test_validate_attached_files_rejects_unattached_file(self):
        store = FakeStore(
            [
                {
                    "id": "file_ok",
                    "filename": "notes.txt",
                    "parse_status": "parsed",
                }
            ]
        )

        with self.assertRaisesRegex(DocumentScopeError, "not attached"):
            await _validate_attached_files(
                cast(Any, store),
                "conv_1",
                ["file_missing"],
            )

    async def test_validate_attached_files_rejects_unparsed_file(self):
        store = FakeStore(
            [
                {
                    "id": "file_pending",
                    "filename": "notes.txt",
                    "parse_status": "pending",
                }
            ]
        )

        with self.assertRaisesRegex(DocumentScopeError, "not ready"):
            await _validate_attached_files(
                cast(Any, store),
                "conv_1",
                ["file_pending"],
            )

    async def test_runtime_adds_attached_file_metadata_to_prompt(self):
        store = FakeStore(
            [
                {
                    "id": "file_ok",
                    "filename": "contract.pdf",
                    "parse_status": "parsed",
                }
            ]
        )
        runtime = AristotleAgentRuntime(
            search_client=cast(Any, None),
            settings=cast(Any, None),
            document_store=cast(Any, store),
        )

        prompt = await runtime._message_with_file_context(
            "Summarize this.",
            ["file_ok"],
        )

        self.assertIn("contract.pdf", prompt)
        self.assertIn("file_ok", prompt)
        self.assertIn("Summarize this.", prompt)

    async def test_runtime_adds_active_artifact_manifest_to_followup(self):
        store = FakeStore(
            [],
            [
                {
                    "id": "pres_roman",
                    "conversation_id": "conv_1",
                    "message_id": "msg_1",
                    "path": "reports/roman-history.md",
                    "mime_type": "text/markdown",
                    "title": "Roman History",
                    "version": 2,
                }
            ],
        )
        runtime = AristotleAgentRuntime(
            search_client=cast(Any, None),
            settings=cast(Any, None),
            document_store=cast(Any, store),
        )

        prompt = await runtime._message_with_context(
            "As Markdown and PDF.",
            [],
            "conv_1",
            "pres_roman",
        )

        self.assertIn("[active] reports/roman-history.md", prompt)
        self.assertIn("must not trigger new web research", prompt)
        self.assertIn("export_document", prompt)

    async def test_active_artifact_must_belong_to_conversation(self):
        store = FakeStore(
            [],
            [
                {
                    "id": "pres_other",
                    "conversation_id": "conv_other",
                }
            ],
        )

        with self.assertRaisesRegex(DocumentScopeError, "does not belong"):
            await _validate_active_artifact(
                cast(Any, store),
                "conv_1",
                "pres_other",
            )


if __name__ == "__main__":
    unittest.main()
