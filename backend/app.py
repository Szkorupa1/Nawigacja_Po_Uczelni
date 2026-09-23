from flask import Flask, request, jsonify, render_template, redirect, url_for, session 
from functools import wraps
import html
import time
import bcrypt 
import secrets
import sqlite3
import os
from pathfinding import find_shortest_path
from graph_builder import GraphBuilder

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "baza.db")


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))


_report_rate: dict = {}   # klucz: IP, wartość: lista timestampów
 
def _check_rate_limit(ip: str, max_per_window: int = 5, window_sec: int = 600) -> bool:
    """Zwraca True jeśli wolno wysłać, False jeśli przekroczono limit."""
    now = time.time()
    times = [t for t in _report_rate.get(ip, []) if now - t < window_sec]
    _report_rate[ip] = times
    if len(times) >= max_per_window:
        return False
    _report_rate[ip].append(now)
    return True

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------- helper DB ----------
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def get_table_columns(table_name):
    with get_db_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [r["name"] for r in rows]


ROOM_COLS = {}
CONN_COLS = {}

def detect_columns():
    global ROOM_COLS, CONN_COLS
    ROOM_COLS = {}
    CONN_COLS = {}
    
    
    cols = get_table_columns("Rooms")
    for key in ("id","name","floor","status", "type"):
        found = next((c for c in cols if c.lower() == key), None)
        ROOM_COLS[key] = found if found else key
    
    
    cols2 = get_table_columns("Connections")
    for key in ("id","from_room","to_room","dystans","dodatkowy_czas","status","instrukcja_ab","instrukcja_ba","img_ab", "img_ba"):
        found = next((c for c in cols2 if c.lower() == key), None)
        CONN_COLS[key] = found if found else key

REPORTS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS Reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        message     TEXT    NOT NULL,
        start_room  TEXT    DEFAULT '',
        end_room    TEXT    DEFAULT '',
        start_label TEXT    DEFAULT '',
        end_label   TEXT    DEFAULT '',
        step        INTEGER DEFAULT NULL,
        total_steps INTEGER DEFAULT NULL,
        context     TEXT    DEFAULT '',
        ip          TEXT    DEFAULT '',
        is_read     INTEGER DEFAULT 0,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

def init_db():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                floor TEXT,
                type TEXT DEFAULT 'room',
                status TEXT DEFAULT 'Aktywny'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_room TEXT NOT NULL,
                to_room TEXT NOT NULL,
                dystans INTEGER,
                dodatkowy_czas INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Aktywny',
                instrukcja_ab TEXT,
                instrukcja_ba TEXT,
                img_ab BLOB,
                img_ba BLOB
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS AdminUsers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        conn.execute(REPORTS_TABLE_SQL)
        conn.commit()
    detect_columns()
    print("Baza danych zainicjalizowana")
    print(f"   Kolumny Rooms: {ROOM_COLS}")
    print(f"   Kolumny Connections: {CONN_COLS}")

def hash_password(password):
    """Haszuje hasło używając bcrypt"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt)

init_db()

def verify_password(password, password_hash):
    return bcrypt.checkpw(password.encode('utf-8'), password_hash)

def create_admin_user(username, password):
    """Tworzy nowego użytkownika admina"""
    with get_db_connection() as conn:
        try:
            password_hash = hash_password(password)
            conn.execute(
                "INSERT INTO AdminUsers (username, password_hash) VALUES (?, ?)",
                (username, password_hash)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def verify_admin_user(username, password):
    """Weryfikuje dane logowania admina"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM AdminUsers WHERE username = ?",
            (username,)
        ).fetchone()
        
        if not row:
            return False
        
        if verify_password(password, row['password_hash']):
            
            conn.execute(
                "UPDATE AdminUsers SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                (row['id'],)
            )
            conn.commit()
            return True
        
        return False

def admin_user_exists():
    """Sprawdza czy istnieje jakikolwiek użytkownik admina"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT COUNT(*) as count FROM AdminUsers").fetchone()
        return row['count'] > 0

# ---------- utilities ----------
def parse_int(value, default=None):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default



def room_id_to_name(conn, ref):
    """
    Konwertuje referencję pokoju (ID lub nazwę) na nazwę pokoju.
    
    """
    if ref is None or ref == "":
        return None

    s = str(ref).strip()
    
    
    import re
    s_clean = re.sub(r'\s*\(Piętro\s+\d+\)\s*$', '', s, flags=re.IGNORECASE).strip()
                                            
    
  
    row = conn.execute(
        f'SELECT {ROOM_COLS["name"]} AS name FROM Rooms WHERE LOWER(TRIM({ROOM_COLS["name"]}))=LOWER(?)',
        (s_clean,)
    ).fetchone()
    if row:
        return row["name"]

    
    if s_clean.isdigit():
        row = conn.execute(
            f'SELECT {ROOM_COLS["name"]} AS name FROM Rooms WHERE {ROOM_COLS["id"]}=?',
            (int(s_clean),)
        ).fetchone()
        if row:
            return row["name"]

    return None


def normalize_room_row(row):
    return {
        "id": row[ROOM_COLS["id"]],
        "name": row[ROOM_COLS["name"]],
        "floor": row[ROOM_COLS["floor"]] if ROOM_COLS["floor"] in row.keys() else None,
        "type": row[ROOM_COLS["type"]] if ROOM_COLS["type"] in row.keys() else "room",
        "status": row[ROOM_COLS["status"]] if ROOM_COLS["status"] in row.keys() else "Aktywny"
    }

def normalize_conn_row(row):
    return {
        "id": row[CONN_COLS["id"]],
        "from_room": row[CONN_COLS["from_room"]],
        "to_room": row[CONN_COLS["to_room"]],
        "dystans": row[CONN_COLS["dystans"]],
        "dodatkowy_czas": row[CONN_COLS["dodatkowy_czas"]],
        "status": row[CONN_COLS["status"]],
        "instrukcja_ab": row[CONN_COLS["instrukcja_ab"]],
        "instrukcja_ba": row[CONN_COLS["instrukcja_ba"]],
        "has_img_ab": bool(row[CONN_COLS["img_ab"]]),
        "has_img_ba": bool(row[CONN_COLS["img_ba"]]),
    }

# ---------- ROUTES / API ----------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Strona logowania lub tworzenia pierwszego konta"""
    setup_mode = not admin_user_exists()
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        if not username or not password:
            return render_template("login.html", 
                                 error="Wypełnij wszystkie pola", 
                                 setup_mode=setup_mode)
        
        
        if setup_mode:
            if len(password) < 6:
                return render_template("login.html", 
                                     error="Hasło musi mieć minimum 6 znaków", 
                                     setup_mode=True)
            
            if create_admin_user(username, password):
                session['logged_in'] = True
                session['username'] = username
                print(f" Utworzono pierwszego administratora: {username}")
                return redirect(url_for('admin_page'))
            else:
                return render_template("login.html", 
                                     error="Błąd tworzenia konta", 
                                     setup_mode=True)
        
        
        else:
            if verify_admin_user(username, password):
                session['logged_in'] = True
                session['username'] = username
                return redirect(url_for('admin_page'))
            else:
                return render_template("login.html", 
                                     error="Nieprawidłowe dane logowania", 
                                     setup_mode=False)
    
    return render_template("login.html", setup_mode=setup_mode)

@app.route("/admin/logout")
def admin_logout():
    """Wylogowanie użytkownika"""
    username = session.get('username', 'Nieznany')
    session.clear()
    print(f" Wylogowano użytkownika: {username}")
    return redirect(url_for('admin_login'))

@app.route("/admin")
@login_required
def admin_page():
    return render_template("admin.html")

@app.route("/route")
def route_page():
    """Strona z nawigacją krok po kroku"""
    return render_template("route.html", end_label=request.args.get("end_label"))

@app.route("/rooms", methods=["GET"])
def get_rooms():
    try:
        with get_db_connection() as conn:
            rows = conn.execute(f'SELECT * FROM Rooms ORDER BY {ROOM_COLS["id"]}').fetchall()
            out = [normalize_room_row(r) for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- ENDPOINT DO POBIERANIA ZDJĘĆ ----------
@app.route("/connection_image", methods=["GET"])
def get_connection_image():
    try:
        from_room = request.args.get("from")
        to_room = request.args.get("to")

        if not from_room or not to_room:
            return jsonify({"error": "Brak parametrów from/to"}), 400

        with get_db_connection() as conn:
            row = conn.execute(f"""
                SELECT
                    {CONN_COLS['from_room']} AS f,
                    {CONN_COLS['to_room']}   AS t,
                    {CONN_COLS['img_ab']}    AS img_ab,
                    {CONN_COLS['img_ba']}    AS img_ba
                FROM Connections
                WHERE ({CONN_COLS['from_room']}=? AND {CONN_COLS['to_room']}=?)
                   OR ({CONN_COLS['from_room']}=? AND {CONN_COLS['to_room']}=?)
                LIMIT 1
            """, (from_room, to_room, to_room, from_room)).fetchone()

            if not row:
                return jsonify({"error": "Połączenie nie istnieje"}), 404

            if row["f"] == from_room and row["t"] == to_room:
                img = row["img_ab"]
            else:
                img = row["img_ba"]

            if not img:
                return jsonify({"error": "Brak zdjęcia dla tego kierunku"}), 404

            from flask import Response
            return Response(img, mimetype="image/jpeg")

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/report", methods=["POST"])
def submit_report():
    try:
        ip = request.remote_addr or "unknown"

        if not _check_rate_limit(ip, max_per_window=5, window_sec=600):
            return jsonify({"error": "Zbyt wiele zgłoszeń. Spróbuj za chwilę."}), 429

        message = request.form.get("message", "").strip()
        message = html.escape(message)[:1000]

        if not message:
            return jsonify({"error": "Brak treści zgłoszenia"}), 400
        if len(message) < 5:
            return jsonify({"error": "Zgłoszenie jest zbyt krótkie"}), 400

        start_room  = html.escape(request.form.get("start", "")[:200])
        end_room    = html.escape(request.form.get("end", "")[:200])
        start_label = html.escape(request.form.get("start_label", "")[:200])
        end_label   = html.escape(request.form.get("end_label", "")[:200])
        context     = html.escape(request.form.get("context", "")[:100])

        step_raw        = request.form.get("step", "")
        total_steps_raw = request.form.get("total_steps", "")
        step        = int(step_raw)        if step_raw.isdigit()        else None
        total_steps = int(total_steps_raw) if total_steps_raw.isdigit() else None

        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO Reports
                  (message, start_room, end_room, start_label, end_label,
                   step, total_steps, context, ip)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message, start_room, end_room, start_label, end_label,
                 step, total_steps, context, ip)
            )
            conn.commit()

        return jsonify({"success": "Zgłoszenie zapisane"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/reports", methods=["GET"])
@login_required
def admin_get_reports():
    try:
        only_unread = request.args.get("unread") == "1"
        with get_db_connection() as conn:
            query = "SELECT * FROM Reports"
            if only_unread:
                query += " WHERE is_read = 0"
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rooms_active", methods=["GET"])
def get_rooms_active():
    try:
        with get_db_connection() as conn:
            rows = conn.execute(f'SELECT * FROM Rooms WHERE {ROOM_COLS["status"]}=? ORDER BY {ROOM_COLS["id"]}', ("Aktywny",)).fetchall()
            out = [normalize_room_row(r) for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/reports/<int:report_id>/read", methods=["POST"])
@login_required
def admin_mark_report_read(report_id):
    try:
        with get_db_connection() as conn:
            conn.execute("UPDATE Reports SET is_read=1 WHERE id=?", (report_id,))
            conn.commit()
        return jsonify({"success": "Oznaczono jako przeczytane"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/reports/<int:report_id>/delete", methods=["POST"])
@login_required
def admin_delete_report(report_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM Reports WHERE id=?", (report_id,))
            conn.commit()
        return jsonify({"success": "Usunięto zgłoszenie"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rooms_active_no_stairs", methods=["GET"])
def get_rooms_active_no_stairs():
    """
    Zwraca tylko aktywne pokoje, które NIE są schodami ani windą.
    
    """
    try:
        with get_db_connection() as conn:
            rows = conn.execute(f'''
                SELECT * FROM Rooms 
                WHERE {ROOM_COLS["status"]}=? 
                  AND {ROOM_COLS["type"]} NOT IN ('stairs', 'elevator')
                ORDER BY {ROOM_COLS["id"]}
            ''', ("Aktywny",)).fetchall()
            
            out = [normalize_room_row(r) for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/connections", methods=["GET"])
def get_connections():
    try:
        with get_db_connection() as conn:
            rows = conn.execute(f'SELECT * FROM Connections ORDER BY {CONN_COLS["id"]}').fetchall()
            out = [normalize_conn_row(r) for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/connection/<int:conn_id>", methods=["GET"])
def get_connection(conn_id):
    try:
        with get_db_connection() as conn:
            row = conn.execute(f'SELECT * FROM Connections WHERE {CONN_COLS["id"]}=?', (conn_id,)).fetchone()
        if not row:
            return jsonify({"error":"Połączenie nie istnieje"}), 404
        return jsonify(normalize_conn_row(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- admin add room ----------
@app.route("/admin/add_room", methods=["POST"])
@login_required
def admin_add_room():
    try:
        name = request.form.get("name")
        floor = request.form.get("floor") or "0"
        rtype = request.form.get("type") or "room"
        neighbor_ref = request.form.get("neighbor")
        distance = request.form.get("distance")
        extra = request.form.get("extra_time") or 0
        instructions = request.form.getlist("instructions")
        custom = request.form.get("custom_instruction")
        file_ab = request.files.get("image_ab")
        file_ba = request.files.get("image_ba")

        if not name or not neighbor_ref or not distance:
            return jsonify({"error": "Wymagane pola: name, neighbor, distance"}), 400

        d = parse_int(distance)
        et = parse_int(extra, default=0)
        if d is None or et is None:
            return jsonify({"error": "Dystans / dodatkowy czas muszą być liczbami"}), 400

        with get_db_connection() as conn:
           
            neighbor_raw = room_id_to_name(conn, neighbor_ref)
            if not neighbor_raw:
                return jsonify({"error": "Sąsiad nie istnieje"}), 400

            
            neighbor_name = force_corridor_endpoint(conn, neighbor_raw)
            if not neighbor_name:
                return jsonify({"error": "Nie znaleziono korytarza przed schodami"}), 400

            
            existing = conn.execute(
                f'SELECT 1 FROM Rooms WHERE {ROOM_COLS["name"]}=?',
                (name,)
            ).fetchone()
            if existing:
                return jsonify({"error": f"Pokój '{name}' już istnieje"}), 400

            img_ab = file_ab.read() if file_ab and file_ab.filename else None
            img_ba = file_ba.read() if file_ba and file_ba.filename else None
            instr_ab, instr_ba = split_instructions(instructions, custom)

            
            conn.execute(
                f'''
                INSERT INTO Rooms ({ROOM_COLS["name"]}, {ROOM_COLS["floor"]},
                                   {ROOM_COLS["type"]}, {ROOM_COLS["status"]})
                VALUES (?, ?, ?, ?)
                ''',
                (name, floor, rtype, "Aktywny")
            )

            
            from_name = name
            if rtype in ("stairs", "elevator"):
                from_name = resolve_connection_endpoint(conn, name)
                if not from_name:
                    return jsonify({"error": "Nie znaleziono korytarza dla nowo dodanych schodów"}), 400

            
            conn.execute(
    f'''
    INSERT INTO Connections
    (
        {CONN_COLS["from_room"]},
        {CONN_COLS["to_room"]},
        {CONN_COLS["dystans"]},
        {CONN_COLS["dodatkowy_czas"]},
        {CONN_COLS["status"]},
        {CONN_COLS["instrukcja_ab"]},
        {CONN_COLS["instrukcja_ba"]},
        {CONN_COLS["img_ab"]},
        {CONN_COLS["img_ba"]}
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''',
    (
        from_name,
        neighbor_name,
        d,
        et,
        "Aktywny",
        instr_ab,
        instr_ba,
        img_ab,   
        img_ba    
    )
)

            conn.commit()

        return jsonify({
            "message": f" Dodano pokój '{name}' i połączenie do '{neighbor_name}'"
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ---------- admin add connection ----------
@app.route("/admin/add_connection", methods=["POST"])
@login_required
def admin_add_connection():
    try:
        from_ref = request.form.get("from_room")
        to_ref = request.form.get("to_room")
        distance = request.form.get("distance")
        extra = request.form.get("extra_time") or 0
        instructions = request.form.getlist("instructions")
        custom = request.form.get("custom_instruction")
        status = request.form.get("status") or "Aktywny"

        file_ab = request.files.get("image_ab")
        file_ba = request.files.get("image_ba")

        if not from_ref or not to_ref or not distance:
            return jsonify({"error": "Wymagane: from_room, to_room, distance"}), 400

        d = parse_int(distance)
        et = parse_int(extra, default=0)
        if d is None or et is None:
            return jsonify({"error": "Dystans / dodatkowy czas muszą być liczbami"}), 400

        img_ab = file_ab.read() if file_ab and file_ab.filename else None
        img_ba = file_ba.read() if file_ba and file_ba.filename else None

        instr_ab, instr_ba = split_instructions(instructions, custom)

        with get_db_connection() as conn:
            from_raw = room_id_to_name(conn, from_ref)
            to_raw = room_id_to_name(conn, to_ref)

            if not from_raw or not to_raw:
                return jsonify({"error": "Podane pokoje nie istnieją"}), 400

            from_name = force_corridor_endpoint(conn, from_raw)
            to_name   = force_corridor_endpoint(conn, to_raw)

            if not from_name or not to_name:
                return jsonify({"error": "Nie znaleziono korytarza dla schodów/windy"}), 400

            exists = conn.execute(
                f"""
                SELECT 1 FROM Connections
                WHERE {CONN_COLS["from_room"]}=? AND {CONN_COLS["to_room"]}=?
                """,
                (from_name, to_name)
            ).fetchone()

            if exists:
                return jsonify({"error": "Takie połączenie już istnieje"}), 400

            conn.execute(
                f"""
                INSERT INTO Connections (
                    {CONN_COLS["from_room"]},
                    {CONN_COLS["to_room"]},
                    {CONN_COLS["dystans"]},
                    {CONN_COLS["dodatkowy_czas"]},
                    {CONN_COLS["status"]},
                    {CONN_COLS["instrukcja_ab"]},
                    {CONN_COLS["instrukcja_ba"]},
                    {CONN_COLS["img_ab"]},
                    {CONN_COLS["img_ba"]}
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    from_name,
                    to_name,
                    d,
                    et,
                    status,
                    instr_ab,
                    instr_ba,
                    img_ab,
                    img_ba,
                )
            )

            conn.commit()

        return jsonify({
            "message": f"✅ Dodano połączenie {from_name} → {to_name}"
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500




# ---------- admin edit connection ----------
@app.route("/admin/edit_connection", methods=["POST"])
@login_required
def admin_edit_connection():
    try:
        conn_id = request.form.get("id")
        if not conn_id:
            return jsonify({"error":"Brak id połączenia"}), 400

        from_ref = request.form.get("from_room")
        to_ref = request.form.get("to_room")
        distance = request.form.get("distance")
        extra = request.form.get("extra_time")
        instructions = request.form.getlist("instructions")
        custom = request.form.get("custom_instruction")
        status = request.form.get("status")
        file_ab = request.files.get("image_ab")
        file_ba = request.files.get("image_ba")


        updates = []
        params = []

        with get_db_connection() as conn:
            if from_ref:
                from_raw = room_id_to_name(conn, from_ref)
                if not from_raw:
                    return jsonify({"error":"from_room nie istnieje"}), 400

                from_name = force_corridor_endpoint(conn, from_raw)
                if not from_name:
                    return jsonify({"error":"Nie znaleziono korytarza dla from_room"}), 400

                updates.append(f'{CONN_COLS["from_room"]}=?')
                params.append(from_name)

            if to_ref:
                to_raw = room_id_to_name(conn, to_ref)
                if not to_raw:
                    return jsonify({"error":"to_room nie istnieje"}), 400

                to_name = force_corridor_endpoint(conn, to_raw)
                if not to_name:
                    return jsonify({"error":"Nie znaleziono korytarza dla to_room"}), 400

                updates.append(f'{CONN_COLS["to_room"]}=?')
                params.append(to_name)

            if distance is not None and distance != "":
                d = parse_int(distance)
                if d is None:
                    return jsonify({"error":"Dystans musi być liczbą"}), 400
                updates.append(f'{CONN_COLS["dystans"]}=?')
                params.append(d)
            
            if extra is not None and extra != "":
                et = parse_int(extra)
                if et is None:
                    return jsonify({"error":"Dodatkowy czas musi być liczbą"}), 400
                updates.append(f'{CONN_COLS["dodatkowy_czas"]}=?')
                params.append(et)
            
            if instructions or custom:
                instr_ab, instr_ba = split_instructions(instructions, custom)

                updates.append("instrukcja_ab=?")
                params.append(instr_ab)

                updates.append("instrukcja_ba=?")
                params.append(instr_ba)

            
            if status is not None:
                updates.append(f'{CONN_COLS["status"]}=?')
                params.append(status)
            
            if file_ab and file_ab.filename:
                img_ab = file_ab.read()
                updates.append(f'{CONN_COLS["img_ab"]}=?')
                params.append(img_ab)
            
            if file_ba and file_ba.filename:
                img_ba = file_ba.read()
                updates.append(f'{CONN_COLS["img_ba"]}=?')
                params.append(img_ba)


            if not updates:
                return jsonify({"error":"Brak pól do aktualizacji"}), 400

            params.append(conn_id)
            sql = f'UPDATE Connections SET {", ".join(updates)} WHERE {CONN_COLS["id"]}=?'
            conn.execute(sql, params)
            conn.commit()

        return jsonify({"message":f"✅ Połączenie {conn_id} zaktualizowane"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- set room status ----------
@app.route("/admin/set_room_status/<int:room_id>", methods=["POST"])
@login_required
def admin_set_room_status(room_id):
    """
    Ustawia status pokoju (Aktywny/Nieaktywny) i automatycznie
    aktualizuje status wszystkich powiązanych połączeń w tabeli Connections.
    """
    try:
        new_status = request.form.get("status")
        if new_status not in ("Aktywny", "Nieaktywny"):
            return jsonify({"error": "Nieprawidłowy status (Aktywny/Nieaktywny)"}), 400

        with get_db_connection() as conn:
            
            row = conn.execute(
                f'SELECT {ROOM_COLS["name"]} AS name FROM Rooms WHERE {ROOM_COLS["id"]}=?',
                (room_id,)
            ).fetchone()
            if not row:
                return jsonify({"error": "Pokój nie istnieje"}), 404

            name = row["name"]

            
            conn.execute(
                f'UPDATE Rooms SET {ROOM_COLS["status"]}=? WHERE {ROOM_COLS["id"]}=?',
                (new_status, room_id)
            )

            
            if new_status == "Nieaktywny":
                conn.execute(
                    f'''
                    UPDATE Connections 
                    SET {CONN_COLS["status"]}=? 
                    WHERE {CONN_COLS["from_room"]}=? OR {CONN_COLS["to_room"]}=?
                    ''',
                    ("Nieaktywny", name, name)
                )
            elif new_status == "Aktywny":
                conn.execute(
                    f'''
                    UPDATE Connections 
                    SET {CONN_COLS["status"]}=? 
                    WHERE {CONN_COLS["from_room"]}=? OR {CONN_COLS["to_room"]}=?
                    ''',
                    ("Aktywny", name, name)
                )

            conn.commit()

        return jsonify({
            "message": f" Pokój '{name}' ustawiono na {new_status} i zaktualizowano jego połączenia"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- admin edit room name ----------
@app.route("/admin/edit_room_name/<int:room_id>", methods=["POST"])
@login_required
def admin_edit_room_name(room_id):
    try:
        new_name = request.form.get("name")
        if not new_name:
            return jsonify({"error":"Brak nowej nazwy"}), 400

        with get_db_connection() as conn:
            
            row = conn.execute(f'SELECT {ROOM_COLS["name"]} as name FROM Rooms WHERE {ROOM_COLS["id"]}=?', (room_id,)).fetchone()
            if not row:
                return jsonify({"error":"Pokój nie istnieje"}), 404
            old_name = row["name"]

            
            exists = conn.execute(f'SELECT 1 FROM Rooms WHERE {ROOM_COLS["name"]}=?', (new_name,)).fetchone()
            if exists:
                return jsonify({"error":f"Pokój o nazwie '{new_name}' już istnieje"}), 400

            
            conn.execute(f'UPDATE Rooms SET {ROOM_COLS["name"]}=? WHERE {ROOM_COLS["id"]}=?', (new_name, room_id))

            
            conn.execute(
                f'UPDATE Connections SET {CONN_COLS["from_room"]}=? WHERE {CONN_COLS["from_room"]}=?', 
                (new_name, old_name)
            )
            conn.execute(
                f'UPDATE Connections SET {CONN_COLS["to_room"]}=? WHERE {CONN_COLS["to_room"]}=?', 
                (new_name, old_name)
            )
            conn.commit()

        return jsonify({"message":f"✅ Zmieniono nazwę pokoju '{old_name}' na '{new_name}'"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- set connection status ----------
@app.route("/admin/set_connection_status/<int:conn_id>", methods=["POST"])
@login_required
def admin_set_connection_status(conn_id):
    try:
        new_status = request.form.get("status")
        if new_status not in ("Aktywny","Nieaktywny"):
            return jsonify({"error":"Nieprawidłowy status"}), 400
        
        with get_db_connection() as conn:
            if not conn.execute(f'SELECT 1 FROM Connections WHERE {CONN_COLS["id"]}=?', (conn_id,)).fetchone():
                return jsonify({"error":"Połączenie nie istnieje"}), 404
            conn.execute(f'UPDATE Connections SET {CONN_COLS["status"]}=? WHERE {CONN_COLS["id"]}=?', (new_status, conn_id))
            conn.commit()
        
        return jsonify({"message":f"✅ Połączenie {conn_id} ustawione na {new_status}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- seed ----------
@app.route("/admin/seed", methods=["POST"])
@login_required
def admin_seed():
    try:
        with get_db_connection() as conn:
            if conn.execute('SELECT 1 FROM Rooms LIMIT 1').fetchone():
                return jsonify({"message": "Baza już ma dane"}), 400

            
            conn.execute(
                'INSERT INTO Rooms (name, floor, status) VALUES (?,?,?)',
                ("Wejście Główne", "0", "Aktywny")
            )
            conn.execute(
                'INSERT INTO Rooms (name, floor, status) VALUES (?,?,?)',
                ("100", "1", "Aktywny")
            )
            conn.execute(
                'INSERT INTO Rooms (name, floor, status) VALUES (?,?,?)',
                ("101", "1", "Aktywny")
            )

            
            conn.execute(
                '''
                INSERT INTO Connections
                (from_room, to_room, dystans, dodatkowy_czas,
                 status, instrukcja_ab, instrukcja_ba)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                ("100", "Wejście Główne", 11, 0,
                 "Aktywny", "idź prosto", "idź prosto")
            )

            conn.execute(
                '''
                INSERT INTO Connections
                (from_room, to_room, dystans, dodatkowy_czas,
                 status, instrukcja_ab, instrukcja_ba)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                ("101", "100", 5, 0,
                 "Aktywny", "idź prosto", "idź prosto")
            )

            conn.commit()

        detect_columns()
        return jsonify({"message": "✅ Zasiane testowe dane"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
@app.route("/admin/add_multi_floors", methods=["POST"])
@login_required
def admin_add_multi_floors():
    try:
        
        rtype = request.form.get("type") or "stairs"
        start_floor = parse_int(request.form.get("start_floor"))
        end_floor   = parse_int(request.form.get("end_floor"))
        extra_time = parse_int(request.form.get("extra_time"), 0)
        neighbor_ref = request.form.get("neighbor")

        
        stairs_distance = parse_int(request.form.get("stairs_distance"), 10)
        corridor_distance = parse_int(request.form.get("corridor_distance"), 0)

        if start_floor is None or end_floor is None:
            return jsonify({"error": "Nieprawidłowy zakres pięter"}), 400

        if start_floor > end_floor:
            return jsonify({"error": "start_floor nie może być większe niż end_floor"}), 400


        if not neighbor_ref:
            return jsonify({"error": "Nie wskazano pokoju sąsiada"}), 400

        with get_db_connection() as conn:
            
            neighbor_name = room_id_to_name(conn, neighbor_ref)
            if not neighbor_name:
                return jsonify({"error": "Sąsiad nie istnieje"}), 400

            results = []
            base = request.form.get("base") or rtype.capitalize()
            prev_stairs_name = None

            
            def add_connection_if_not_exists(room_a, room_b, distance, extra_time, instr_type="corridor"):
                exists = conn.execute(
                    f"""SELECT 1 FROM Connections WHERE ({CONN_COLS['from_room']}=? AND {CONN_COLS['to_room']}=?) OR ({CONN_COLS['from_room']}=? AND {CONN_COLS['to_room']}=?)""",
                    (room_a, room_b, room_b, room_a)
                ).fetchone()
                if exists:
                        return False
                if instr_type == "stairs":
                    instr_ab = "wejdź po schodach"
                    instr_ba = "zejdź po schodach"
                elif instr_type == "elevator":
                    instr_ab = "wjedź windą"
                    instr_ba = "zjedź windą"
                else:
                    instr_ab = "idź prosto"
                    instr_ba = "idź prosto"

                conn.execute(
                    f"""
                    INSERT INTO Connections(
                        {CONN_COLS['from_room']},
                        {CONN_COLS['to_room']},
                        {CONN_COLS['dystans']},
                        {CONN_COLS['dodatkowy_czas']},
                        {CONN_COLS['status']},
                        instrukcja_ab,
                        instrukcja_ba
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        room_a,
                        room_b,
                        distance,
                        extra_time,
                        "Aktywny",
                        instr_ab,
                        instr_ba
                    )
                )

                return True

            
            for floor in range(start_floor, end_floor + 1):
                

                
                stairs_name = f"{base} p.{floor}"
                corridor_name = f"{base} korytarz p.{floor}"

                added = {
                    "floor": floor,
                    "stairs_created": False,
                    "corridor_created": False,
                    "connections": []
                }

                
                if not conn.execute(f"SELECT 1 FROM Rooms WHERE {ROOM_COLS['name']}=?", (stairs_name,)).fetchone():
                    conn.execute(
                        f"INSERT INTO Rooms ({ROOM_COLS['name']}, {ROOM_COLS['floor']}, "
                        f"{ROOM_COLS['type']}, {ROOM_COLS['status']}) VALUES (?, ?, ?, ?)",
                        (stairs_name, str(floor), rtype, "Aktywny")
                    )
                    added["stairs_created"] = True

                
                if not conn.execute(f"SELECT 1 FROM Rooms WHERE {ROOM_COLS['name']}=?", (corridor_name,)).fetchone():
                    conn.execute(
                        f"INSERT INTO Rooms ({ROOM_COLS['name']}, {ROOM_COLS['floor']}, "
                        f"{ROOM_COLS['type']}, {ROOM_COLS['status']}) VALUES (?, ?, ?, ?)",
                        (corridor_name, str(floor), "corridor", "Aktywny")
                    )
                    added["corridor_created"] = True

                
                if add_connection_if_not_exists(corridor_name, stairs_name, corridor_distance, extra_time, instr_type=rtype):
                    added["connections"].append({
                        "from": corridor_name,
                        "to": stairs_name,
                        "distance": corridor_distance
                    })

                
                if floor == start_floor:
                    if add_connection_if_not_exists(neighbor_name, corridor_name, corridor_distance, extra_time, instr_type="corridor"):
                        added["connections"].append({
                            "from": neighbor_name,
                            "to": corridor_name,
                            "distance": corridor_distance
                        })

                
                if prev_stairs_name:
                    if add_connection_if_not_exists(prev_stairs_name, stairs_name, stairs_distance, extra_time, instr_type=rtype):
                        added["connections"].append({
                            "from": prev_stairs_name,
                            "to": stairs_name,
                            "distance": stairs_distance
                        })

                results.append(added)
                prev_stairs_name = stairs_name

            conn.commit()

        return jsonify(results), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route("/rooms_active_stairs_only", methods=["GET"])
def get_rooms_active_stairs_only():
    """
    Zwraca tylko schody i windy (bez korytarzy),
    z przyjazną nazwą do UI
    """
    try:
        with get_db_connection() as conn:
            rows = conn.execute(f"""
                SELECT *
                FROM Rooms
                WHERE {ROOM_COLS['status']}='Aktywny'
                  AND {ROOM_COLS['type']} IN ('stairs', 'elevator')
                ORDER BY {ROOM_COLS['floor']}
            """).fetchall()

            out = []
            for r in rows:
                name = r[ROOM_COLS["name"]]
                floor = r[ROOM_COLS["floor"]]

                
                label = name
                if floor and floor != "0":
                    label = f"{name} (Piętro {floor})"

                out.append({
                    "name": name,      
                    "label": label     
                })

        return jsonify(out)

    except Exception as e:
        return jsonify({"error": str(e)}), 500




def resolve_connection_endpoint(conn, room_name):
   

    row = conn.execute(
        f"""
        SELECT {ROOM_COLS['type']} AS type,
               {ROOM_COLS['floor']} AS floor,
               {ROOM_COLS['name']} AS name
        FROM Rooms
        WHERE {ROOM_COLS['name']}=?
        """,
        (room_name,)
    ).fetchone()

    if not row:
        return None

    if row["type"] in ("stairs", "elevator"):
        
        corridor = conn.execute(
            f"""
            SELECT {ROOM_COLS['name']} AS name
            FROM Rooms
            WHERE {ROOM_COLS['type']}='corridor'
              AND {ROOM_COLS['floor']}=?
              AND {ROOM_COLS['name']} LIKE ?
            """,
            (row["floor"], f"%{row['name'].replace(f' p.{row['floor']}', '')}%")
        ).fetchone()

        return corridor["name"] if corridor else row["name"]

    return row["name"]

def compress_straight_instructions(path):
    """
    Łączy kolejne kroki z tą samą instrukcją.
    
    POPRAWKA: 
    - Pierwszy krok ZAWSZE osobno 
    - Od drugiego kroku scalamy te same instrukcje
    - Zachowuje pierwsze zdjęcie ze scalanych kroków
    """
    if not path or len(path) == 0:
        return []

    MERGEABLE = {
        "idź prosto",
        "wejdź po schodach",
        "zejdź po schodach",
        "wjedź windą",
        "zjedź windą"
    }

    compressed = []
    
    
    first = dict(path[0])
    if "image_from" not in first:
        first["image_from"] = first["from"]
    if "image_to" not in first:
        first["image_to"] = first["to"]
    
    compressed.append(first)  
    
    
    if len(path) == 1:
        return compressed

    
    current = dict(path[1])
    if "image_from" not in current:
        current["image_from"] = current["from"]
    if "image_to" not in current:
        current["image_to"] = current["to"]

    
    for step in path[2:]:
        
        if (
            step["instruction"] == current["instruction"]
            and step["instruction"] in MERGEABLE
        ):
            
            current["to"] = step["to"]
            current["distance"] += step["distance"]
            current["extra_time"] += step.get("extra_time", 0)
            
            
            if not current.get("image_from") or not current.get("image_to"):
                if step.get("image_from") and step.get("image_to"):
                    current["image_from"] = step["image_from"]
                    current["image_to"] = step["image_to"]
        else:
            
            compressed.append(current)
            current = dict(step)
            
            if "image_from" not in current:
                current["image_from"] = current["from"]
            if "image_to" not in current:
                current["image_to"] = current["to"]

    
    compressed.append(current)
    
    return compressed


def force_corridor_endpoint(conn, room_name):
    row = conn.execute(
        f"""
        SELECT {ROOM_COLS['type']} AS type,
               {ROOM_COLS['floor']} AS floor,
               {ROOM_COLS['name']} AS name
        FROM Rooms
        WHERE {ROOM_COLS['name']}=?
        """,
        (room_name,)
    ).fetchone()

    if not row:
        return None

    
    if row["type"] not in ("stairs", "elevator"):
        return row["name"]

    
    base = row["name"]
    base = base.replace(f" p.{row['floor']}", "").strip()

    corridor = conn.execute(
        f"""
        SELECT {ROOM_COLS['name']} AS name
        FROM Rooms
        WHERE {ROOM_COLS['type']}='corridor'
          AND {ROOM_COLS['floor']}=?
          AND {ROOM_COLS['name']} LIKE ?
        """,
        (row["floor"], f"{base} korytarz%")
    ).fetchone()

    
    return corridor["name"] if corridor else row["name"]


# ==========  2: split_instructions ==========
def split_instructions(instructions, custom_instruction=None):
    
    instructions = instructions or []

    def join(instr_list, custom):
        base = ", ".join(instr_list)
        if custom:
            return f"{base} | {custom}" if base else custom
        return base

    instrukcja_ab_list = []
    instrukcja_ba_list = []

    for instr in instructions:
        low = instr.lower()

        
        if "skręć w lewo" in low:
            instrukcja_ab_list.append("skręć w lewo")   
            instrukcja_ba_list.append("skręć w prawo")  
        elif "skręć w prawo" in low:
            instrukcja_ab_list.append("skręć w prawo")  
            instrukcja_ba_list.append("skręć w lewo")   
        else:
           
            instrukcja_ab_list.append(instr)
            instrukcja_ba_list.append(instr)

    return (
        join(instrukcja_ab_list, custom_instruction),
        join(instrukcja_ba_list, custom_instruction),
    )


# ========== KROK 2:  normalize_stairs_and_elevators ==========


def normalize_stairs_and_elevators(path):
    """
    ukrywa WSZYSTKIE korytarze przed użytkownikiem.
    
   
    """
    if not path:
        return []

    def is_stairs(x): return "schod" in x.lower()
    def is_elevator(x): return "wind" in x.lower()
    def is_corridor(x): return "korytarz" in x.lower()
    def is_vertical(x): return is_stairs(x) or is_elevator(x)

    result = []
    i = 0

    while i < len(path):
        step = path[i]
        
        
        if is_corridor(step["to"]) and i + 1 < len(path) and is_vertical(path[i + 1]["to"]):
            result.append({
                "from": step["from"],
                "to": path[i + 1]["to"],  
                "instruction": step["instruction"],
                "distance": step["distance"] + path[i + 1]["distance"],
                "extra_time": step.get("extra_time", 0) + path[i + 1].get("extra_time", 0),
                "image_from": step.get("image_from", step["from"]),
                "image_to": step.get("image_to", step["to"])
            })
            i += 2
            continue

        
        if is_vertical(step["from"]) and is_corridor(step["to"]):
            if i + 1 < len(path):
                result.append({
                    "from": step["from"],
                    "to": path[i + 1]["to"],  
                    "instruction": path[i + 1]["instruction"],
                    "distance": step["distance"] + path[i + 1]["distance"],
                    "extra_time": step.get("extra_time", 0) + path[i + 1].get("extra_time", 0),
                    "image_from": step.get("image_from", step["from"]),
                    "image_to": path[i + 1].get("image_to", path[i + 1]["to"])
                })
                i += 2
                continue
            else:
                
                i += 1
                continue

        
        if is_corridor(step["from"]) and is_corridor(step["to"]):
            i += 1
            continue

        
        result.append({
            "from": step["from"],
            "to": step["to"],
            "instruction": step["instruction"],
            "distance": step["distance"],
            "extra_time": step.get("extra_time", 0),
            "image_from": step.get("image_from", step["from"]),
            "image_to": step.get("image_to", step["to"])
        })
        i += 1

    return result



def format_room_label(name: str):
    
    import re

    def repl(match):
        return f"(Piętro {match.group(1)})"

    return re.sub(r"\bp\.(\d+)\b", repl, name)




# ---------- ENDPOINT WYSZUKIWANIA TRASY ----------
@app.route("/find_route", methods=["GET"])
def find_route():
    try:
        start = request.args.get("start")
        end = request.args.get("end")
        avoid_stairs = request.args.get("avoid_stairs", "false").lower() == "true"
        avoid_elevator = request.args.get("avoid_elevator", "false").lower() == "true"

        if not start or not end:
            return jsonify({"error": "Brak parametrów start/end"}), 400

        
        with get_db_connection() as conn:
            result, error = find_shortest_path(
                conn,
                CONN_COLS,
                start,
                end,
                avoid_stairs,
                avoid_elevator
            )

        if error:
            return jsonify({"error": error}), 404

        if result and "path" in result:
           
            for step in result["path"]:
                step["image_from"] = step["from"]
                step["image_to"] = step["to"]
            
            
            result["path"] = normalize_stairs_and_elevators(result["path"])
            
            
            result["path"] = compress_straight_instructions(result["path"])
            
            
            for step in result["path"]:
                step["from"] = format_room_label(step["from"])
                step["to"] = format_room_label(step["to"])
            
            
            result["total_distance"] = sum(
                step.get("distance", 0) for step in result["path"]
            )
            result["steps"] = len(result["path"])

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500




    
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
