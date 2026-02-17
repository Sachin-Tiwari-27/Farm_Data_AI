import sqlite3
import json
import os
import uuid
import threading
import logging
from datetime import datetime

# --- CONFIGURATION ---
DB_DIR = "data/db"
MEDIA_DIR = "data/media"
SQL_FILE = os.path.join(DB_DIR, "farm.db")
JSON_USERS = os.path.join(DB_DIR, "users.json")
JSON_LOGS = os.path.join(DB_DIR, "logs.json")

logger = logging.getLogger(__name__)

# --- CONSTANTS ---
ENV_FIELD = "Open Field"
ENV_POLY = "Polyhouse"
ENV_CEA = "Controlled Env (CEA)"

MED_SOIL = "Soil"
MED_COCO = "Cocopeat"
MED_MIX = "Soil + Cocopeat"
MED_HYDRO = "Hydroponic"
MED_OTHER = "Other"

# --- DATA CLASSES ---
class Landmark:
    def __init__(self, data):
        # We now use 'landmark_id' (1-20) instead of global DB 'id'
        self.id = data.get('landmark_id') or data.get('id')
        self.label = data.get('label', f"Spot {self.id}")
        self.env = data.get('env', ENV_FIELD)
        self.medium = data.get('medium', MED_SOIL)

    def to_dict(self):
        return {
            "id": self.id, "label": self.label,
            "env": self.env, "medium": self.medium
        }

class User:
    def __init__(self, data):
        self.id = data.get('id')
        self.full_name = data.get('name')
        self.farm_name = data.get('farm')
        self.latitude = data.get('lat')
        self.longitude = data.get('lon')
        self.photo_time = data.get('p_time')
        self.voice_time = data.get('v_time')
        lm_data = data.get('landmarks', [])
        self.landmarks = [Landmark(lm) if isinstance(lm, dict) else lm for lm in lm_data]

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.full_name,
            "farm": self.farm_name,
            "lat": self.latitude,
            "lon": self.longitude,
            "p_time": self.photo_time,
            "v_time": self.voice_time,
            "landmarks": [lm.to_dict() for lm in self.landmarks]
        }

class LogEntry:
    def __init__(self, data):
        self.id = data.get('id')
        self.user_id = data.get('user_id')
        self.landmark_id = data.get('landmark_id')
        self.category = data.get('category', 'adhoc') 
        self.status = data.get('status')
        self.timestamp = datetime.fromisoformat(data.get('timestamp'))
        self.files = data.get('files', {})
        self.transcription = data.get('transcription', "")
        self.weather = data.get('weather', {})
        
        # Smart Name Logic
        self.landmark_name = data.get('landmark_name')
        if not self.landmark_name or self.landmark_name == "General/Evening":
            if self.category == 'evening': self.landmark_name = "Evening Summary"
            elif self.landmark_id == 99: self.landmark_name = "General Ad-hoc"
            else: self.landmark_name = f"Spot {self.landmark_id}"

# --- DATABASE CORE ---
def get_db():
    # check_same_thread=False is REQUIRED for background sync to work
    conn = sqlite3.connect(SQL_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT, farm TEXT,
        lat REAL, lon REAL,
        p_time TEXT, v_time TEXT
    )''')
    
    # --- MIGRATION: Landmark ID Logic ---
    # Check if landmark_id column exists. If not, we migrate.
    c.execute("PRAGMA table_info(landmarks)")
    cols = [row[1] for row in c.fetchall()]
    
    if "landmark_id" not in cols and "user_id" in cols:
        logger.info("Migrating landmarks to per-user ID schema...")
        # 1. Backup old landmarks
        c.execute("ALTER TABLE landmarks RENAME TO landmarks_old")
        
        # 2. Create New Table
        c.execute('''CREATE TABLE landmarks (
            user_id INTEGER,
            landmark_id INTEGER,
            label TEXT, env TEXT, medium TEXT,
            PRIMARY KEY(user_id, landmark_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        
        # 3. Migrate Data & Re-index Logs
        # We need to map old global IDs to new per-user IDs (1, 2, 3...)
        old_lms = c.execute("SELECT * FROM landmarks_old ORDER BY user_id, id").fetchall()
        
        user_counts = {}
        for row in old_lms:
            uid = row['user_id']
            old_id = row['id']
            
            # Generate new 1-20 ID
            new_id = user_counts.get(uid, 0) + 1
            user_counts[uid] = new_id
            
            # Insert into new table
            c.execute("""
                INSERT INTO landmarks (user_id, landmark_id, label, env, medium)
                VALUES (?, ?, ?, ?, ?)
            """, (uid, new_id, row['label'], row['env'], row['medium']))
            
            # CRITICAL: Update logs to use the new ID
            c.execute("UPDATE logs SET landmark_id = ? WHERE user_id = ? AND landmark_id = ?", (new_id, uid, old_id))
            
        c.execute("DROP TABLE landmarks_old")
        logger.info("Landmark migration complete.")
    
    # Standard Creation (if first run)
    c.execute('''CREATE TABLE IF NOT EXISTS landmarks (
        user_id INTEGER,
        landmark_id INTEGER,
        label TEXT, env TEXT, medium TEXT,
        PRIMARY KEY(user_id, landmark_id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        landmark_id INTEGER,
        category TEXT,
        status TEXT,
        timestamp TEXT,
        date TEXT,
        weather_json TEXT,
        transcription TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_id TEXT,
        file_path TEXT,
        file_type TEXT,
        FOREIGN KEY(log_id) REFERENCES logs(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ai_interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        log_id TEXT,
        prompt TEXT,
        response TEXT,
        model_used TEXT,
        rating INTEGER DEFAULT 0,
        timestamp TEXT,
        feedback_status TEXT DEFAULT 'NA',
        feedback_note TEXT DEFAULT '',
        FOREIGN KEY(log_id) REFERENCES logs(id)
    )''')
    
    # --- MIGRATION: Add Feedback Columns ---
    c.execute("PRAGMA table_info(ai_interactions)")
    ai_cols = [row[1] for row in c.fetchall()]
    if "feedback_status" not in ai_cols:
        c.execute("ALTER TABLE ai_interactions ADD COLUMN feedback_status TEXT DEFAULT 'NA'")
        c.execute("ALTER TABLE ai_interactions ADD COLUMN feedback_note TEXT DEFAULT ''")
    
    conn.commit()
    conn.close()
    
    # Trigger initial sync
    if not os.path.exists(JSON_USERS):
        trigger_sync()


def sync_to_json_shadow():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Sync Users
        cursor.execute("SELECT * FROM users")
        users_rows = cursor.fetchall()
        users_dict = {}
        
        for u in users_rows:
            uid = u['id']
            cursor.execute("SELECT * FROM landmarks WHERE user_id=?", (uid,))
            lm_rows = cursor.fetchall()
            landmarks = [dict(lm) for lm in lm_rows]
            
            users_dict[str(uid)] = {
                "id": uid, "name": u['name'], "farm": u['farm'],
                "lat": u['lat'], "lon": u['lon'],
                "p_time": u['p_time'], "v_time": u['v_time'],
                "landmarks": landmarks
            }
            
        with open(JSON_USERS, 'w') as f:
            json.dump(users_dict, f, indent=4)
            
        # Sync Logs
        cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC")
        log_rows = cursor.fetchall()
        logs_list = []
        
        for log in log_rows:
            log_id = log['id']
            cursor.execute("SELECT file_type, file_path FROM media WHERE log_id=?", (log_id,))
            media_rows = cursor.fetchall()
            files_dict = {m['file_type']: m['file_path'] for m in media_rows}
            
            entry = {
                "id": log_id,
                "user_id": log['user_id'],
                "landmark_id": log['landmark_id'],
                "category": log['category'],
                "status": log['status'],
                "timestamp": log['timestamp'],
                "date": log['date'],
                "weather": json.loads(log['weather_json']) if log['weather_json'] else {},
                "transcription": log['transcription'],
                "files": files_dict
            }
            logs_list.append(entry)
            
        with open(JSON_LOGS, 'w') as f:
            json.dump(logs_list, f, indent=4)
            
        conn.close()
    except Exception as e:
        logger.error(f"Shadow Sync Failed: {e}")

def trigger_sync():
    # Run in background thread
    threading.Thread(target=sync_to_json_shadow, daemon=True).start()

# --- USER FUNCTIONS ---
def get_user_profile(user_id):
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not u:
        conn.close()
        return None
    
    lms = conn.execute("SELECT * FROM landmarks WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    
    user_data = dict(u)
    # Map 'landmark_id' to the '.id' attribute for compatibility
    user_data['landmarks'] = [dict(l) for l in lms]
    return User(user_data)

def update_user_schedule(user_id, p_time=None, v_time=None):
    conn = get_db()
    if p_time:
        conn.execute("UPDATE users SET p_time=? WHERE id=?", (p_time, user_id))
    if v_time:
        conn.execute("UPDATE users SET v_time=? WHERE id=?", (v_time, user_id))
    conn.commit()
    conn.close()
    trigger_sync()

def save_user_profile(user_data):
    conn = get_db()
    c = conn.cursor()
    
    # 1. Update User Info
    c.execute("""
        INSERT OR REPLACE INTO users (id, name, farm, lat, lon, p_time, v_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_data['id'], user_data['name'], user_data['farm'],
        user_data['lat'], user_data['lon'],
        user_data['p_time'], user_data['v_time']
    ))
    
    # 2. Update Landmarks - Now using stable per-user IDs (1-20)
    c.execute("DELETE FROM landmarks WHERE user_id=?", (user_data['id'],))
    
    for lm in user_data.get('landmarks', []):
        if hasattr(lm, 'to_dict'): lm = lm.to_dict()
        
        # We prioritize 'landmark_id' or 'id' from the dict
        l_id = lm.get('landmark_id') or lm.get('id')
        
        c.execute("""
            INSERT INTO landmarks (user_id, landmark_id, label, env, medium)
            VALUES (?, ?, ?, ?, ?)
        """, (user_data['id'], l_id, lm['label'], lm['env'], lm['medium']))
        
    conn.commit()
    conn.close()
    trigger_sync()

def get_all_user_ids():
    """Returns a list of all registered user IDs for job restoration."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT id FROM users").fetchall()
        return [row['id'] for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

def get_user_landmarks(user_id):
    user = get_user_profile(user_id)
    return user.landmarks if user else []

def get_landmark_by_id(user_id, landmark_id):
    user = get_user_profile(user_id)
    if not user: return None
    for lm in user.landmarks:
        if lm.id == int(landmark_id): return lm
    return None

def get_pending_landmark_ids(user_id):
    """ Returns list of landmark IDs that have NOT been checked this morning. """
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    all_lms = conn.execute("SELECT landmark_id FROM landmarks WHERE user_id=?", (user_id,)).fetchall()
    all_ids = set(row['landmark_id'] for row in all_lms)
    
    done_lms = conn.execute("""
        SELECT landmark_id FROM logs 
        WHERE user_id=? AND date=? AND category='morning'
    """, (user_id, today)).fetchall()
    done_ids = set(row['landmark_id'] for row in done_lms)
    
    conn.close()
    return sorted(list(all_ids - done_ids))

# --- OTHER DB FUNCTIONS ---
def get_entries_by_date_range(user_id, start_date, end_date):
    conn = get_db()
    s_str = start_date.strftime("%Y-%m-%d")
    e_str = end_date.strftime("%Y-%m-%d")
    query = "SELECT date, COUNT(*) as count FROM logs WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY date"
    rows = conn.execute(query, (user_id, s_str, e_str)).fetchall()
    conn.close()
    return {row['date']: row['count'] for row in rows}

def is_routine_done(user_id, routine_type):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    try:
        if routine_type == 'morning':
            # Get count of user's current landmarks
            lms = conn.execute("SELECT landmark_id FROM landmarks WHERE user_id=?", (user_id,)).fetchall()
            current_ids = [row['landmark_id'] for row in lms]
            
            if not current_ids: return False
            
            # Count how many of THESE SPECIFIC IDs (1-20) have morning logs today
            placeholders = ','.join(['?'] * len(current_ids))
            query = f"SELECT COUNT(DISTINCT landmark_id) FROM logs WHERE user_id=? AND date=? AND category='morning' AND landmark_id IN ({placeholders})"
            done_count = conn.execute(query, [user_id, today] + current_ids).fetchone()[0]
            return done_count >= len(current_ids)
            
        elif routine_type == 'evening':
            count = conn.execute("SELECT COUNT(*) FROM logs WHERE user_id=? AND date=? AND category='evening'", (user_id, today)).fetchone()[0]
            return count > 0
    finally:
        conn.close()
    return False

def create_entry(user_id, landmark_id, file_paths, status, weather, category='adhoc', transcription=""):
    entry_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    date_str = datetime.now().strftime("%Y-%m-%d")
    weather_json = json.dumps(weather)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO logs (id, user_id, landmark_id, category, status, timestamp, date, weather_json, transcription)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (entry_id, user_id, landmark_id, category, status, timestamp, date_str, weather_json, transcription))
    
    for key, path in file_paths.items():
        c.execute("INSERT INTO media (log_id, file_path, file_type) VALUES (?, ?, ?)", (entry_id, path, key))
    
    conn.commit()
    conn.close()
    trigger_sync()
    return entry_id

def update_transcription(entry_id, text):
    conn = get_db()
    conn.execute("UPDATE logs SET transcription = ? WHERE id = ?", (text, entry_id))
    conn.commit()
    conn.close()
    trigger_sync()

def log_ai_interaction(user_id, prompt, response, model_used, log_id=None):
    timestamp = datetime.now().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO ai_interactions (user_id, log_id, prompt, response, model_used, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                 (user_id, log_id, prompt, response, model_used, timestamp))
    conn.commit()
    inserted_id = cursor.lastrowid
    conn.close()
    return inserted_id

def update_ai_feedback(interaction_id, status, note=None):
    conn = get_db()
    if note is not None:
        conn.execute("UPDATE ai_interactions SET feedback_status=?, feedback_note=? WHERE id=?", (status, note, interaction_id))
    else:
        conn.execute("UPDATE ai_interactions SET feedback_status=? WHERE id=?", (status, interaction_id))
    conn.commit()
    conn.close()

def get_entries_for_date(user_id, date_str):
    conn = get_db()
    # Join on composite key: user_id AND landmark_id
    query = """
        SELECT l.*, lm.label as landmark_label 
        FROM logs l
        LEFT JOIN landmarks lm ON l.user_id = lm.user_id AND l.landmark_id = lm.landmark_id
        WHERE l.user_id=? AND l.date=?
    """
    logs = conn.execute(query, (user_id, date_str)).fetchall()
    
    result = []
    for log in logs:
        media = conn.execute("SELECT file_type, file_path FROM media WHERE log_id=?", (log['id'],)).fetchall()
        files = {m['file_type']: m['file_path'] for m in media}
        
        data = dict(log)
        data['files'] = files
        data['landmark_name'] = log['landmark_label']
        data['weather'] = json.loads(log['weather_json']) if log['weather_json'] else {}
        result.append(LogEntry(data))
        
    conn.close()
    return result

# Initialize
init_db()