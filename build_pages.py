"""Build the static GitHub Pages preview without publishing server-only features."""

import argparse
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
PAGES = ("index.html", "ask.html", "chat.html", "about.html", "ask-mykai.html", "profile.html")
ASSETS = ("styles.css", "badges.txt", "badge-picker.js", "badges.js")
ALLOWED_SCRIPTS = {"badge-picker.js", "badges.js"}
EXPECTED_OUTPUT = set(PAGES + ASSETS + (".nojekyll",))
SCRIPT_PATTERN = re.compile(r"<script\b([^>]*)>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
SCRIPT_SOURCE_PATTERN = re.compile(
    r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE
)
BODY_PATTERN = re.compile(r"<body(?:\s[^>]*)?>", re.IGNORECASE)

PREVIEW_NOTICE = (
    '<aside role="note" style="display:block;background:#fff3cd;color:#4b3b00;'
    'border:1px solid #d6a900;padding:10px 12px;margin:0 0 16px;border-radius:6px;'
    'font-size:14px">GitHub Pages preview only: forms, accounts, questions, rooms, '
    "and chat need the Python server.</aside>"
)
DISABLE_FORMS = (
    '<script>document.addEventListener("submit",function(event){'
    "event.preventDefault();event.stopImmediatePropagation();},true);</script>"
)


def _keep_preview_script(match):
    source_match = SCRIPT_SOURCE_PATTERN.search(match.group(1))
    if not source_match:
        return match.group(0)
    source = next(value for value in source_match.groups() if value is not None)
    if Path(urlsplit(source).path).name in ALLOWED_SCRIPTS:
        return match.group(0)
    return ""


def build_pages(output_dir):
    output_dir = Path(output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)
    unexpected = {path.name for path in output_dir.iterdir()} - EXPECTED_OUTPUT
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError("Output directory contains files outside the Pages build: " + names)

    for filename in PAGES:
        source = (ROOT / filename).read_text(encoding="utf-8")
        page = SCRIPT_PATTERN.sub(_keep_preview_script, source)
        page, body_count = BODY_PATTERN.subn(
            lambda match: match.group(0) + PREVIEW_NOTICE + DISABLE_FORMS,
            page,
            count=1,
        )
        if body_count != 1:
            raise ValueError(filename + " must contain a body element.")
        (output_dir / filename).write_text(page, encoding="utf-8")

    for filename in ASSETS:
        shutil.copyfile(ROOT / filename, output_dir / filename)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    actual_output = {path.name for path in output_dir.iterdir()}
    if actual_output != EXPECTED_OUTPUT:
        raise RuntimeError("The Pages output does not match the approved file list.")
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages preview.")
    parser.add_argument("--output", default="_site", help="Output directory (default: _site)")
    args = parser.parse_args()
    output_dir = build_pages(args.output)
    print("GitHub Pages preview built at " + str(output_dir))


if __name__ == "__main__":
    main()
