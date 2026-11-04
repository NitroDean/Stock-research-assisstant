"""Focused checks for PDF indexing, grounded answers, and document links."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

import app


def text_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Revenue increased in the latest quarter.) Tj ET")
    ref = writer._add_object(stream)
    page[NameObject("/Contents")] = ref
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class AppChecks(unittest.TestCase):
    def test_index_search_and_grounded_source(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app, "DATA", Path(temp)), patch.object(app, "FILES", Path(temp) / "files"), patch.object(app, "DB", Path(temp) / "index.sqlite3"), patch.object(app, "embed_many", side_effect=RuntimeError("no model")):
                with app.connection() as db:
                    result = app.index_pdf(db, "Quarterly report.pdf", text_pdf())
                    self.assertEqual(result["pages"], 1)
                    self.assertGreater(result["chunks"], 0)
                    found = app.search(db, "Did revenue increase?")
                    self.assertEqual(found[0]["name"], "Quarterly report.pdf")
                    self.assertEqual(found[0]["page"], 1)
                    with patch.object(app, "ollama", return_value={"message": {"content": "Revenue increased [1]."}}):
                        response = app.answer(db, "Did revenue increase?")
                    self.assertIn("[1]", response["answer"])
                    self.assertEqual(response["sources"][0]["name"], "Quarterly report.pdf")
                    self.assertEqual(response["sources"][0]["page"], 1)
                    self.assertTrue((app.FILES / f"{result['id']}.pdf").is_file())

    def test_rejects_non_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app, "DATA", Path(temp)), patch.object(app, "FILES", Path(temp) / "files"), patch.object(app, "DB", Path(temp) / "index.sqlite3"):
                with app.connection() as db:
                    with self.assertRaises(ValueError):
                        app.index_pdf(db, "fake.pdf", b"not a PDF")


if __name__ == "__main__":
    unittest.main()
