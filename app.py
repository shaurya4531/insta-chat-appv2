from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, random, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'app.db')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'replace-with-a-secure-secret')

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Create tables if not exist
    cur.execute(\"\"\"CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT,
        avatar_url TEXT,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )\"\"\")
    cur.execute(\"\"\"CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER NOT NULL,
        user2 INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user1, user2)
    )\"\"\")
    cur.execute(\"\"\"CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        text TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER DEFAULT 0
    )\"\"\")
    conn.commit()
    # Migration: ensure is_read column exists (for older DBs)
    try:
        cur.execute("SELECT is_read FROM messages LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
        conn.commit()
    conn.close()

init_db()

class User(UserMixin):
    def __init__(self, id_, username, display_name, avatar_url=None):
        self.id = id_
        self.username = username
        self.display_name = display_name or username
        self.avatar_url = avatar_url or ''

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return User(row['id'], row['username'], row['display_name'], row.get('avatar_url'))
    return None

def generate_unique_username(prefix='user_', length=4):
    conn = get_db()
    cur = conn.cursor()
    while True:
        suffix = ''.join(random.choices('0123456789', k=length))
        username = f\"{prefix}{suffix}\"
        cur.execute(\"SELECT id FROM users WHERE username=?\", (username,))
        if not cur.fetchone():
            conn.close()
            return username

def get_or_create_conversation(user_a, user_b):
    if user_a == user_b:
        return None
    a, b = min(user_a, user_b), max(user_a, user_b)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"SELECT * FROM conversations WHERE user1=? AND user2=?\", (a, b))
    row = cur.fetchone()
    if row:
        conv_id = row['id']
    else:
        cur.execute(\"INSERT INTO conversations (user1, user2) VALUES (?, ?)\", (a, b))
        conn.commit()
        conv_id = cur.lastrowid
    conn.close()
    return conv_id

def list_user_conversations(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"\"\"SELECT c.*, u1.username AS u1_name, u2.username AS u2_name,
                   u1.display_name AS u1_disp, u2.display_name AS u2_disp, u1.avatar_url AS u1_avatar, u2.avatar_url AS u2_avatar
                   FROM conversations c
                   JOIN users u1 ON u1.id = c.user1
                   JOIN users u2 ON u2.id = c.user2
                   WHERE c.user1=? OR c.user2=?
                   ORDER BY c.created_at DESC
                \"\"\", (user_id, user_id))
    rows = cur.fetchall()
    convs = []
    for r in rows:
        other_id = r['user1'] if r['user2']==user_id else r['user2']
        other_name = r['u1_name'] if other_id==r['user1'] else r['u2_name']
        other_disp = r['u1_disp'] if other_id==r['user1'] else r['u2_disp']
        other_avatar = r['u1_avatar'] if other_id==r['user1'] else r['u2_avatar']
        convs.append({'id': r['id'], 'other_id': other_id, 'other_username': other_name, 'other_display': other_disp, 'other_avatar': other_avatar, 'created_at': r['created_at']})
    conn.close()
    return convs

def get_conversation_messages(conv_id, limit=500):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"SELECT m.*, u.username AS sender_username, u.display_name as sender_display, u.avatar_url as sender_avatar FROM messages m JOIN users u ON u.id=m.sender_id WHERE m.conversation_id=? ORDER BY m.id ASC LIMIT ?\", (conv_id, limit))
    rows = cur.fetchall()
    msgs = []
    for r in rows:
        msgs.append({'id': r['id'], 'sender_id': r['sender_id'], 'sender_username': r['sender_username'], 'sender_display': r['sender_display'], 'sender_avatar': r['sender_avatar'], 'text': r['text'], 'timestamp': r['timestamp'], 'is_read': r['is_read']})
    conn.close()
    return msgs

@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('chat_list'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        display = request.form.get('display_name') or ''
        avatar = request.form.get('avatar_url') or ''
        password = request.form.get('password', '')
        if not password or len(password) < 3:
            flash('Password required (min 3 chars)', 'danger')
            return redirect(url_for('register'))
        username = generate_unique_username()
        password_hash = generate_password_hash(password)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(\"INSERT INTO users (username, display_name, avatar_url, password_hash) VALUES (?, ?, ?, ?)\", (username, display, avatar, password_hash))
        conn.commit()
        conn.close()
        flash(f'Account created. Your username is {username}', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        cur = conn.cursor()
        cur.execute(\"SELECT * FROM users WHERE username=?\", (username,))
        row = cur.fetchone()
        conn.close()
        if row and check_password_hash(row['password_hash'], password):
            user = User(row['id'], row['username'], row['display_name'], row.get('avatar_url'))
            login_user(user)
            flash('Logged in successfully', 'success')
            return redirect(url_for('chat_list'))
        flash('Invalid username or password', 'danger')
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        display = request.form.get('display_name') or current_user.display_name
        avatar = request.form.get('avatar_url') or ''
        conn = get_db()
        cur = conn.cursor()
        cur.execute(\"UPDATE users SET display_name=?, avatar_url=? WHERE id=?\", (display, avatar, current_user.id))
        conn.commit()
        conn.close()
        flash('Profile updated', 'success')
        return redirect(url_for('profile'))
    # fetch fresh data
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"SELECT display_name, avatar_url, username FROM users WHERE id=?\", (current_user.id,))
    row = cur.fetchone()
    conn.close()
    return render_template('profile.html', display_name=row['display_name'], avatar_url=row['avatar_url'], username=row['username'])

@app.route('/chat-list')
@login_required
def chat_list():
    convs = list_user_conversations(int(current_user.id))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"SELECT id, username, display_name, avatar_url FROM users WHERE id!=? ORDER BY id DESC LIMIT 50\", (current_user.id,))
    others = cur.fetchall()
    conn.close()
    return render_template('chat_list.html', convs=convs, others=others)

@app.route('/new-chat/<int:user_id>')
@login_required
def new_chat(user_id):
    conv_id = get_or_create_conversation(int(current_user.id), user_id)
    if conv_id is None:
        flash('Cannot start chat with yourself', 'danger')
        return redirect(url_for('chat_list'))
    return redirect(url_for('chat_room', conv_id=conv_id))

@app.route('/chat/<int:conv_id>')
@login_required
def chat_room(conv_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"SELECT * FROM conversations WHERE id=?\", (conv_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        flash('Conversation not found', 'danger')
        return redirect(url_for('chat_list'))
    if int(row['user1']) not in (int(current_user.id),) and int(row['user2']) not in (int(current_user.id),):
        conn.close()
        flash('Not a member of this conversation', 'danger')
        return redirect(url_for('chat_list'))
    messages = get_conversation_messages(conv_id)
    # mark messages as read for current user (simple approach)
    cur.execute(\"UPDATE messages SET is_read=1 WHERE conversation_id=? AND sender_id!=?\", (conv_id, current_user.id))
    conn.commit()
    conn.close()
    return render_template('chat_room.html', conv_id=conv_id, messages=messages, me_id=int(current_user.id))

# SocketIO
online_users = {}  # user_id -> sid

from flask import request  # local import
@socketio.on('connect')
def on_connect():
    pass

@socketio.on('register_socket')
def on_register_socket(data):
    user_id = int(data.get('user_id', 0))
    online_users[user_id] = request.sid
    emit('online_update', {'user_id': user_id, 'status': 'online'}, broadcast=True)

@socketio.on('typing')
def on_typing(data):
    conv = data.get('conv_id')
    user = data.get('user_id')
    emit('typing', {'conv_id': conv, 'user_id': user}, room=str(conv), include_self=False)

@socketio.on('stop_typing')
def on_stop_typing(data):
    conv = data.get('conv_id')
    user = data.get('user_id')
    emit('stop_typing', {'conv_id': conv, 'user_id': user}, room=str(conv), include_self=False)

@socketio.on('join_room')
def on_join(data):
    room = data.get('room')
    join_room(room)

@socketio.on('leave_room')
def on_leave(data):
    room = data.get('room')
    leave_room(room)

@socketio.on('send_message')
def on_message(data):
    conv_id = int(data.get('conv_id'))
    sender_id = int(data.get('sender_id'))
    text = data.get('text','').strip()
    timestamp = datetime.datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(\"INSERT INTO messages (conversation_id, sender_id, text, timestamp, is_read) VALUES (?, ?, ?, ?, 0)\", (conv_id, sender_id, text, timestamp))
    conn.commit()
    msg_id = cur.lastrowid
    cur.execute(\"SELECT username, display_name, avatar_url FROM users WHERE id=?\", (sender_id,))
    r = cur.fetchone()
    conn.close()
    payload = {'id': msg_id, 'conv_id': conv_id, 'sender_id': sender_id, 'sender_username': r['username'], 'sender_display': r['display_name'], 'sender_avatar': r['avatar_url'] or '', 'text': text, 'timestamp': timestamp, 'is_read': 0}
    emit('new_message', payload, room=str(conv_id))

@socketio.on('message_read')
def on_message_read(data):
    conv_id = int(data.get('conv_id'))
    user_id = int(data.get('user_id'))
    conn = get_db()
    cur = conn.cursor()
    # mark messages from other user as read
    cur.execute(\"UPDATE messages SET is_read=1 WHERE conversation_id=? AND sender_id!=?\", (conv_id, user_id))
    conn.commit()
    conn.close()
    emit('messages_read', {'conv_id': conv_id, 'reader_id': user_id}, room=str(conv_id))

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    to_remove = None
    for uid, s in list(online_users.items()):
        if s == sid:
            to_remove = uid
            break
    if to_remove:
        online_users.pop(to_remove, None)
        emit('online_update', {'user_id': to_remove, 'status': 'offline'}, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
