import unittest
from typing import Any, cast

from app.agent.runtime import AristotleAgentRuntime
from app.websocket.chat import DocumentScopeError, _validate_attached_files


class FakeStore:
    def __init__(self, files):
        self.files = files

    async def list_files(self, conversation_id: str):
        return self.files

    async def get_file(self, file_id: str):
        for file in self.files:
            if file["id"] == file_id:
                return file
        return None


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


if __name__ == "__main__":
    unittest.main()
