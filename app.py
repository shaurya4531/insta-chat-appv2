from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = "your_secret_key_here"
DATABASE = "chat.db"

# ---------- Database Setup ----------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)

    # Messages table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- Routes ----------
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("chat_list"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Please fill all fields")
            return redirect(url_for("register"))

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)))
            conn.commit()
            flash("Account created! Please log in.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already taken.")
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("chat_list"))
        else:
            flash("Invalid credentials.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/chats")
def chat_list():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id != ?", (session["user_id"],))
    users = cur.fetchall()
    conn.close()

    return render_template("chat_list.html", users=users)

@app.route("/chat/<int:user_id>", methods=["GET", "POST"])
def chat_room(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        message = request.form.get("message")
        if message:
            cur.execute("""
                INSERT INTO messages (sender_id, receiver_id, content)
                VALUES (?, ?, ?)
            """, (session["user_id"], user_id, message))
            conn.commit()

    # Get chat partner
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    partner = cur.fetchone()

    # Get messages between both users
    cur.execute("""
        SELECT * FROM messages
        WHERE (sender_id = ? AND receiver_id = ?)
        OR (sender_id = ? AND receiver_id = ?)
        ORDER BY timestamp
    """, (session["user_id"], user_id, user_id, session["user_id"]))
    messages = cur.fetchall()

    conn.close()
    return render_template("chat_room.html", partner=partner, messages=messages)

# ---------- Main ----------
if __name__ == "__main__":
    with app.app_context():
        init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
