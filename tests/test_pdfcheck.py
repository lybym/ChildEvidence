import unittest

from research_library.pdfcheck import count_pages, has_eof_marker, sniff_pdf, validate_pdf

from helpers import HTML_BYTES, JUNK_BYTES, make_pdf, make_tmp_dir


class PdfCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("pdf-")

    def _write(self, name, data):
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def test_valid_pdf(self):
        p = self._write("one.pdf", make_pdf(1))
        v = validate_pdf(p)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["page_count"], 1)
        self.assertEqual(v["page_count_method"], "raw_scan")
        self.assertTrue(sniff_pdf(p))
        self.assertTrue(has_eof_marker(p))

    def test_two_page_pdf(self):
        p = self._write("two.pdf", make_pdf(2))
        v = validate_pdf(p)
        self.assertTrue(v["ok"])
        count, method = count_pages(p)
        self.assertEqual(count, 2)

    def test_html_rejected(self):
        p = self._write("login.pdf", HTML_BYTES)
        v = validate_pdf(p)
        self.assertFalse(v["ok"])
        self.assertIn("no_pdf_header", v["checks"])

    def test_junk_rejected(self):
        p = self._write("junk.pdf", JUNK_BYTES)
        v = validate_pdf(p)
        self.assertFalse(v["ok"])

    def test_truncated_pdf_rejected(self):
        data = make_pdf(1)
        p = self._write("trunc.pdf", data[: len(data) // 2])
        v = validate_pdf(p)
        self.assertFalse(v["ok"])
        self.assertTrue("no_eof_marker" in v["checks"] or "too_small" in v["checks"], v["checks"])

    def test_tiny_pdf_rejected(self):
        p = self._write("tiny.pdf", b"%PDF-1.4\n%%EOF\n")
        v = validate_pdf(p)
        self.assertFalse(v["ok"])
        self.assertIn("too_small", v["checks"])

    def test_missing_file(self):
        v = validate_pdf(self.tmp / "nope.pdf")
        self.assertFalse(v["ok"])
        self.assertIn("missing_file", v["checks"])


if __name__ == "__main__":
    unittest.main()
