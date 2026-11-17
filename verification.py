"""Verification helpers used by server.py with verified.txt and SMTP settings."""

import io
import os
import re
import secrets
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

import qrcode


_ROSTER_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<number>[1-9]\d*)(?:\s+(?P<marker>#))?$")


@dataclass(frozen=True)
class RosterEntry:
    number: int
    name: str
    verified: bool


def parse_roster(text):
    """Parse member numbers and verification markers from verified.txt."""
    headers = []
    entries = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            headers.append(line.rstrip())
            continue

        match = _ROSTER_LINE.fullmatch(stripped)
        if not match:
            raise ValueError(
                f"verified.txt line {line_number} must be 'Name Number' "
                "with an optional trailing #."
            )
        number = int(match.group("number"))
        if number in entries:
            raise ValueError(f"verified.txt has duplicate member number {number}.")
        entries[number] = RosterEntry(
            number=number,
            name=match.group("name").strip(),
            verified=bool(match.group("marker")),
        )
    return headers, entries


def read_roster(path):
    return parse_roster(Path(path).read_text(encoding="utf-8"))


def next_member_number(entries, existing_numbers=()):
    numbers = set(entries) | {int(number) for number in existing_numbers if number is not None}
    return max(numbers, default=0) + 1


def write_roster(path, headers, entries):
    """Save the roster atomically so a partial write cannot corrupt it."""
    path = Path(path)
    header_lines = list(headers)
    while header_lines and not header_lines[-1].strip():
        header_lines.pop()

    lines = header_lines
    if entries:
        if lines:
            lines.append("")
        for number in sorted(entries):
            entry = entries[number]
            marker = " #" if entry.verified else ""
            lines.append(f"{entry.name} {number}{marker}")

    temporary_path = path.with_name(path.name + ".tmp")
    try:
        temporary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def new_verification_token():
    """Create a random, one-time token for the email verification QR."""
    return secrets.token_urlsafe(32)


def hash_verification_token(token):
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verification_url(base_url, token):
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS URL.")
    return base_url.rstrip("/") + "/verify.html#" + token


def qr_code_png(value):
    image = qrcode.make(value)
    image_data = io.BytesIO()
    image.save(image_data, format="PNG")
    return image_data.getvalue()


def send_verification_email(email, name, account_number, link):
    """Email the member's verification link as both text and a QR image."""
    settings = {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "username": os.environ.get("SMTP_USERNAME", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("SMTP_FROM", "").strip(),
    }
    missing = [key for key, value in settings.items() if not value]
    if missing:
        names = ", ".join("SMTP_" + key.upper() for key in missing)
        raise ValueError(f"Email delivery is not configured; set {names}.")

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as error:
        raise ValueError("SMTP_PORT must be a valid port number.") from error
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT must be between 1 and 65535.")

    message = EmailMessage()
    message["Subject"] = "Your Mykai's Answer verification QR code"
    message["From"] = settings["sender"]
    message["To"] = email
    message.set_content(
        f"Hello {name},\n\n"
        f"Your account number is {account_number}. Show the attached QR code "
        "to Mykai Wade (#5) for review. Only that signed-in account can approve "
        "verification, and approval requires an explicit confirmation.\n\n"
        "This one-time QR code expires in 24 hours. If it expires, sign in and "
        "request a new code from the account page.\n\n"
        f"Verification link: {link}\n"
    )
    message.add_attachment(
        qr_code_png(link),
        maintype="image",
        subtype="png",
        filename=f"verification-{account_number}.png",
    )

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(
            settings["host"], port, timeout=20, context=context
        ) as server:
            server.login(settings["username"], settings["password"])
            server.send_message(message)
    else:
        with smtplib.SMTP(settings["host"], port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings["username"], settings["password"])
            server.send_message(message)
