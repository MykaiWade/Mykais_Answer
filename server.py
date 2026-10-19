# =====================================================================
# server.py - the "brain" of the site.
# It does three jobs:
#   1. Saves the questions people submit.
#   2. Finds other people's questions that are similar.
#   3. Runs live chat rooms and saves the messages.
# Run it with:  python server.py
# Stop it with: Ctrl+C
# =====================================================================

# --- Imports: tools this file borrows. You only add one if you use a new tool. ---
import os        # Works with file paths and folders.
import re        # "Regular expressions": finds patterns in text (used to split text into words).
import sqlite3   # The database. It stores everything in one file (chat.db).
import time      # Gives the current time, so each message gets a timestamp.

import uvicorn   # The program that actually runs the web server.
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # The web framework: routes, errors, live chat.
from fastapi.responses import FileResponse   # Lets the server send an HTML file to the browser.
from pydantic import BaseModel               # Describes what data a form submission must contain.

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
MAX_QUESTION = 200      # Most characters allowed in a question.
MAX_DESCRIPTION = 1000  # Most characters allowed in a description.
MAX_MESSAGE = 500       # Most characters allowed in one chat message.


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

    # Table 1: questions. Each row = one submitted question.
    # id = a number that goes up by 1 each time (1, 2, 3...). user_id = which browser asked it.
    # CHANGE: to store more things (like a category), add a column here. For an existing
    # chat.db you must delete the file once so the table is rebuilt with the new column.
    con.execute(
        "CREATE TABLE IF NOT EXISTS questions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, "
        "question TEXT, description TEXT, created REAL)"
    )

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
    # The shape of the data ask.html sends. If a field is missing, the server rejects the request.
    user_id: str            # The random ID of the browser that asked.
    question: str           # Required.
    description: str = ""   # Optional. The "= ''" means it can be left out.


@app.post("/api/questions")   # This is the address ask.html sends the form to.
def add_question(q: NewQuestion):
    # Clean up the text: strip() removes extra spaces, [:200] cuts it to the size limit.
    question = q.question.strip()[:MAX_QUESTION]
    description = q.description.strip()[:MAX_DESCRIPTION]
    user_id = q.user_id.strip()[:64]

    # Refuse empty questions. 400 = "the request was bad". The message shows up in the server log.
    if not question or not user_id:
        raise HTTPException(status_code=400, detail="A question is required.")

    con = db()

    # Save the new question into the database. The "?" marks are filled in safely by the values after them.
    cur = con.execute(
        "INSERT INTO questions (user_id, question, description, created) VALUES (?, ?, ?, ?)",
        (user_id, question, description, time.time()),
    )
    new_id = cur.lastrowid   # The number the database just gave this question.

    # Turn the new question + description into keywords once, to compare against others.
    mine = keywords(question + " " + description)

    # Get other people's questions (user_id != mine), newest first.
    # CHANGE: "LIMIT 500" = only compare against the 500 newest. Raise it for more matches (slower).
    others = con.execute(
        "SELECT id, question, description FROM questions "
        "WHERE user_id != ? ORDER BY id DESC LIMIT 500",
        (user_id,),
    ).fetchall()

    # Score every other question against this one.
    matches = []
    for row in others:
        score = similarity(mine, keywords(row["question"] + " " + row["description"]))
        # Keep it only if at least one keyword is shared.
        # CHANGE: use "score >= 0.2" to require a stronger match (fewer, better results).
        if score > 0:
            matches.append({
                "id": row["id"],
                "question": row["question"],
                "description": row["description"],
                "score": round(score, 2),   # Rounded to 2 decimals, like 0.33.
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
def inbox(user_id: str):
    con = db()

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


# Keeps track of every open chat window, grouped by room. Example: {"3-7": {window1, window2}}
# It lives in memory only, so it resets when the server restarts (saved messages stay in the database).
open_chats = {}


@app.websocket("/ws/{room}")   # A WebSocket is a connection that stays open so messages arrive instantly.
async def chat(ws: WebSocket, room: str):
    # Reject bad room names right away.
    try:
        parse_room(room)
    except HTTPException:
        await ws.close()
        return

    await ws.accept()                              # Accept the visitor's connection.
    open_chats.setdefault(room, set()).add(ws)     # Add them to the list for this room.

    # Send the last 50 saved messages so a new window isn't empty.
    # CHANGE: "LIMIT 50" = how much history to show.
    con = db()
    history = con.execute(
        "SELECT user_id, text FROM messages WHERE room = ? ORDER BY id DESC LIMIT 50",
        (room,),
    ).fetchall()
    con.close()
    for m in reversed(history):   # reversed() puts the oldest first, newest last.
        await ws.send_json({"user_id": m["user_id"], "text": m["text"]})

    try:
        while True:   # Keep listening for new messages until the visitor leaves.
            data = await ws.receive_json()
            # Call setup packets must be relayed live and must not be saved as chat history.
            if data.get("type") == "signal":
                # Get the WebRTC offer, answer, network candidate, or hang-up packet.
                signal = data.get("signal")
                # Ignore malformed call packets instead of trying to send them.
                if not isinstance(signal, dict):
                    continue
                # Add the sender id and packet type so the browser can tell it from chat text.
                packet = {"type": "signal", "user_id": str(data.get("user_id", ""))[:64], "signal": signal}
                # Send the call setup data to the other open windows in this room.
                for client in list(open_chats[room]):
                    # Do not send the packet back to the browser that created it.
                    if client is not ws:
                        await client.send_json(packet)
                # Skip the text-message save/broadcast code below.
                continue

            # Clean the message the same way as questions.
            text = str(data.get("text", "")).strip()[:MAX_MESSAGE]
            user_id = str(data.get("user_id", "")).strip()[:64]
            if not text or not user_id:   # Ignore empty messages.
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
                await client.send_json({"user_id": user_id, "text": text})
    except WebSocketDisconnect:
        # The visitor closed the page: remove them from the room.
        open_chats[room].discard(ws)


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


# This block only runs when you type "python server.py" (not when another file imports this one).
if __name__ == "__main__":
    # host="0.0.0.0" = accept connections from other devices on your Wi-Fi.
    #   CHANGE: use host="127.0.0.1" to allow only this computer (safer for private testing).
    # port=8000 = the "door number" in the address (http://IP:8000).
    #   CHANGE: use another number like 8080 if 8000 is already taken.
    uvicorn.run(app, host="0.0.0.0", port=8000)

