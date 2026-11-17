"""Check that website pages have their basic structure and working local links."""

import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Find the website root from this test file's location.
ROOT = Path(__file__).resolve().parents[1]


class LocalReferenceParser(HTMLParser):
    """Collect file paths used by HTML links and scripts."""

    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        # Save links and assets so the tests can check that each file exists.
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.references.append(value)


class SitePageTests(unittest.TestCase):
    # Every page should include the browser title and visible page body.
    def test_every_html_page_has_a_title_and_body(self):
        pages = sorted(ROOT.glob("*.html"))
        self.assertTrue(pages, "No HTML pages were found.")

        for page in pages:
            with self.subTest(page=page.name):
                html = page.read_text(encoding="utf-8").lower()
                self.assertIn("<title>", html)
                self.assertIn("<body", html)

    # Local links and assets should point to files inside the website folder.
    def test_local_links_and_assets_exist_for_every_html_page(self):
        pages = sorted(ROOT.glob("*.html"))
        self.assertTrue(pages, "No HTML pages were found.")

        for page in pages:
            parser = LocalReferenceParser()
            parser.feed(page.read_text(encoding="utf-8"))
            for reference in parser.references:
                parsed = urlsplit(reference)
                # External URLs and links without a file path need no file check.
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                relative_path = unquote(parsed.path).lstrip("/")
                target = (ROOT / relative_path).resolve()
                with self.subTest(page=page.name, reference=reference):
                    self.assertTrue(target.is_relative_to(ROOT))
                    self.assertTrue(target.is_file())


# Run the tests when this file is started directly.
if __name__ == "__main__":
    unittest.main()
