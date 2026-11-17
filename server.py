# - Runs the FastAPI app for accounts, public questions, badge matching, and live chat.
# - Serves the HTML/CSS/JavaScript files and reads/writes chat.db for saved data.
# - Browser scripts such as profile.js, profile-page.js, and chat.js call its API routes.
# - Verification helpers are in verification.py; approved member numbers come from verified.txt.
# - Start locally with: python server.py (press Ctrl+C to stop).

# --- Imports: tools this file borrows. You only add one if you use a new tool. ---
import base64
import os        # Works with file paths and folders.
import hashlib   # Hashes passwords and session tokens before saving them.
import hmac      # Compares password hashes without timing leaks.
import json      # Stores each question's selected badges in the database.
import re        # "Regular expressions": finds patterns in text (used to split text into words).
import secrets   # Creates unpredictable profile IDs.
import smtplib
import sqlite3   # The database. It stores everything in one file (chat.db).
import time      # Gives the current time, so each message gets a timestamp.
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from dotenv import load_dotenv
import uvicorn   # The program that actually runs the web server.
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect  # The web framework: routes, errors, live chat.
from fastapi.responses import FileResponse, JSONResponse, Response  # Sends pages and API responses.
from pydantic import BaseModel, Field        # Describes what data a form submission must contain.
from verification import (
    RosterEntry,
    hash_verification_token,
    new_verification_token,
    next_member_number,
    qr_code_png,
    read_roster,
    send_verification_email,
    verification_url,
    write_roster,
)

# Creates the web app. Every "@app..." line below attaches a feature to it.
app = FastAPI()

# The folder this file is in. Pages and the database are found relative to it.
# CHANGE: normally leave this alone.
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(Path(HERE) / ".env")

# Where the database lives. It is created automatically the first time you run the server.
# CHANGE: rename "chat.db" if you want. If you delete the file, ALL questions and messages are erased.
DB_FILE = os.environ.get("MYKAIS_DB_FILE", os.path.join(HERE, "chat.db"))
VERIFIED_FILE = Path(
    os.environ.get("MYKAIS_VERIFIED_FILE", Path(HERE) / "verified.txt")
)
VERIFIER_ACCOUNT_NUMBER = 5
VERIFICATION_REQUEST_LIFETIME = 24 * 60 * 60
PUBLIC_PROFILE_ID_BYTES = 18

# The only pages visitors are allowed to open. This is a safety list: it stops people from
# downloading server.py or chat.db through the browser.
# CHANGE: when you create a new page (like faq.html), add its name here without ".html": "faq".
PAGES = {"index", "ask", "chat", "about", "ask-mykai", "profile", "verify"}

# Size limits, so nobody can flood the server with huge text.
# CHANGE: raise or lower these numbers. If you change them, also change the matching
# maxlength="..." numbers in ask.html and chat.html so the boxes agree.
MAX_QUESTION = 100      # Most characters allowed in a question.
MAX_DESCRIPTION = 200  # Most characters allowed in a description.
MAX_MESSAGE = 500       # Most characters allowed in one chat message.
SESSION_DAYS = 30        # How long a sign-in stays active on this browser.
PASSWORD_ITERATIONS = 310_000  # PBKDF2 work factor used to store passwords safely.
SESSION_COOKIE = "mykais_session"


# =====================================================================
# DATABASE HELPERS
# =====================================================================

def db():
    # Opens a connection to the database file. Other functions call this when they need data.
    con = sqlite3.connect(DB_FILE)
    # Lets us read a row by column name (row["text"]) instead of by number (row[2]).
    con.row_factory = sqlite3.Row
    return con


def setup_database():
    # Runs once at startup. Creates the two tables (like spreadsheets) if they don't exist yet.
    con = db()

    # The roster file is authoritative; this column is kept in sync for older data.
    con.execute(
        "CREATE TABLE IF NOT EXISTS profiles ("
        "user_id TEXT PRIMARY KEY, real_name TEXT NOT NULL, "
        "verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, "
        "account_number INTEGER, public_id TEXT, "
        "email TEXT, password_hash TEXT)"
    )
    profile_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(profiles)").fetchall()
    }
    if "email" not in profile_columns:
        con.execute("ALTER TABLE profiles ADD COLUMN email TEXT")
    if "password_hash" not in profile_columns:
        con.execute("ALTER TABLE profiles ADD COLUMN password_hash TEXT")
    if "account_number" not in profile_columns:
        con.execute("ALTER TABLE profiles ADD COLUMN account_number INTEGER")
    if "public_id" not in profile_columns:
        con.execute("ALTER TABLE profiles ADD COLUMN public_id TEXT")
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS profiles_public_id_unique "
        "ON profiles(public_id) WHERE public_id IS NOT NULL"
    )
    profiles_without_public_id = con.execute(
        "SELECT user_id FROM profiles WHERE public_id IS NULL"
    ).fetchall()
    for profile in profiles_without_public_id:
        con.execute(
            "UPDATE profiles SET public_id = ? WHERE user_id = ?",
            (secrets.token_urlsafe(PUBLIC_PROFILE_ID_BYTES), profile["user_id"]),
        )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS profiles_account_number_unique "
        "ON profiles(account_number) WHERE account_number IS NOT NULL"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS profiles_email_unique "
        "ON profiles(email COLLATE NOCASE) WHERE email IS NOT NULL"
    )

    # Store only hashes of random session tokens, never the browser's cookie value.
    con.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS verification_requests ("
        "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
        "created REAL NOT NULL, expires REAL NOT NULL, used_at REAL)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS verification_requests_user "
        "ON verification_requests(user_id, expires)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS verification_mail_events ("
        "ip_hash TEXT NOT NULL, created REAL NOT NULL)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS verification_mail_events_ip_created "
        "ON verification_mail_events(ip_hash, created)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS contact_requests ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, requester_id TEXT NOT NULL, "
        "target_id TEXT NOT NULL, created REAL NOT NULL, "
        "UNIQUE(requester_id, target_id))"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS contact_requests_target "
        "ON contact_requests(target_id, created)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS contacts ("
        "user_id TEXT NOT NULL, contact_user_id TEXT NOT NULL, created REAL NOT NULL, "
        "PRIMARY KEY(user_id, contact_user_id), CHECK(user_id != contact_user_id))"
    )

    # Table 1: questions. Each row = one submitted question.
    # id = a number that goes up by 1 each time (1, 2, 3...). user_id = which browser asked it.
    # Existing databases get the tags column below without losing saved questions.
    con.execute(
        "CREATE TABLE IF NOT EXISTS questions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, "
        "question TEXT, description TEXT, created REAL, tags TEXT NOT NULL DEFAULT '[]')"
    )
    question_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(questions)").fetchall()
    }
    if "tags" not in question_columns:
        con.execute("ALTER TABLE questions ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")

    # Table 2: messages. Each row = one chat message.
    # room = which chat it belongs to (like "3-7"). text = what was typed.
    con.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT, "
        "user_id TEXT, text TEXT, created REAL)"
    )

    con.commit()   # Saves the changes.
    con.close()    # Closes the connection. Always do this when you're finished.


setup_database()   # Actually runs the function above when the server starts.


def roster_verified(account_number, real_name, entries=None):
    if account_number is None:
        return False
    if entries is None:
        _, entries = read_roster(VERIFIED_FILE)
    entry = entries.get(account_number)
    return bool(
        entry
        and entry.name.casefold() == real_name.casefold()
        and entry.verified
    )


def synchronize_verification_roster():
    headers, entries = read_roster(VERIFIED_FILE)
    original_headers = list(headers)
    original_entries = dict(entries)
    con = db()
    roster_changed = False
    try:
        con.execute("BEGIN IMMEDIATE")
        profiles = con.execute(
            "SELECT user_id, real_name, account_number FROM profiles "
            "WHERE email IS NOT NULL ORDER BY created, user_id"
        ).fetchall()
        name_counts = {}
        for profile in profiles:
            normalized_name = profile["real_name"].casefold()
            name_counts[normalized_name] = name_counts.get(normalized_name, 0) + 1

        used_numbers = set()
        for profile in profiles:
            number = profile["account_number"]
            if number is None:
                continue
            entry = entries.get(number)
            if entry is None:
                entries[number] = RosterEntry(number, profile["real_name"], False)
                roster_changed = True
            elif entry.name.casefold() != profile["real_name"].casefold():
                raise RuntimeError(
                    f"Roster number {number} does not match its saved account name."
                )
            used_numbers.add(number)

        for profile in profiles:
            if profile["account_number"] is not None:
                continue
            normalized_name = profile["real_name"].casefold()
            matching_numbers = [
                number for number, entry in entries.items()
                if number not in used_numbers
                and entry.name.casefold() == normalized_name
            ]
            if name_counts[normalized_name] == 1 and len(matching_numbers) == 1:
                number = matching_numbers[0]
            else:
                number = next_member_number(entries, used_numbers)
                entries[number] = RosterEntry(number, profile["real_name"], False)
                roster_changed = True
            con.execute(
                "UPDATE profiles SET account_number = ? WHERE user_id = ?",
                (number, profile["user_id"]),
            )
            used_numbers.add(number)

        for profile in profiles:
            number = profile["account_number"]
            if number is None:
                number = con.execute(
                    "SELECT account_number FROM profiles WHERE user_id = ?",
                    (profile["user_id"],),
                ).fetchone()["account_number"]
            verified = roster_verified(number, profile["real_name"], entries)
            con.execute(
                "UPDATE profiles SET verified = ? WHERE user_id = ?",
                (int(verified), profile["user_id"]),
            )

        if roster_changed:
            write_roster(VERIFIED_FILE, headers, entries)
        con.commit()
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        con.rollback()
        if roster_changed:
            write_roster(VERIFIED_FILE, original_headers, original_entries)
        raise
    finally:
        con.close()


synchronize_verification_roster()


# =====================================================================
# ACCOUNTS
# Public names are claims; verification is controlled by verified.txt and Mykai's approval.
# =====================================================================

class RegisterAccount(BaseModel):
    real_name: str
    email: str
    password: str
    legacy_user_id: Optional[str] = None


class LoginAccount(BaseModel):
    email: str
    password: str


class VerificationToken(BaseModel):
    token: str = Field(min_length=30, max_length=128)


class ContactRequest(BaseModel):
    public_id: str = Field(min_length=20, max_length=64)


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def password_matches(password, stored_hash):
    try:
        iterations, salt_hex, digest_hex = stored_hash.split("$")
        iterations = int(iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if not 100_000 <= iterations <= 1_000_000 or len(salt) != 16 or len(expected) != 32:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def private_profile(con, token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    profile = con.execute(
        "SELECT profiles.user_id, profiles.real_name, profiles.account_number, "
        "profiles.public_id "
        "FROM sessions JOIN profiles ON profiles.user_id = sessions.user_id "
        "WHERE sessions.token_hash = ? AND sessions.expires > ?",
        (token_hash, time.time()),
    ).fetchone()
    if not profile:
        return None
    return {
        "user_id": profile["user_id"],
        "real_name": profile["real_name"],
        "account_number": profile["account_number"],
        "public_id": profile["public_id"],
        "verified": roster_verified(
            profile["account_number"], profile["real_name"]
        ),
    }


def set_session_cookie(response, token, request):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def finish_login(con, user_id, request, message, extra=None):
    # Remove expired sessions and store only this browser's new token hash.
    con.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    con.execute(
        "INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
        (token_hash, user_id, time.time() + SESSION_DAYS * 24 * 60 * 60),
    )
    profile = con.execute(
        "SELECT user_id, real_name, account_number, public_id "
        "FROM profiles WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    con.commit()
    data = {
        "message": message,
        "user_id": profile["user_id"],
        "real_name": profile["real_name"],
        "account_number": profile["account_number"],
        "public_id": profile["public_id"],
        "verified": roster_verified(
            profile["account_number"], profile["real_name"]
        ),
    }
    if extra:
        data.update(extra)
    response = JSONResponse(data)
    set_session_cookie(response, token, request)
    return response


def record_verification_email_event(con, request):
    client_ip = request.headers.get("cf-connecting-ip")
    if not client_ip and request.client:
        client_ip = request.client.host
    ip_hash = hashlib.sha256((client_ip or "unknown").encode("utf-8")).hexdigest()
    now = time.time()
    cutoff = now - 60 * 60
    con.execute("DELETE FROM verification_mail_events WHERE created <= ?", (cutoff,))
    sent = con.execute(
        "SELECT COUNT(*) FROM verification_mail_events "
        "WHERE ip_hash = ? AND created > ?",
        (ip_hash, cutoff),
    ).fetchone()[0]
    if sent >= 5:
        raise HTTPException(
            status_code=429,
            detail="Too many verification emails were requested from this connection. Try again later.",
        )
    con.execute(
        "INSERT INTO verification_mail_events (ip_hash, created) VALUES (?, ?)",
        (ip_hash, now),
    )


@app.post("/api/auth/register")
def register_account(account: RegisterAccount, request: Request):
    real_name = " ".join(account.real_name.split())
    email = account.email.strip().lower()
    password = account.password
    if not real_name or len(real_name) > 100 or any(ord(char) < 32 for char in real_name):
        raise HTTPException(status_code=400, detail="Enter a name up to 100 characters.")
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(status_code=400, detail="Use a password between 12 and 128 characters.")

    roster_changed = False
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        headers, entries = read_roster(VERIFIED_FILE)
        original_headers = list(headers)
        original_entries = dict(entries)
        record_verification_email_event(con, request)
        # Keep this browser's old questions/chats when it upgrades its old profile.
        legacy_id = (account.legacy_user_id or "")[:64]
        legacy = con.execute(
            "SELECT user_id, account_number FROM profiles "
            "WHERE user_id = ? AND email IS NULL "
            "AND password_hash IS NULL",
            (legacy_id,),
        ).fetchone() if legacy_id else None
        if legacy:
            user_id = legacy["user_id"]
            con.execute(
                "UPDATE profiles SET real_name = ?, email = ?, password_hash = ? "
                "WHERE user_id = ?",
                (real_name, email, password_hash(password), user_id),
            )
        else:
            user_id = secrets.token_urlsafe(32)
            con.execute(
                "INSERT INTO profiles "
                "(user_id, real_name, verified, created, email, password_hash, "
                "account_number, public_id) VALUES (?, ?, 0, ?, ?, ?, NULL, ?)",
                (
                    user_id,
                    real_name,
                    time.time(),
                    email,
                    password_hash(password),
                    secrets.token_urlsafe(PUBLIC_PROFILE_ID_BYTES),
                ),
            )
        profile = con.execute(
            "SELECT account_number FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        account_number = profile["account_number"]
        if account_number is None:
            existing_numbers = [
                row["account_number"]
                for row in con.execute(
                    "SELECT account_number FROM profiles WHERE account_number IS NOT NULL"
                )
            ]
            account_number = next_member_number(entries, existing_numbers)
            entries[account_number] = RosterEntry(
                account_number, real_name, False
            )
            write_roster(VERIFIED_FILE, headers, entries)
            roster_changed = True
            con.execute(
                "UPDATE profiles SET account_number = ?, verified = 0 "
                "WHERE user_id = ?",
                (account_number, user_id),
            )

        token = new_verification_token()
        con.execute(
            "DELETE FROM verification_requests WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        con.execute(
            "INSERT INTO verification_requests "
            "(token_hash, user_id, created, expires, used_at) VALUES (?, ?, ?, ?, NULL)",
            (
                hash_verification_token(token),
                user_id,
                time.time(),
                time.time() + VERIFICATION_REQUEST_LIFETIME,
            ),
        )
        link = verification_url(
            os.environ.get("PUBLIC_BASE_URL", "https://mykaianswer.com").strip(),
            token,
        )
        send_verification_email(email, real_name, account_number, link)
        return finish_login(
            con,
            user_id,
            request,
            "Account created.",
            {"verification_email_sent": True},
        )
    except sqlite3.IntegrityError:
        con.rollback()
        if roster_changed:
            write_roster(VERIFIED_FILE, original_headers, original_entries)
        raise HTTPException(status_code=409, detail="That email already has an account.")
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as error:
        con.rollback()
        if roster_changed:
            write_roster(VERIFIED_FILE, original_headers, original_entries)
        raise HTTPException(
            status_code=502,
            detail=f"Account was not created because its verification email failed: {error}",
        ) from error
    finally:
        con.close()


@app.post("/api/auth/login")
def login_account(account: LoginAccount, request: Request):
    email = account.email.strip().lower()
    con = db()
    profile = con.execute(
        "SELECT user_id, password_hash FROM profiles WHERE email = ? COLLATE NOCASE",
        (email,),
    ).fetchone()
    if not profile or not profile["password_hash"] or not password_matches(
        account.password, profile["password_hash"]
    ):
        con.close()
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    response = finish_login(con, profile["user_id"], request, "Signed in.")
    con.close()
    return response


@app.get("/api/auth/me")
def current_account(request: Request):
    con = db()
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
    con.close()
    if not profile:
        raise HTTPException(status_code=401, detail="Sign in to use your profile.")
    return {
        "user_id": profile["user_id"],
        "real_name": profile["real_name"],
        "account_number": profile["account_number"],
        "public_id": profile["public_id"],
        "verified": bool(profile["verified"]),
    }


@app.get("/api/public-profile/{public_id}")
def get_public_profile(public_id: str, request: Request):
    con = db()
    try:
        target = con.execute(
            "SELECT user_id, real_name, account_number, public_id "
            "FROM profiles WHERE public_id = ?",
            (public_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="This profile was not found.")

        viewer = private_profile(con, request.cookies.get(SESSION_COOKIE))
        relationship = "signed_out"
        if viewer:
            if viewer["user_id"] == target["user_id"]:
                relationship = "self"
            elif con.execute(
                "SELECT 1 FROM contacts WHERE user_id = ? AND contact_user_id = ?",
                (viewer["user_id"], target["user_id"]),
            ).fetchone():
                relationship = "connected"
            elif con.execute(
                "SELECT 1 FROM contact_requests "
                "WHERE requester_id = ? AND target_id = ?",
                (viewer["user_id"], target["user_id"]),
            ).fetchone():
                relationship = "request_sent"
            elif con.execute(
                "SELECT 1 FROM contact_requests "
                "WHERE requester_id = ? AND target_id = ?",
                (target["user_id"], viewer["user_id"]),
            ).fetchone():
                relationship = "request_received"
            else:
                relationship = "none"

        return {
            "real_name": target["real_name"],
            "account_number": target["account_number"],
            "verified": roster_verified(
                target["account_number"], target["real_name"]
            ),
            "relationship": relationship,
            "can_verify": bool(
                viewer
                and viewer["account_number"] == VERIFIER_ACCOUNT_NUMBER
                and viewer["verified"]
                and not roster_verified(
                    target["account_number"], target["real_name"]
                )
            ),
        }
    finally:
        con.close()


# These helpers protect contact and verification actions from signed-out or cross-site requests.
def require_same_origin(request):
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    parsed_origin = urlsplit(origin)
    if not origin or not host or parsed_origin.netloc.casefold() != host.casefold():
        raise HTTPException(status_code=403, detail="This verification request was rejected.")
    hostname = (parsed_origin.hostname or "").casefold()
    local_http = parsed_origin.scheme == "http" and hostname in {
        "localhost", "127.0.0.1", "::1",
    }
    if parsed_origin.scheme != "https" and not local_http:
        raise HTTPException(status_code=403, detail="Verification requires a secure page.")


def require_verifier(con, request):
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
    if not profile:
        raise HTTPException(status_code=401, detail="Sign in with the verified account first.")
    if (
        profile["account_number"] != VERIFIER_ACCOUNT_NUMBER
        or not profile["verified"]
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the verified Mykai Wade account (#5) can approve members.",
        )
    return profile


def contact_card(con, user_id):
    row = con.execute(
        "SELECT user_id, real_name, account_number, public_id "
        "FROM profiles WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return {
        "public_id": row["public_id"],
        "real_name": row["real_name"],
        "account_number": row["account_number"],
        "verified": roster_verified(row["account_number"], row["real_name"]),
    }


# The Profile page uses these routes to list contacts and manage contact requests.
@app.get("/api/contacts")
def list_contacts(request: Request):
    con = db()
    try:
        profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not profile:
            raise HTTPException(status_code=401, detail="Sign in to view your contacts.")
        contact_ids = con.execute(
            "SELECT contact_user_id FROM contacts WHERE user_id = ? "
            "ORDER BY created DESC",
            (profile["user_id"],),
        ).fetchall()
        incoming = con.execute(
            "SELECT id, requester_id, created FROM contact_requests "
            "WHERE target_id = ? ORDER BY created",
            (profile["user_id"],),
        ).fetchall()
        outgoing = con.execute(
            "SELECT target_id, created FROM contact_requests "
            "WHERE requester_id = ? ORDER BY created",
            (profile["user_id"],),
        ).fetchall()
        return {
            "contacts": [contact_card(con, row["contact_user_id"]) for row in contact_ids],
            "incoming": [
                {
                    "id": row["id"],
                    **contact_card(con, row["requester_id"]),
                }
                for row in incoming
            ],
            "outgoing": [
                contact_card(con, row["target_id"]) for row in outgoing
            ],
        }
    finally:
        con.close()


@app.post("/api/contacts/requests")
def create_contact_request(payload: ContactRequest, request: Request):
    require_same_origin(request)
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        requester = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not requester:
            raise HTTPException(status_code=401, detail="Sign in to add a contact.")
        target = con.execute(
            "SELECT user_id FROM profiles WHERE public_id = ?",
            (payload.public_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="This profile was not found.")
        if requester["user_id"] == target["user_id"]:
            raise HTTPException(status_code=400, detail="You cannot add your own account.")
        if con.execute(
            "SELECT 1 FROM contacts WHERE user_id = ? AND contact_user_id = ?",
            (requester["user_id"], target["user_id"]),
        ).fetchone():
            raise HTTPException(status_code=409, detail="You are already contacts.")
        if con.execute(
            "SELECT 1 FROM contact_requests WHERE requester_id = ? AND target_id = ?",
            (requester["user_id"], target["user_id"]),
        ).fetchone():
            raise HTTPException(status_code=409, detail="A contact request is already pending.")
        if con.execute(
            "SELECT 1 FROM contact_requests WHERE requester_id = ? AND target_id = ?",
            (target["user_id"], requester["user_id"]),
        ).fetchone():
            raise HTTPException(
                status_code=409,
                detail="This person already requested to add you. Review it in your profile.",
            )
        con.execute(
            "INSERT INTO contact_requests (requester_id, target_id, created) "
            "VALUES (?, ?, ?)",
            (requester["user_id"], target["user_id"], time.time()),
        )
        con.commit()
        return {"message": "Contact request sent."}
    finally:
        con.close()


# Scanning a profile QR creates a mutual contact; this action does not verify either account.
@app.post("/api/contacts")
def add_contact(payload: ContactRequest, request: Request):
    require_same_origin(request)
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        requester = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not requester:
            raise HTTPException(status_code=401, detail="Sign in to add a contact.")
        target = con.execute(
            "SELECT user_id FROM profiles WHERE public_id = ?",
            (payload.public_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="This profile was not found.")
        if requester["user_id"] == target["user_id"]:
            raise HTTPException(status_code=400, detail="You cannot add your own account.")

        existing = con.execute(
            "SELECT 1 FROM contacts WHERE user_id = ? AND contact_user_id = ?",
            (requester["user_id"], target["user_id"]),
        ).fetchone()
        if existing:
            con.commit()
            return {"message": "You are already contacts.", "connected": True}

        created = time.time()
        con.execute(
            "INSERT OR IGNORE INTO contacts (user_id, contact_user_id, created) "
            "VALUES (?, ?, ?)",
            (requester["user_id"], target["user_id"], created),
        )
        con.execute(
            "INSERT OR IGNORE INTO contacts (user_id, contact_user_id, created) "
            "VALUES (?, ?, ?)",
            (target["user_id"], requester["user_id"], created),
        )
        con.execute(
            "DELETE FROM contact_requests WHERE "
            "(requester_id = ? AND target_id = ?) OR "
            "(requester_id = ? AND target_id = ?)",
            (
                requester["user_id"],
                target["user_id"],
                target["user_id"],
                requester["user_id"],
            ),
        )
        con.commit()
        return {"message": "You have been added to each other's contacts.", "connected": True}
    finally:
        con.close()


# Only verified account #5 can approve a member from their public profile.
@app.post("/api/verification/approve-profile")
def approve_profile_verification(payload: ContactRequest, request: Request):
    require_same_origin(request)
    roster_changed = False
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        headers, entries = read_roster(VERIFIED_FILE)
        original_headers = list(headers)
        original_entries = dict(entries)
        require_verifier(con, request)
        target = con.execute(
            "SELECT user_id, real_name, account_number FROM profiles "
            "WHERE public_id = ?",
            (payload.public_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="This profile was not found.")
        number = target["account_number"]
        entry = entries.get(number)
        if not entry or entry.name.casefold() != target["real_name"].casefold():
            raise HTTPException(
                status_code=409,
                detail="The member roster no longer matches this account.",
            )
        if not entry.verified:
            entries[number] = RosterEntry(number, entry.name, True)
            write_roster(VERIFIED_FILE, headers, entries)
            roster_changed = True
            con.execute(
                "UPDATE profiles SET verified = 1 WHERE user_id = ?",
                (target["user_id"],),
            )
        con.execute(
            "UPDATE verification_requests SET used_at = ? "
            "WHERE user_id = ? AND used_at IS NULL",
            (time.time(), target["user_id"]),
        )
        con.commit()
        return {
            "real_name": target["real_name"],
            "account_number": number,
            "verified": True,
            "message": f"{target['real_name']} {number} is now verified.",
        }
    except (OSError, sqlite3.Error):
        con.rollback()
        if roster_changed:
            write_roster(VERIFIED_FILE, original_headers, original_entries)
        raise
    finally:
        con.close()


@app.post("/api/contacts/requests/{request_id}/accept")
def accept_contact_request(request_id: int, request: Request):
    require_same_origin(request)
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not profile:
            raise HTTPException(status_code=401, detail="Sign in to accept a request.")
        contact_request = con.execute(
            "SELECT requester_id FROM contact_requests WHERE id = ? AND target_id = ?",
            (request_id, profile["user_id"]),
        ).fetchone()
        if not contact_request:
            raise HTTPException(status_code=404, detail="This contact request was not found.")
        created = time.time()
        con.execute(
            "INSERT INTO contacts (user_id, contact_user_id, created) VALUES (?, ?, ?)",
            (profile["user_id"], contact_request["requester_id"], created),
        )
        con.execute(
            "INSERT INTO contacts (user_id, contact_user_id, created) VALUES (?, ?, ?)",
            (contact_request["requester_id"], profile["user_id"], created),
        )
        con.execute("DELETE FROM contact_requests WHERE id = ?", (request_id,))
        con.commit()
        return {"message": "Contact request accepted."}
    finally:
        con.close()


@app.post("/api/contacts/requests/{request_id}/decline")
def decline_contact_request(request_id: int, request: Request):
    require_same_origin(request)
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not profile:
            raise HTTPException(status_code=401, detail="Sign in to manage contact requests.")
        result = con.execute(
            "DELETE FROM contact_requests WHERE id = ? AND target_id = ?",
            (request_id, profile["user_id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="This contact request was not found.")
        con.commit()
        return {"message": "Contact request declined."}
    finally:
        con.close()


@app.get("/api/profile/qr")
def get_profile_qr(request: Request):
    con = db()
    try:
        profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not profile:
            raise HTTPException(status_code=401, detail="Sign in to view your profile QR.")
        base_url = os.environ.get("PUBLIC_BASE_URL", "https://mykaianswer.com").strip()
        parsed = urlsplit(base_url)
        hostname = (parsed.hostname or "").casefold()
        local_http = parsed.scheme == "http" and hostname in {
            "localhost", "127.0.0.1", "::1",
        }
        if not parsed.netloc or (parsed.scheme != "https" and not local_http):
            raise HTTPException(
                status_code=500,
                detail="Set PUBLIC_BASE_URL to the HTTPS website address.",
            )
        link = (
            base_url.rstrip("/")
            + "/profile.html?scan="
            + profile["public_id"]
        )
        return Response(
            content=qr_code_png(link),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    finally:
        con.close()


@app.post("/api/verification/request")
def verification_request_info(payload: VerificationToken, request: Request):
    require_same_origin(request)
    con = db()
    try:
        require_verifier(con, request)
        row = con.execute(
            "SELECT profiles.real_name, profiles.account_number "
            "FROM verification_requests "
            "JOIN profiles ON profiles.user_id = verification_requests.user_id "
            "WHERE verification_requests.token_hash = ? "
            "AND verification_requests.used_at IS NULL "
            "AND verification_requests.expires > ?",
            (hash_verification_token(payload.token), time.time()),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="This QR code is expired, invalid, or already used.",
            )
        return {
            "real_name": row["real_name"],
            "account_number": row["account_number"],
        }
    finally:
        con.close()


@app.post("/api/verification/approve")
def approve_verification(payload: VerificationToken, request: Request):
    require_same_origin(request)
    roster_changed = False
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        headers, entries = read_roster(VERIFIED_FILE)
        original_headers = list(headers)
        original_entries = dict(entries)
        require_verifier(con, request)
        row = con.execute(
            "SELECT verification_requests.user_id, profiles.real_name, "
            "profiles.account_number "
            "FROM verification_requests "
            "JOIN profiles ON profiles.user_id = verification_requests.user_id "
            "WHERE verification_requests.token_hash = ? "
            "AND verification_requests.used_at IS NULL "
            "AND verification_requests.expires > ?",
            (hash_verification_token(payload.token), time.time()),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="This QR code is expired, invalid, or already used.",
            )

        number = row["account_number"]
        entry = entries.get(number)
        if not entry or entry.name.casefold() != row["real_name"].casefold():
            raise HTTPException(
                status_code=409,
                detail="The member roster no longer matches this account.",
            )
        if not entry.verified:
            entries[number] = RosterEntry(number, entry.name, True)
            write_roster(VERIFIED_FILE, headers, entries)
            roster_changed = True
            con.execute(
                "UPDATE profiles SET verified = 1 WHERE user_id = ?",
                (row["user_id"],),
            )

        con.execute(
            "UPDATE verification_requests SET used_at = ? WHERE token_hash = ?",
            (time.time(), hash_verification_token(payload.token)),
        )
        con.commit()
        return {
            "real_name": row["real_name"],
            "account_number": number,
            "verified": True,
        }
    except (OSError, sqlite3.Error):
        con.rollback()
        if roster_changed:
            write_roster(VERIFIED_FILE, original_headers, original_entries)
        raise
    finally:
        con.close()


@app.post("/api/verification/resend")
def resend_verification(request: Request):
    require_same_origin(request)
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
        if not profile:
            raise HTTPException(status_code=401, detail="Sign in to request a QR code.")
        if profile["verified"]:
            raise HTTPException(status_code=409, detail="This account is already verified.")
        account = con.execute(
            "SELECT email FROM profiles WHERE user_id = ?", (profile["user_id"],)
        ).fetchone()
        if not account or not account["email"]:
            raise HTTPException(status_code=400, detail="This account has no email address.")
        latest = con.execute(
            "SELECT MAX(created) FROM verification_requests WHERE user_id = ?",
            (profile["user_id"],),
        ).fetchone()[0]
        if latest and time.time() - latest < 60:
            raise HTTPException(
                status_code=429,
                detail="Wait one minute before requesting another verification QR code.",
            )
        record_verification_email_event(con, request)

        token = new_verification_token()
        con.execute(
            "DELETE FROM verification_requests WHERE user_id = ? AND used_at IS NULL",
            (profile["user_id"],),
        )
        con.execute(
            "INSERT INTO verification_requests "
            "(token_hash, user_id, created, expires, used_at) VALUES (?, ?, ?, ?, NULL)",
            (
                hash_verification_token(token),
                profile["user_id"],
                time.time(),
                time.time() + VERIFICATION_REQUEST_LIFETIME,
            ),
        )
        link = verification_url(
            os.environ.get("PUBLIC_BASE_URL", "https://mykaianswer.com").strip(),
            token,
        )
        send_verification_email(
            account["email"], profile["real_name"], profile["account_number"], link
        )
        con.commit()
        return {
            "message": "A new verification QR code was sent to your email and is shown below.",
            "qr_code": base64.b64encode(qr_code_png(link)).decode("ascii"),
        }
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as error:
        con.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Could not send a verification email: {error}",
        ) from error
    finally:
        con.close()


@app.post("/api/auth/logout")
def logout_account(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    con = db()
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        con.commit()
    con.close()
    response = JSONResponse({"message": "Signed out."})
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax", path="/")
    return response


# =====================================================================
# MATCHING: how the server decides two questions are "similar"
# =====================================================================

# Everyday words that say nothing about the topic. They are ignored when comparing.
# CHANGE: add words that show up in every question on your site (inside the quotes, separated by spaces).
STOP_WORDS = set(
    "a an the and or but is are was were be to of in on for with at by from it "
    "this that i my me we you your how what why when do does can should would about".split()
)


def keywords(text):
    # Turns a sentence into a set of important lowercase words.
    # Example: "How do I fix Python?" -> {"fix", "python"}
    found = re.findall(r"[a-z0-9]+", text.lower())   # Lowercase everything, then pull out each word.
    # Keep a word only if it isn't a stop word AND it has more than 2 letters.
    # CHANGE: replace "> 2" with "> 3" to ignore short words like "car" and "run" too.
    return {w for w in found if w not in STOP_WORDS and len(w) > 2}


def similarity(a, b):
    # Gives a score from 0 (nothing in common) to 1 (identical word lists).
    # Formula: words both questions share, divided by all different words between them.
    if not a or not b:    # If either side has no keywords, there's nothing to compare.
        return 0
    return len(a & b) / len(a | b)   # "&" = shared words, "|" = all words combined.


# =====================================================================
# QUESTIONS: saving and matching
# =====================================================================

class NewQuestion(BaseModel):
    # The profile ID comes from the signed-in session cookie, not from the browser's request body.
    question: str           # Required.
    description: str = ""   # Optional. The "= ''" means it can be left out.
    tags: list[str] = Field(default_factory=list)  # Selected major and minor badges.


class NewPublicRoom(BaseModel):  # Validates the question submitted to create a public room.
    question: str  # Holds the required room topic supplied by the browser.
    description: str = ""  # Holds optional context that is public with the question.
    tags: list[str] = Field(default_factory=list)  # Holds the selected major and minor badges.


@app.get("/api/questions/me")
def my_questions(request: Request):
    con = db()
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
    if not profile:
        con.close()
        raise HTTPException(status_code=401, detail="Sign in to view your questions.")

    rows = con.execute(
        "SELECT id, question, description, created, tags FROM questions "
        "WHERE user_id = ? ORDER BY id DESC",
        (profile["user_id"],),
    ).fetchall()
    con.close()
    return {
        "questions": [
            {
                "id": row["id"],
                "question": row["question"],
                "description": row["description"],
                "created": row["created"],
                "tags": json.loads(row["tags"] or "[]"),
            }
            for row in rows
        ]
    }


@app.post("/api/questions")   # This is the address ask.html sends the form to.
def add_question(q: NewQuestion, request: Request):
    # Clean up the text: strip() removes extra spaces, [:200] cuts it to the size limit.
    question = q.question.strip()[:MAX_QUESTION]
    description = q.description.strip()[:MAX_DESCRIPTION]
    tags = list(dict.fromkeys(
        tag.strip().upper()[:64] for tag in q.tags[:20] if tag.strip()
    ))

    con = db()
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
    if not profile:
        con.close()
        raise HTTPException(status_code=401, detail="Sign in before posting a question.")
    if not question:
        con.close()
        raise HTTPException(status_code=400, detail="A question is required.")
    user_id = profile["user_id"]

    # Save the new question into the database. The "?" marks are filled in safely by the values after them.
    cur = con.execute(
        "INSERT INTO questions (user_id, question, description, created, tags) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, question, description, time.time(), json.dumps(tags)),
    )
    new_id = cur.lastrowid   # The number the database just gave this question.

    # Turn the new question + description into keywords once, to compare against others.
    mine = keywords(question + " " + description)

    # Get other people's questions and their public profile names, newest first.
    # CHANGE: "LIMIT 500" = only compare against the 500 newest. Raise it for more matches (slower).
    others = con.execute(
        "SELECT questions.id, questions.question, questions.description, questions.tags, "
        "profiles.real_name, profiles.account_number FROM questions "
        "LEFT JOIN profiles ON profiles.user_id = questions.user_id "
        "WHERE questions.user_id != ? ORDER BY questions.id DESC LIMIT 500",
        (user_id,),
    ).fetchall()

    # Only compare questions with at least one shared major or minor badge.
    matches = []
    for row in others:
        shared_tags = sorted(set(tags) & set(json.loads(row["tags"] or "[]")))
        if not shared_tags:
            continue
        score = similarity(mine, keywords(row["question"] + " " + row["description"]))
        # Keep it only if at least one keyword is shared.
        # CHANGE: use "score >= 0.2" to require a stronger match (fewer, better results).
        if score > 0:
            matches.append({
                "id": row["id"],
                "question": row["question"],
                "description": row["description"],
                "score": round(score, 2),   # Rounded to 2 decimals, like 0.33.
                "shared_tags": shared_tags,
                "real_name": row["real_name"] or "Unknown member",
                "account_number": row["account_number"],
                "verified": roster_verified(
                    row["account_number"], row["real_name"] or ""
                ),
            })

    # Sort best match first.
    matches.sort(key=lambda m: m["score"], reverse=True)

    con.commit()
    con.close()

    # Send back this question's id and the top matches.
    # CHANGE: "[:5]" = show at most 5 matches. Use [:10] for 10.
    return {"id": new_id, "matches": matches[:5]}


@app.post("/api/public-rooms")  # Exposes the authenticated endpoint for creating public rooms.
def create_public_room(room: NewPublicRoom, request: Request):
    question = room.question.strip()[:MAX_QUESTION]  # Trims the topic and enforces the question length limit.
    description = room.description.strip()[:MAX_DESCRIPTION]  # Applies the shared public-description limit.
    tags = list(dict.fromkeys(tag.strip().upper()[:64] for tag in room.tags[:20] if tag.strip()))  # Normalizes unique badge names.
    if not question:
        raise HTTPException(status_code=400, detail="A room question is required.")  # Rejects blank topics.

    con = db()  # Opens the database connection used to save the topic.
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))  # Identifies the signed-in room creator.
    if not profile:
        con.close()  # Releases the database connection before returning an authentication error.
        raise HTTPException(status_code=401, detail="Sign in before creating a room.")  # Requires a signed-in creator.
    cur = con.execute(  # Stores the topic as a question so it has a stable database ID.
        "INSERT INTO questions (user_id, question, description, created, tags) "
        "VALUES (?, ?, ?, ?, ?)",
        (profile["user_id"], question, description, time.time(), json.dumps(tags)),
    )
    question_id = cur.lastrowid  # Uses the saved question ID as the room identifier.
    con.commit()  # Persists the newly created public room topic.
    con.close()  # Closes the database connection after saving.
    return {"id": question_id, "room": f"question-{question_id}", "question": question}  # Returns the shareable room link data.


@app.get("/api/public-rooms")  # Exposes the public list and activity counts used by Ask Mykai.
async def public_rooms():
    con = db()  # Opens the database to read all room topics and saved message totals.
    rows = con.execute(  # Joins room topics to saved messages so quiet rooms remain visible too.
        "SELECT questions.id, questions.question, questions.description, questions.tags, questions.created, "
        "COUNT(messages.id) AS message_count "
        "FROM questions LEFT JOIN messages "
        "ON messages.room = 'question-' || questions.id "
        "GROUP BY questions.id ORDER BY questions.id DESC"
    ).fetchall()
    con.close()  # Closes the database before calculating the in-memory presence counts.

    rooms = []  # Collects the public room details returned to the browser.
    for row in rows:
        room = f"question-{row['id']}"  # Builds the stable URL room key from the question ID.
        members = open_chat_members.get(room, {})  # Reads connected visitor IDs for this room.
        rooms.append({  # Adds topic, saved-message, and live-presence data for this room.
            "id": row["id"],  # Includes the source question ID.
            "room": room,  # Includes the key used by the chat page.
            "question": row["question"],  # Includes the room's displayed topic.
            "description": row["description"] or "",  # Makes the question description public in the chat directory.
            "tags": json.loads(row["tags"] or "[]"),  # Groups public questions by every badge they use.
            "created": row["created"],  # Provides a recency tie-breaker for room rankings.
            "message_count": row["message_count"],  # Reports the total number of saved messages.
            "active_people": len(set(members.values())),  # Counts unique connected profiles and guests.
        })
    return rooms  # Sends all public room summaries to the browser.


# =====================================================================
# CHAT ROOMS
# A room is named after the two question ids it connects, smaller number first (like "3-7").
# =====================================================================

def is_public_room(room):  # Identifies room keys that refer to a single public question topic.
    return re.fullmatch(r"question-\d+", room) is not None  # Accepts only the public-room key format.


def parse_room(room):
    # Checks a room name looks like "number-number" and returns the two numbers.
    # This blocks weird or malicious room names.
    if not re.fullmatch(r"\d+-\d+", room):
        raise HTTPException(status_code=400, detail="Bad room name.")
    a, b = room.split("-")
    return int(a), int(b)


@app.get("/api/room/{room}")   # chat.html asks this to show what the chat is about.
def room_info(room: str):
    if is_public_room(room):  # Loads the single topic when this is a public question room.
        question_id = int(room.split("-", 1)[1])  # Extracts the topic ID from the public room key.
        con = db()  # Opens the database to retrieve the room topic.
        question = con.execute(  # Finds the topic associated with this public room.
            "SELECT question FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        con.close()  # Releases the database connection after the lookup.
        if not question:
            raise HTTPException(status_code=404, detail="This public room was not found.")  # Rejects nonexistent rooms.
        return {"questions": [question["question"]], "public": True}  # Returns the topic and public-room marker.

    a, b = parse_room(room)
    con = db()
    # Look up both questions by id and return their text.
    rows = con.execute(
        "SELECT question FROM questions WHERE id IN (?, ?) ORDER BY id", (a, b)
    ).fetchall()
    con.close()
    return {"questions": [r["question"] for r in rows]}


@app.get("/api/inbox")   # ask.html asks this on load: "did anyone reply to me?"
def inbox(request: Request):
    con = db()
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
    if not profile:
        con.close()
        raise HTTPException(status_code=401, detail="Sign in to view your replies.")
    user_id = profile["user_id"]

    # Collect the ids of every question this browser asked.
    my_ids = {r["id"] for r in con.execute(
        "SELECT id FROM questions WHERE user_id = ?", (user_id,))}

    waiting = []
    # Look at every room that has messages.
    for r in con.execute("SELECT DISTINCT room FROM messages").fetchall():
        if is_public_room(r["room"]):
            continue  # Keeps public-room messages out of the private question-reply inbox.
        a, b = parse_room(r["room"])
        # Only care about rooms that include one of my questions.
        if a in my_ids or b in my_ids:
            # Find the most recent message in that room.
            last = con.execute(
                "SELECT user_id, text FROM messages WHERE room = ? ORDER BY id DESC LIMIT 1",
                (r["room"],),
            ).fetchone()
            # If the other person wrote last, I have a reply waiting.
            if last["user_id"] != user_id:
                waiting.append({"room": r["room"], "text": last["text"]})
    con.close()
    return waiting


@app.get("/api/chats/me")
def user_chats(request: Request):
    # Only return rooms connected to questions asked by this profile.
    con = db()
    profile = private_profile(con, request.cookies.get(SESSION_COOKIE))
    if not profile:
        con.close()
        raise HTTPException(status_code=401, detail="Sign in to see your chat rooms.")
    user_id = profile["user_id"]

    my_questions = {
        row["id"]: row["question"]
        for row in con.execute(
            "SELECT id, question FROM questions WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    rooms = []
    # A room is listed after its first saved message; unopened matches are not chat rooms yet.
    for row in con.execute("SELECT DISTINCT room FROM messages").fetchall():
        if is_public_room(row["room"]):
            continue  # Keeps public discussions out of the personal pair-chat list.
        first_id, second_id = parse_room(row["room"])
        my_question_id = None
        if first_id in my_questions:
            my_question_id = first_id
        elif second_id in my_questions:
            my_question_id = second_id
        if my_question_id is None:
            continue

        question_rows = con.execute(
            "SELECT id, question FROM questions WHERE id IN (?, ?) ORDER BY id",
            (first_id, second_id),
        ).fetchall()
        last = con.execute(
            "SELECT messages.user_id, messages.text, messages.created, profiles.real_name "
            "FROM messages LEFT JOIN profiles ON profiles.user_id = messages.user_id "
            "WHERE messages.room = ? ORDER BY messages.id DESC LIMIT 1",
            (row["room"],),
        ).fetchone()
        rooms.append({
            "room": row["room"],
            "questions": [question["question"] for question in question_rows],
            "my_question": my_questions[my_question_id],
            "last_message": last["text"],
            "last_sender": last["real_name"] or "Unknown member",
            "last_message_from_me": last["user_id"] == user_id,
            "updated": last["created"],
        })

    con.close()
    # Show the most recently active rooms at the top.
    rooms.sort(key=lambda chat: chat["updated"], reverse=True)
    return rooms


# Keeps track of open chat windows and active call participants, grouped by room.
# It lives in memory only, so it resets when the server restarts (saved messages stay in the database).
open_chats = {}
open_chat_members = {}  # Tracks each connected visitor by public room for live active counts.
active_calls = {}
MAX_CALL_PARTICIPANTS = 20


@app.websocket("/ws/{room}")   # A WebSocket is a connection that stays open so messages arrive instantly.
async def chat(ws: WebSocket, room: str):
    # Reject bad room names right away.
    if is_public_room(room):  # Validates that public rooms point to an existing question.
        con = db()  # Opens the database to verify the public room topic.
        question_id = int(room.split("-", 1)[1])  # Extracts the question ID from the room key.
        exists = con.execute(  # Checks whether the referenced room topic exists.
            "SELECT 1 FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        con.close()  # Closes the database after validating the topic.
        if not exists:
            await ws.close()  # Refuses a WebSocket request for a nonexistent room.
            return  # Stops processing the invalid room connection.
    else:
        try:
            parse_room(room)
        except HTTPException:
            await ws.close()
            return

    # Browsers attach session cookies to WebSockets, so block cross-site connection attempts.
    request_scheme = "https" if ws.url.scheme in ("https", "wss") else "http"
    expected_origin = f"{request_scheme}://{ws.headers.get('host', '')}"
    origin = ws.headers.get("origin")
    if origin and origin != expected_origin:
        await ws.close(code=1008)
        return

    await ws.accept()                              # Accept the visitor's connection.
    open_chats.setdefault(room, set()).add(ws)     # Add them to the list for this room.
    session_token = ws.cookies.get(SESSION_COOKIE)
    con = db()
    profile = private_profile(con, session_token)
    con.close()
    user_id = profile["user_id"] if profile else ""
    if profile:
        await ws.send_json({
            "type": "auth",
            "real_name": profile["real_name"],
            "account_number": profile["account_number"],
            "verified": bool(profile["verified"]),
        })

    # Send the last 50 saved messages so a new window isn't empty.
    # CHANGE: "LIMIT 50" = how much history to show.
    con = db()
    history = con.execute(
        "SELECT messages.user_id, messages.text, profiles.real_name, "
        "profiles.account_number "
        "FROM messages LEFT JOIN profiles ON profiles.user_id = messages.user_id "
        "WHERE messages.room = ? ORDER BY messages.id DESC LIMIT 50",
        (room,),
    ).fetchall()
    con.close()
    for m in reversed(history):   # reversed() puts the oldest first, newest last.
        await ws.send_json({
            "user_id": m["user_id"],
            "text": m["text"],
            "real_name": m["real_name"] or "Unknown member",
            "account_number": m["account_number"],
            "verified": roster_verified(
                m["account_number"], m["real_name"] or ""
            ),
        })

    open_chat_members.setdefault(room, {})[ws] = (  # Adds this connection to live room presence counts.
        user_id or "guest:" + secrets.token_urlsafe(12)
    )
    try:
        while True:   # Keep listening for new messages until the visitor leaves.
            data = await ws.receive_json()
            # Check logout/expiration between messages so an open chat cannot reuse an old sign-in.
            con = db()
            profile = private_profile(con, session_token)
            con.close()
            user_id = profile["user_id"] if profile else ""

            if data.get("type") == "call-leave":
                participants = active_calls.get(room, {})
                participant = participants.pop(ws, None)
                if participant:
                    for client in list(participants):
                        await client.send_json({
                            "type": "call-peer-left",
                            "participant_id": participant["id"],
                        })
                    if not participants and active_calls.get(room) is participants:
                        active_calls.pop(room, None)
                continue

            if data.get("type") == "call-join":
                if not user_id:
                    await ws.send_json({"type": "error", "message": "Create a profile before starting a call."})
                    continue
                participants = active_calls.setdefault(room, {})
                if ws in participants:
                    continue
                if len(participants) >= MAX_CALL_PARTICIPANTS:
                    if not participants:
                        active_calls.pop(room, None)
                    await ws.send_json({
                        "type": "error",
                        "message": "This prototype supports up to twenty people in a call.",
                    })
                    continue

                participant = {
                    "id": secrets.token_urlsafe(12),
                    "user_id": user_id,
                    "real_name": profile["real_name"],
                }
                existing = list(participants.values())
                participants[ws] = participant
                await ws.send_json({
                    "type": "call-joined",
                    "participant_id": participant["id"],
                    "peers": existing,
                })
                packet = {
                    "type": "call-peer-joined",
                    "participant": participant,
                }
                for client in list(participants):
                    if client is not ws:
                        await client.send_json(packet)
                continue

            if data.get("type") == "call-signal":
                if not user_id:
                    await ws.send_json({"type": "error", "message": "Sign in again before continuing the call."})
                    continue
                sender = active_calls.get(room, {}).get(ws)
                target_id = data.get("target")
                signal = data.get("signal")
                if not sender or not isinstance(target_id, str) or not isinstance(signal, dict):
                    continue
                if signal.get("type") not in {"description", "candidate"}:
                    continue
                target = next(
                    (
                        client for client, peer in active_calls.get(room, {}).items()
                        if peer["id"] == target_id
                    ),
                    None,
                )
                if target:
                    await target.send_json({
                        "type": "call-signal",
                        "participant_id": sender["id"],
                        "signal": signal,
                    })
                continue

            # Clean the message the same way as questions.
            text = str(data.get("text", "")).strip()[:MAX_MESSAGE]
            if not text:   # Ignore empty messages.
                continue
            if not user_id:
                await ws.send_json({"type": "error", "message": "Create a profile before sending a message."})
                continue

            # Save the message permanently.
            con = db()
            con.execute(
                "INSERT INTO messages (room, user_id, text, created) VALUES (?, ?, ?, ?)",
                (room, user_id, text, time.time()),
            )
            con.commit()
            con.close()

            # Deliver it to everyone in the room, including the sender (so it shows on their screen too).
            for client in list(open_chats[room]):
                await client.send_json({
                    "user_id": user_id,
                    "text": text,
                    "real_name": profile["real_name"],
                    "account_number": profile["account_number"],
                    "verified": bool(profile["verified"]),
                })
    except WebSocketDisconnect:
        # The visitor closed the page: remove them from the room.
        open_chats[room].discard(ws)
        members = open_chat_members.get(room, {})  # Looks up the presence map for the disconnected room.
        members.pop(ws, None)  # Removes this visitor so the active count stays accurate.
        if not members:  # Drops the room entry after its last connected visitor leaves.
            open_chat_members.pop(room, None)  # Removes empty maps to avoid retaining unused room state.
        participants = active_calls.get(room, {})
        participant = participants.pop(ws, None)
        if participant:
            for client in list(participants):
                await client.send_json({
                    "type": "call-peer-left",
                    "participant_id": participant["id"],
                })
            if not participants and active_calls.get(room) is participants:
                active_calls.pop(room, None)


# =====================================================================
# PAGES: sending your HTML files to the browser
# =====================================================================

@app.get("/")   # Visiting just http://yourserver:8000 shows index.html.
def home():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.get("/{page}.html")   # Visiting /ask.html, /chat.html, etc.
def page(page: str):
    path = os.path.join(HERE, page + ".html")
    # Only allow pages on the PAGES list above, and only if the file really exists.
    if page not in PAGES or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Page not found.")
    return FileResponse(path)


# Serve the stylesheet before uvicorn starts, including when the app is imported.
@app.get("/styles.css")
def styles():
    return FileResponse(os.path.join(HERE, "styles.css"), media_type="text/css")

# Extra files the browser may download besides pages. Like PAGES, this is a safety list.
# CHANGE: add each browser asset here; rooms.js supplies public-room listing and creation behavior.
PUBLIC_FILES = {
    "badges.txt", "badge-picker.js", "badges.js", "ask.js", "profile.js",
    "profile-view.js", "chat.js", "rooms.js", "verification-ui.js", "profile-page.js",
    "qr-scanner.umd.min.js", "qr-scanner-worker.min.js",
}  # Allows pages to load their public scripts.

@app.get("/{name}")   # Matches approved browser assets like /badges.js and /profile.js.
def public_file(name: str):
    path = os.path.join(HERE, name)
    # Anything not on the list (server.py, chat.db) gets a 404, so nobody can download them.
    if name not in PUBLIC_FILES or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)   # Sends the file; the browser works out the type from the ending.
   
# This block only runs when you type "python server.py" (not when another file imports this one).
if __name__ == "__main__":
  
    # host="127.0.0.1" = allow only this computer to connect.
    # Do not use "0.0.0.0" for password accounts unless HTTPS is configured.
    # port=8000 = the "door number" in the address (http://IP:8000).
    #   CHANGE: use another number like 8080 if 8000 is already taken.
    uvicorn.run(app, host="127.0.0.1", port=8000)
