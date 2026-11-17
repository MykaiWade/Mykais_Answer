import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from build_pages import ALLOWED_SCRIPTS, EXPECTED_OUTPUT, build_pages


class LocalReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"a", "link"} and "href" in attributes:
            self.references.append(attributes["href"])
        if tag in {"script", "img"} and "src" in attributes:
            self.references.append(attributes["src"])


class GitHubPagesBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name) / "preview"
        build_pages(self.output_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_contains_only_approved_public_files(self):
        self.assertEqual({path.name for path in self.output_dir.iterdir()}, EXPECTED_OUTPUT)
        self.assertNotIn("server.py", EXPECTED_OUTPUT)
        self.assertNotIn("chat.db", EXPECTED_OUTPUT)

    def test_local_page_references_resolve(self):
        for page in self.output_dir.glob("*.html"):
            parser = LocalReferenceParser()
            parser.feed(page.read_text(encoding="utf-8"))
            for reference in parser.references:
                parsed = urlsplit(reference)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                with self.subTest(page=page.name, reference=reference):
                    target = (self.output_dir / parsed.path).resolve()
                    self.assertTrue(target.is_relative_to(self.output_dir.resolve()))
                    self.assertTrue(target.is_file())

    def test_pages_show_preview_notice_disable_forms_and_remove_backend_scripts(self):
        for page in self.output_dir.glob("*.html"):
            html = page.read_text(encoding="utf-8")
            parser = LocalReferenceParser()
            parser.feed(html)
            script_sources = [
                urlsplit(reference).path.rsplit("/", 1)[-1]
                for reference in parser.references
                if reference.lower().endswith(".js")
            ]
            with self.subTest(page=page.name):
                self.assertIn("GitHub Pages preview only", html)
                self.assertIn("event.stopImmediatePropagation()", html)
                self.assertTrue(set(script_sources).issubset(ALLOWED_SCRIPTS))


if __name__ == "__main__":
    unittest.main()
