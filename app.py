# app.py
import os
import json
import random
import sqlite3
from pathlib import Path
from flask import Flask, render_template, jsonify, request, g
from flask_socketio import SocketIO, emit, join_room
import chess  # python-chess

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "db" / "leaderboard.sqlite"
DATA_DIR.mkdir(exist_ok=True)
(DB_PATH.parent).mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['SECRET_KEY'] = 'replace_this_secret'
socketio = SocketIO(app, async_mode='eventlet')

# --- DB helpers ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
    return db

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS leaderboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Load JSON data functions ---
def load_writers():
    path = DATA_DIR / "writers.json"
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    else:
        return {"golden_age": [], "silver_age": [], "soviet_period": []}

def load_quiz():
    path = DATA_DIR / "quiz_questions.json"
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    else:
        return []

# --- Routes / Pages ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/writers")
def writers_page():
    return render_template("writers_list.html")

@app.route("/writers/<writer_id>")
def writer_detail(writer_id):
    return render_template("writer_detail.html", writer_id=writer_id)

@app.route("/chess")
def chess_page():
    return render_template("chess.html")

@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html")

# --- API: Writers ---
@app.route("/api/writers")
def api_writers():
    data = load_writers()
    return jsonify(data)

@app.route("/api/writer/<writer_id>")
def api_writer(writer_id):
    data = load_writers()
    for epoch, lst in data.items():
        for w in lst:
            if str(w.get("id")) == str(writer_id):
                return jsonify(w)
    return jsonify({"error": "not found"}), 404

# --- API: Quiz ---
@app.route("/api/quiz/start")
def api_quiz_start():
    questions = load_quiz()
    if len(questions) < 15:
        return jsonify({"error": "Not enough questions in bank"}), 400
    selected = random.sample(questions, 15)
    return jsonify(selected)

@app.route("/api/quiz/submit", methods=["POST"])
def api_quiz_submit():
    payload = request.json
    name = payload.get("name", "Anonymous")
    score = int(payload.get("score", 0))
    total = int(payload.get("total", 0))
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO leaderboard (name, score, total) VALUES (?, ?, ?)", (name, score, total))
    db.commit()
    return jsonify({"status": "ok"})

@app.route("/api/leaderboard")
def api_leaderboard():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT name, score, total, timestamp FROM leaderboard ORDER BY score DESC, timestamp ASC LIMIT 50")
    rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)

# --- Chess real-time support ---
games = {}

@socketio.on('join_game')
def on_join_game(data):
    room = data.get('room') or 'default'
    join_room(room)
    sid = request.sid
    game = games.get(room)
    if not game:
        board = chess.Board()
        game = {'board': board, 'players': [], 'fen': board.fen()}
        games[room] = game
    if sid not in game['players']:
        game['players'].append(sid)
    emit('game_state', {'fen': game['fen']}, room=sid)

@socketio.on('make_move')
def on_make_move(data):
    room = data.get('room') or 'default'
    uci = data.get('uci')
    sid = request.sid
    game = games.get(room)
    if not game:
        emit('error', {'msg': 'game not found'}, to=sid)
        return
    board = game['board']
    try:
        move = chess.Move.from_uci(uci)
    except Exception:
        emit('invalid_move', {'msg': 'invalid uci'}, to=sid)
        return
    if move in board.legal_moves:
        board.push(move)
        game['fen'] = board.fen()
        emit('move_made', {'uci': uci, 'fen': board.fen()}, room=room)
    else:
        emit('invalid_move', {'msg': 'illegal move'}, to=sid)

@socketio.on('reset_game')
def on_reset(data):
    room = data.get('room') or 'default'
    board = chess.Board()
    games[room] = {'board': board, 'players': [], 'fen': board.fen()}
    emit('game_state', {'fen': board.fen()}, room=room)

if __name__ == "__main__":
    init_db()
    socketio.run(app, host='0.0.0.0', port=3000)