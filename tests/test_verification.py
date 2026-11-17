"""Unit tests for roster, token, QR, and email helpers in verification.py."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verification import (
    RosterEntry,
    hash_verification_token,
    new_verification_token,
    next_member_number,
    parse_roster,
    read_roster,
    send_verification_email,
    verification_url,
    write_roster,
)


class VerificationRosterTests(unittest.TestCase):
    def test_parse_roster_preserves_numbers_and_markers(self):
        headers, entries = parse_roster(
            "// member list\n\nMykai Wade 5 #\nNew Member 6\n"
        )

        self.assertIn("// member list", headers)
        self.assertEqual(entries[5], RosterEntry(5, "Mykai Wade", True))
        self.assertEqual(entries[6], RosterEntry(6, "New Member", False))

    def test_duplicate_numbers_and_malformed_rows_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate member number"):
            parse_roster("First Member 1 #\nSecond Member 1\n")
        with self.assertRaisesRegex(ValueError, "line 1"):
            parse_roster("First Member is verified\n")

    def test_new_member_number_follows_roster_and_database(self):
        self.assertEqual(next_member_number({1: None, 5: None}, [7]), 8)

    def test_write_roster_preserves_verified_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verified.txt"
            headers, entries = parse_roster("// roster\nMykai Wade 5 #\n")
            entries[6] = RosterEntry(6, "New Member", False)

            write_roster(path, headers, entries)
            saved_headers, saved_entries = read_roster(path)

            self.assertIn("// roster", saved_headers)
            self.assertTrue(saved_entries[5].verified)
            self.assertFalse(saved_entries[6].verified)

    def test_verification_url_keeps_token_in_fragment_and_requires_https(self):
        token = new_verification_token()
        url = verification_url("https://mykaianswer.com/", token)

        self.assertEqual(url, f"https://mykaianswer.com/verify.html#{token}")
        self.assertNotEqual(hash_verification_token(token), token)
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            verification_url("http://mykaianswer.com", token)

    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "sender@example.test",
        "SMTP_PASSWORD": "test-password",
        "SMTP_FROM": "sender@example.test",
    })
    @patch("verification.smtplib.SMTP")
    def test_email_contains_qr_image_without_connecting_to_smtp(self, smtp):
        server = smtp.return_value.__enter__.return_value

        send_verification_email(
            "member@example.test",
            "New Member",
            6,
            "https://mykaianswer.com/verify.html#test-token",
        )

        message = server.send_message.call_args.args[0]
        attachments = list(message.iter_attachments())
        self.assertEqual(message["To"], "member@example.test")
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_content_type(), "image/png")
        server.starttls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
