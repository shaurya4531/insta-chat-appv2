from flask import Flask, render_template, request, redirect, url_for, session, g
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

# -----------------------
# CONFIGURATION
# -----------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
DATABASE = "chat_app.db"

# -----------------------
# DATABASE HELPERS
# -----------------------
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT,
        avatar_url TEXT,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Conversations table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER NOT NULL,
        user2 INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user1, user2)
    )
    """)

    # Messages table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        text TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER DEFAULT 0
    )
    """)

    conn.commit()

# -----------------------
# AUTHENTICATION
# -----------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        display_name = request.form.get("display_name", username)

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
                (username, display_name, generate_password_hash(password)),
            )
            db.commit()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return "Username already taken."

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("chat_list"))
        return "Invalid credentials."

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------
# CHAT FUNCTIONALITY
# -----------------------
@app.route("/")
def chat_list():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    conversations = db.execute("""
        SELECT c.id, u.username, u.display_name
        FROM conversations c
        JOIN users u ON (u.id = CASE WHEN c.user1 = ? THEN c.user2 ELSE c.user1 END)
        WHERE c.user1 = ? OR c.user2 = ?
    """, (session["user_id"], session["user_id"], session["user_id"])).fetchall()

    return render_template("chat_list.html", conversations=conversations)

@app.route("/chat/<int:conversation_id>", methods=["GET", "POST"])
def chat_room(conversation_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    if request.method == "POST":
        text = request.form["text"]
        db.execute(
            "INSERT INTO messages (conversation_id, sender_id, text) VALUES (?, ?, ?)",
            (conversation_id, session["user_id"], text)
        )
        db.commit()

    messages = db.execute("""
        SELECT m.text, m.timestamp, u.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.conversation_id = ?
        ORDER BY m.timestamp ASC
    """, (conversation_id,)).fetchall()

    return render_template("chat_room.html", messages=messages, conversation_id=conversation_id)

@app.route("/start_chat/<int:user_id>")
def start_chat(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()

    convo = db.execute("""
        SELECT * FROM conversations
        WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)
    """, (session["user_id"], user_id, user_id, session["user_id"])).fetchone()

    if not convo:
        db.execute(
            "INSERT INTO conversations (user1, user2) VALUES (?, ?)",
            (session["user_id"], user_id)
        )
        db.commit()
        convo_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    else:
        convo_id = convo["id"]

    return redirect(url_for("chat_room", conversation_id=convo_id))

# -----------------------
# RUN APP
# -----------------------
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=5000)
