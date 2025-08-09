from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
DATABASE = "chat.db"

# ---------------- DB helpers ----------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            avatar_url TEXT,
            password_hash TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1 INTEGER NOT NULL,
            user2 INTEGER NOT NULL,
            UNIQUE(user1, user2)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            text TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

# ---------------- Routes ----------------
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("chats"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        display_name = request.form.get("display_name")
        avatar_url = request.form.get("avatar_url")

        if not username or not password:
            flash("Username and password are required")
            return redirect(url_for("register"))

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO users (username, display_name, avatar_url, password_hash)
                VALUES (?, ?, ?, ?)
            """, (username, display_name, avatar_url, generate_password_hash(password)))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Username already exists")
            return redirect(url_for("register"))

        flash("Account created. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("chats"))
        else:
            flash("Invalid credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/chats")
def chats():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, u.id AS user_id, u.username, u.display_name, u.avatar_url
        FROM conversations c
        JOIN users u ON (u.id = c.user1 OR u.id = c.user2)
        WHERE (c.user1 = ? OR c.user2 = ?) AND u.id != ?
    """, (session["user_id"], session["user_id"], session["user_id"]))
    chat_list = cur.fetchall()

    return render_template("chats.html", chats=chat_list)

@app.route("/chat/<int:user_id>", methods=["GET", "POST"])
def chat(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO conversations (user1, user2)
        VALUES (?, ?)
    """, (min(session["user_id"], user_id), max(session["user_id"], user_id)))
    conn.commit()

    cur.execute("""
        SELECT id FROM conversations
        WHERE (user1=? AND user2=?) OR (user1=? AND user2=?)
    """, (session["user_id"], user_id, user_id, session["user_id"]))
    conversation_id = cur.fetchone()["id"]

    if request.method == "POST":
        text = request.form.get("text")
        if text.strip():
            cur.execute("""
                INSERT INTO messages (conversation_id, sender_id, text)
                VALUES (?, ?, ?)
            """, (conversation_id, session["user_id"], text))
            conn.commit()

    cur.execute("""
        SELECT m.*, u.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE conversation_id = ?
        ORDER BY timestamp ASC
    """, (conversation_id,))
    messages = cur.fetchall()

    return render_template("chat.html", messages=messages, receiver_id=user_id)

# ---------------- Main ----------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
