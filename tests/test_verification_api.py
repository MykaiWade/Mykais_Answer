"""API tests for account signup, contacts, and verification routes in server.py."""

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class VerificationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        root = Path(cls.temp_directory.name)
        cls.database_path = root / "test.db"
        cls.roster_path = root / "verified.txt"
        cls.questions_path = root / "questions.txt"
        cls.roster_path.write_text(
            "// member roster\n"
            "Erica Concepcion 1 #\n"
            "Ruben Cerpa-Melendez 2 #\n"
            "Noah Callender 3 #\n"
            "Jalen Surles 4 #\n"
            "Mykai Wade 5 #\n",
            encoding="utf-8",
        )
        con = sqlite3.connect(cls.database_path)
        con.execute(
            "CREATE TABLE profiles ("
            "user_id TEXT PRIMARY KEY, real_name TEXT NOT NULL, "
            "verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, "
            "email TEXT, password_hash TEXT)"
        )
        con.execute(
            "INSERT INTO profiles "
            "(user_id, real_name, verified, created, email, password_hash) "
            "VALUES (?, ?, 0, ?, ?, '')",
            ("mykai-test-id", "Mykai Wade", time.time(), "mykai@example.test"),
        )
        con.commit()
        con.close()

        cls.env_keys = (
            "MYKAIS_DB_FILE",
            "MYKAIS_VERIFIED_FILE",
            "PUBLIC_BASE_URL",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
        )
        cls.previous_env = {key: os.environ.get(key) for key in cls.env_keys}
        os.environ.update({
            "MYKAIS_DB_FILE": str(cls.database_path),
            "MYKAIS_VERIFIED_FILE": str(cls.roster_path),
            "PUBLIC_BASE_URL": "https://mykaianswer.test",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "sender@example.test",
            "SMTP_PASSWORD": "test-password",
            "SMTP_FROM": "sender@example.test",
        })

        sys.modules.pop("server", None)
        import server

        cls.server = server
        con = sqlite3.connect(cls.database_path)
        con.execute(
            "UPDATE profiles SET password_hash = ? WHERE user_id = ?",
            (server.password_hash("MykaiTestPassword123!"), "mykai-test-id"),
        )
        con.commit()
        con.close()
        cls.client = TestClient(server.app, base_url="https://mykaianswer.test")
        cls.other_client = TestClient(server.app, base_url="https://mykaianswer.test")
        cls.anonymous_client = TestClient(server.app, base_url="https://mykaianswer.test")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.other_client.close()
        cls.anonymous_client.close()
        sys.modules.pop("server", None)
        for key, value in cls.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.temp_directory.cleanup()

    def test_only_mykai_can_use_single_use_qr_to_approve_member(self):
        origin = {"Origin": "https://mykaianswer.test"}
        with patch("server.send_verification_email") as send_email:
            response = self.client.post(
                "/api/auth/register",
                headers=origin,
                json={
                    "real_name": "New Member",
                    "email": "new-member@example.test",
                    "password": "NewMemberPassword123!",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["account_number"], 6)
        self.assertTrue(response.json()["verification_email_sent"])
        verification_link = send_email.call_args.args[3]
        token = verification_link.split("#", 1)[1]
        self.assertIn("New Member 6\n", self.roster_path.read_text(encoding="utf-8"))

        rejected = self.client.post(
            "/api/verification/request",
            headers=origin,
            json={"token": token},
        )
        self.assertEqual(rejected.status_code, 403)

        login = self.client.post(
            "/api/auth/login",
            headers=origin,
            json={
                "email": "mykai@example.test",
                "password": "MykaiTestPassword123!",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["account_number"], 5)
        self.assertTrue(login.json()["verified"])

        details = self.client.post(
            "/api/verification/request",
            headers=origin,
            json={"token": token},
        )
        self.assertEqual(details.status_code, 200, details.text)
        self.assertEqual(details.json()["real_name"], "New Member")

        approved = self.client.post(
            "/api/verification/approve",
            headers=origin,
            json={"token": token},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["verified"])
        self.assertIn("New Member 6 #", self.roster_path.read_text(encoding="utf-8"))

        reused = self.client.post(
            "/api/verification/request",
            headers=origin,
            json={"token": token},
        )
        self.assertEqual(reused.status_code, 404)

        with patch("server.send_verification_email"):
            contact_registration = self.other_client.post(
                "/api/auth/register",
                headers=origin,
                json={
                    "real_name": "Contact Member",
                    "email": "contact-member@example.test",
                    "password": "ContactMemberPassword123!",
                },
            )
        self.assertEqual(contact_registration.status_code, 200, contact_registration.text)
        public_id = contact_registration.json()["public_id"]

        profile_page = self.other_client.get("/profile.html")
        self.assertEqual(profile_page.status_code, 200, profile_page.text)
        self.assertIn("Show my QR code", profile_page.text)
        self.assertIn("Open camera to scan a QR code", profile_page.text)
        self.assertEqual(
            self.other_client.get("/profile-page.js").status_code,
            200,
        )
        self.assertEqual(
            self.other_client.get("/qr-scanner.umd.min.js").status_code,
            200,
        )
        self.assertEqual(
            self.other_client.get("/qr-scanner-worker.min.js").status_code,
            200,
        )
        self.assertEqual(self.other_client.get("/verified.txt").status_code, 404)

        public_profile = self.other_client.get("/api/public-profile/" + public_id)
        self.assertEqual(public_profile.status_code, 200, public_profile.text)
        self.assertEqual(public_profile.json()["real_name"], "Contact Member")
        self.assertNotIn("email", public_profile.json())

        profile_qr = self.client.get("/api/profile/qr")
        self.assertEqual(profile_qr.status_code, 200, profile_qr.text)
        self.assertEqual(profile_qr.headers["content-type"], "image/png")
        self.assertTrue(profile_qr.content.startswith(b"\x89PNG\r\n\x1a\n"))

        anonymous_request = self.anonymous_client.post(
            "/api/contacts",
            headers=origin,
            json={"public_id": public_id},
        )
        self.assertEqual(anonymous_request.status_code, 401)

        contact_add = self.client.post(
            "/api/contacts",
            headers=origin,
            json={"public_id": public_id},
        )
        self.assertEqual(contact_add.status_code, 200, contact_add.text)
        self.assertTrue(contact_add.json()["connected"])

        verifier_view = self.client.get("/api/public-profile/" + public_id)
        self.assertTrue(verifier_view.json()["can_verify"])
        rejected_verify = self.other_client.post(
            "/api/verification/approve-profile",
            headers=origin,
            json={"public_id": public_id},
        )
        self.assertEqual(rejected_verify.status_code, 403)

        direct_approval = self.client.post(
            "/api/verification/approve-profile",
            headers=origin,
            json={"public_id": public_id},
        )
        self.assertEqual(direct_approval.status_code, 200, direct_approval.text)
        self.assertTrue(direct_approval.json()["verified"])
        self.assertIn("Contact Member 7 #", self.roster_path.read_text(encoding="utf-8"))

        contact_login = self.other_client.post(
            "/api/auth/login",
            headers=origin,
            json={
                "email": "contact-member@example.test",
                "password": "ContactMemberPassword123!",
            },
        )
        self.assertEqual(contact_login.status_code, 200, contact_login.text)
        self.assertEqual(len(self.other_client.get("/api/contacts").json()["contacts"]), 1)
        self.assertEqual(len(self.client.get("/api/contacts").json()["contacts"]), 1)

    def test_questions_are_appended_and_remain_visible_to_their_author(self):
        origin = {"Origin": "https://mykaianswer.test"}
        login = self.client.post(
            "/api/auth/login",
            headers=origin,
            json={
                "email": "mykai@example.test",
                "password": "MykaiTestPassword123!",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)

        with patch("server.QUESTIONS_FILE", self.questions_path):
            submitted = "How do I save a question?"
            response = self.client.post(
                "/api/questions",
                headers=origin,
                json={"question": submitted},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(submitted + "\n", self.questions_path.read_text(encoding="utf-8"))

            mine = self.client.get("/api/questions/me")
            self.assertEqual(mine.status_code, 200, mine.text)
            self.assertTrue(any(
                question["question"] == submitted
                for question in mine.json()["questions"]
            ))

            room_question = "Where can we discuss this?"
            room = self.client.post(
                "/api/public-rooms",
                headers=origin,
                json={"question": room_question},
            )
            self.assertEqual(room.status_code, 200, room.text)
            self.assertIn(
                room_question + "\n",
                self.questions_path.read_text(encoding="utf-8"),
            )

            failed_question = "This should not be saved."
            missing_directory = self.questions_path.parent / "missing"
            with patch("server.QUESTIONS_FILE", missing_directory / "questions.txt"):
                failed_response = self.client.post(
                    "/api/questions",
                    headers=origin,
                    json={"question": failed_question},
                )
            self.assertEqual(failed_response.status_code, 500)
            mine = self.client.get("/api/questions/me")
            self.assertFalse(any(
                question["question"] == failed_question
                for question in mine.json()["questions"]
            ))

    def test_registration_survives_email_failure_and_account_can_sign_in(self):
        con = self.server.db()
        con.execute("DELETE FROM verification_mail_events")
        con.commit()
        con.close()

        origin = {"Origin": "https://mykaianswer.test"}
        account = {
            "real_name": "Email Unavailable",
            "email": "email-unavailable@example.test",
            "password": "EmailUnavailable123!",
        }
        with patch(
            "server.send_verification_email",
            side_effect=ValueError("Email delivery is not configured."),
        ):
            registration = self.anonymous_client.post(
                "/api/auth/register",
                headers=origin,
                json=account,
            )

        self.assertEqual(registration.status_code, 200, registration.text)
        self.assertFalse(registration.json()["verification_email_sent"])
        self.assertEqual(registration.json()["real_name"], account["real_name"])

        login = self.anonymous_client.post(
            "/api/auth/login",
            headers=origin,
            json={
                "email": account["email"],
                "password": account["password"],
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["real_name"], account["real_name"])

    def test_removed_roster_account_is_not_restored_on_startup(self):
        user_id = "removed-roster-test-id"
        con = self.server.db()
        con.execute(
            "INSERT INTO profiles "
            "(user_id, real_name, verified, created, email, password_hash, "
            "account_number) VALUES (?, ?, 1, ?, ?, '', ?)",
            (user_id, "Removed Duplicate", time.time(), "removed@example.test", 99),
        )
        con.commit()
        con.close()

        try:
            roster_before = self.roster_path.read_text(encoding="utf-8")
            self.server.synchronize_verification_roster()

            self.assertEqual(
                self.roster_path.read_text(encoding="utf-8"),
                roster_before,
            )
            con = self.server.db()
            profile = con.execute(
                "SELECT verified FROM profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            con.close()
            self.assertEqual(profile["verified"], 0)
        finally:
            con = self.server.db()
            con.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
            con.commit()
            con.close()


if __name__ == "__main__":
    unittest.main()
