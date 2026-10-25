# =====================================================================
# server.py - the "brain" of the site.
# It does three jobs:
#   1. Saves the questions people submit.
#   2. Finds other people's similar questions that share badges.
#   3. Runs live chat rooms and saves the messages.
# Run it with:  python server.py
# Stop it with: Ctrl+C
# =====================================================================

# --- Imports: tools this file borrows. You only add one if you use a new tool. ---
import os        # Works with file paths and folders.
import hashlib   # Hashes passwords and session tokens before saving them.
import hmac      # Compares password hashes without timing leaks.
import json      # Stores each question's selected badges in the database.
import re        # "Regular expressions": finds patterns in text (used to split text into words).
import secrets   # Creates unpredictable profile IDs.
import sqlite3   # The database. It stores everything in one file (chat.db).
import time      # Gives the current time, so each message gets a timestamp.
from typing import Optional

import uvicorn   # The program that actually runs the web server.
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect  # The web framework: routes, errors, live chat.
from fastapi.responses import FileResponse, JSONResponse  # Sends pages and API responses.
from pydantic import BaseModel, Field        # Describes what data a form submission must contain.

# Creates the web app. Every "@app..." line below attaches a feature to it.
app = FastAPI()

# The folder this file is in. Pages and the database are found relative to it.
# CHANGE: normally leave this alone.
HERE = os.path.dirname(os.path.abspath(__file__))

# Where the database lives. It is created automatically the first time you run the server.
# CHANGE: rename "chat.db" if you want. If you delete the file, ALL questions and messages are erased.
DB_FILE = os.path.join(HERE, "chat.db")

# The only pages visitors are allowed to open. This is a safety list: it stops people from
# downloading server.py or chat.db through the browser.
# CHANGE: when you create a new page (like faq.html), add its name here without ".html": "faq".
PAGES = {"index", "ask", "chat", "about", "ask-mykai"}

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

    # Profile names are public claims; verification remains off until a real process exists.
    con.execute(
        "CREATE TABLE IF NOT EXISTS profiles ("
        "user_id TEXT PRIMARY KEY, real_name TEXT NOT NULL, "
        "verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, "
        "email TEXT, password_hash TEXT)"
    )
    profile_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(profiles)").fetchall()
    }
    if "email" not in profile_columns:
        con.execute("ALTER TABLE profiles ADD COLUMN email TEXT")
    if "password_hash" not in profile_columns:
        con.execute("ALTER TABLE profiles ADD COLUMN password_hash TEXT")
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS profiles_email_unique "
        "ON profiles(email COLLATE NOCASE) WHERE email IS NOT NULL"
    )

    # Store only hashes of random session tokens, never the browser's cookie value.
    con.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL)"
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


# =====================================================================
# ACCOUNTS
# Names are public claims; email addresses are private sign-in details and aren't verified.
# =====================================================================

class RegisterAccount(BaseModel):
    real_name: str
    email: str
    password: str
    legacy_user_id: Optional[str] = None


class LoginAccount(BaseModel):
    email: str
    password: str


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
    return con.execute(
        "SELECT profiles.user_id, profiles.real_name, profiles.verified "
        "FROM sessions JOIN profiles ON profiles.user_id = sessions.user_id "
        "WHERE sessions.token_hash = ? AND sessions.expires > ?",
        (token_hash, time.time()),
    ).fetchone()


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


def finish_login(con, user_id, request, message):
    # Remove expired sessions and store only this browser's new token hash.
    con.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    con.execute(
        "INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
        (token_hash, user_id, time.time() + SESSION_DAYS * 24 * 60 * 60),
    )
    profile = con.execute(
        "SELECT user_id, real_name, verified FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    con.commit()
    response = JSONResponse({
        "message": message,
        "user_id": profile["user_id"],
        "real_name": profile["real_name"],
        "verified": bool(profile["verified"]),
    })
    set_session_cookie(response, token, request)
    return response


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

    con = db()
    try:
        con.execute("BEGIN")
        # Keep this browser's old questions/chats when it upgrades its old profile.
        legacy_id = (account.legacy_user_id or "")[:64]
        legacy = con.execute(
            "SELECT user_id FROM profiles WHERE user_id = ? AND email IS NULL "
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
                "(user_id, real_name, verified, created, email, password_hash) "
                "VALUES (?, ?, 0, ?, ?, ?)",
                (user_id, real_name, time.time(), email, password_hash(password)),
            )
        return finish_login(con, user_id, request, "Account created.")
    except sqlite3.IntegrityError:
        con.rollback()
        raise HTTPException(status_code=409, detail="That email already has an account.")
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
        "verified": bool(profile["verified"]),
    }


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
        "profiles.real_name, profiles.verified FROM questions "
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
                "verified": bool(row["verified"]),
            })

    # Sort best match first.
    matches.sort(key=lambda m: m["score"], reverse=True)

    con.commit()
    con.close()

    # Send back this question's id and the top matches.
    # CHANGE: "[:5]" = show at most 5 matches. Use [:10] for 10.
    return {"id": new_id, "matches": matches[:5]}


# =====================================================================
# CHAT ROOMS
# A room is named after the two question ids it connects, smaller number first (like "3-7").
# =====================================================================

def parse_room(room):
    # Checks a room name looks like "number-number" and returns the two numbers.
    # This blocks weird or malicious room names.
    if not re.fullmatch(r"\d+-\d+", room):
        raise HTTPException(status_code=400, detail="Bad room name.")
    a, b = room.split("-")
    return int(a), int(b)


@app.get("/api/room/{room}")   # chat.html asks this to show what the chat is about.
def room_info(room: str):
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
active_calls = {}
MAX_CALL_PARTICIPANTS = 20


@app.websocket("/ws/{room}")   # A WebSocket is a connection that stays open so messages arrive instantly.
async def chat(ws: WebSocket, room: str):
    # Reject bad room names right away.
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
            "verified": bool(profile["verified"]),
        })

    # Send the last 50 saved messages so a new window isn't empty.
    # CHANGE: "LIMIT 50" = how much history to show.
    con = db()
    history = con.execute(
        "SELECT messages.user_id, messages.text, profiles.real_name, profiles.verified "
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
            "verified": bool(m["verified"]),
        })

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
                    "verified": bool(profile["verified"]),
                })
    except WebSocketDisconnect:
        # The visitor closed the page: remove them from the room.
        open_chats[room].discard(ws)
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
    # Build the stylesheet path from the server folder so it works from any working directory.
    return FileResponse(os.path.join(HERE, "styles.css"), media_type="text/css")

# Extra files the browser may download besides pages. Like PAGES, this is a safety list.
# CHANGE: add a file name here whenever you make a new .js or .txt file the page needs.
PUBLIC_FILES = {"badges.txt", "badges.js", "ask.js", "profile.js", "chat.js"}

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
