from dataclasses import replace
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.config import SETTINGS
from app.documents import (
    chunks_to_records,
    infer_mime_type,
    parse_document_file,
    validate_upload,
)


class DocumentParsingTest(unittest.TestCase):
    def setUp(self):
        self.settings = replace(
            SETTINGS,
            file_storage_dir="storage/test-uploads",
            max_upload_bytes=1024 * 1024,
            max_parsed_chars=20_000,
            max_chunks_per_file=20,
        )

    def test_validate_upload_rejects_unknown_extension(self):
        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            validate_upload("notes.exe", 100, self.settings)

    def test_parse_text_chunks_and_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "notes.md"
            path.write_text(
                "# Project Notes\n\nAlpha beta gamma.\n\nDelta epsilon.",
                encoding="utf-8",
            )

            parsed = parse_document_file(
                path,
                filename="notes.md",
                mime_type=infer_mime_type("notes.md"),
                settings=self.settings,
            )
            records = chunks_to_records(parsed.chunks, file_id="file_test")

        self.assertEqual(parsed.parser, "text")
        self.assertEqual(parsed.title, "notes.md")
        self.assertGreaterEqual(len(parsed.chunks), 1)
        self.assertEqual(records[0]["file_id"], "file_test")
        self.assertIn("Project Notes", records[0]["text"])

    def test_parse_csv_adds_summary_and_row_locator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "people.csv"
            path.write_text(
                "name,role\nAda,Researcher\nGrace,Engineer\n", encoding="utf-8"
            )

            parsed = parse_document_file(
                path,
                filename="people.csv",
                mime_type="text/csv",
                settings=self.settings,
            )

        self.assertEqual(parsed.parser, "csv")
        self.assertEqual(parsed.chunks[0].section, "CSV summary")
        self.assertEqual(parsed.chunks[1].row_start, 1)
        self.assertEqual(parsed.chunks[1].row_end, 2)

    def test_parse_docx_reads_document_xml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Document heading</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Document body text.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """,
                )

            parsed = parse_document_file(
                path,
                filename="sample.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                settings=self.settings,
            )

        self.assertEqual(parsed.parser, "docx")
        self.assertIn("Document heading", parsed.text)
        self.assertIn("Document body text.", parsed.chunks[0].text)


if __name__ == "__main__":
    unittest.main()
