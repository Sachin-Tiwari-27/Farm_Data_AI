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
SQL_FILE = os.path.join(DB_DIR, "farm.db")  # The Source of Truth
JSON_USERS = os.path.join(DB_DIR, "users.json") # The Shadow Mirror
JSON_LOGS = os.path.join(DB_DIR, "logs.json")   # The Shadow Mirror

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

# --- DATA CLASSES (Kept for compatibility) ---
class Landmark:
    def __init__(self, data):
        self.id = data.get('id')
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
        # Landmarks are passed as a list of dicts or objects
        lm_data = data.get('landmarks', [])
        self.landmarks = [Landmark(lm) if isinstance(lm, dict) else lm for lm in lm_data]

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
        self.landmark_name = data.get('landmark_name', f"Spot {self.landmark_id}")

# --- DATABASE CORE ---
def get_db():
    conn = sqlite3.connect(SQL_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates the SQLite tables if they don't exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    conn = get_db()
    c = conn.cursor()
    
    # 1. Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT, farm TEXT,
        lat REAL, lon REAL,
        p_time TEXT, v_time TEXT
    )''')
    
    # 2. Landmarks Table
    c.execute('''CREATE TABLE IF NOT EXISTS landmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        label TEXT, env TEXT, medium TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # 3. Logs Table (The Event)
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        landmark_id INTEGER,
        category TEXT,  -- 'morning', 'evening', 'adhoc'
        status TEXT,
        timestamp TEXT,
        date TEXT,      -- YYYY-MM-DD for fast indexing
        weather_json TEXT,
        transcription TEXT
    )''')
    
    # 4. Media Table (The Evidence)
    c.execute('''CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_id TEXT,
        file_path TEXT,
        file_type TEXT, -- 'wide', 'close', 'soil', 'voice', 'summary'
        FOREIGN KEY(log_id) REFERENCES logs(id)
    )''')
    
    conn.commit()
    conn.close()
    
    # Trigger initial sync to create empty JSONs if missing
    if not os.path.exists(JSON_USERS) or not os.path.exists(JSON_LOGS):
        trigger_sync()

# --- THE BACKGROUND WORKER (SHADOW SYNC) ---
def sync_to_json_shadow():
    """ Reads SQLite -> Overwrites JSON Files. Runs in background. """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 1. Sync Users
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
            
        # 2. Sync Logs
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
    user_data['landmarks'] = [dict(l) for l in lms]
    return User(user_data)

def save_user_profile(user_data):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        INSERT OR REPLACE INTO users (id, name, farm, lat, lon, p_time, v_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_data['id'], user_data['name'], user_data['farm'],
        user_data['lat'], user_data['lon'],
        user_data['p_time'], user_data['v_time']
    ))
    
    c.execute("DELETE FROM landmarks WHERE user_id=?", (user_data['id'],))
    for lm in user_data.get('landmarks', []):
        if hasattr(lm, 'to_dict'): lm = lm.to_dict()
        c.execute("""
            INSERT INTO landmarks (user_id, label, env, medium)
            VALUES (?, ?, ?, ?)
        """, (user_data['id'], lm['label'], lm['env'], lm['medium']))
        
    conn.commit()
    conn.close()
    trigger_sync()

def get_user_landmarks(user_id):
    user = get_user_profile(user_id)
    return user.landmarks if user else []

def get_landmark_by_id(user_id, landmark_id):
    user = get_user_profile(user_id)
    if not user: return None
    for lm in user.landmarks:
        if lm.id == int(landmark_id): return lm
    return None

# --- LOGGING FUNCTIONS ---
def create_entry(user_id, landmark_id, file_paths, status, weather, category='adhoc', transcription=""):
    """ Core function to save a log and map its media. """
    entry_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    date_str = datetime.now().strftime("%Y-%m-%d")
    weather_json = json.dumps(weather)
    
    conn = get_db()
    c = conn.cursor()
    
    # 1. Insert Log
    c.execute("""
        INSERT INTO logs (id, user_id, landmark_id, category, status, timestamp, date, weather_json, transcription)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (entry_id, user_id, landmark_id, category, status, timestamp, date_str, weather_json, transcription))
    
    # 2. Insert Media
    for key, path in file_paths.items():
        c.execute("INSERT INTO media (log_id, file_path, file_type) VALUES (?, ?, ?)", 
                  (entry_id, path, key))
        
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

# --- REPORTING & LOGIC ---
def get_pending_landmark_ids(user_id):
    """ Returns list of landmark IDs that have NOT been checked this morning. """
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    all_lms = conn.execute("SELECT id FROM landmarks WHERE user_id=?", (user_id,)).fetchall()
    all_ids = set(row['id'] for row in all_lms)
    
    done_lms = conn.execute("""
        SELECT landmark_id FROM logs 
        WHERE user_id=? AND date=? AND category='morning'
    """, (user_id, today)).fetchall()
    done_ids = set(row['landmark_id'] for row in done_lms)
    
    conn.close()
    return sorted(list(all_ids - done_ids))

def is_routine_done(user_id, routine_type):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if routine_type == 'evening':
        count = conn.execute("""
            SELECT COUNT(*) FROM logs 
            WHERE user_id=? AND date=? AND category='evening'
        """, (user_id, today)).fetchone()[0]
        conn.close()
        return count > 0
        
    elif routine_type == 'morning':
        conn.close()
        return len(get_pending_landmark_ids(user_id)) == 0
        
    return False

# --- HISTORY FUNCTIONS ---

def get_entries_for_date(user_id, date_str):
    conn = get_db()
    # Updated query to JOIN with landmarks to get the Label (Name)
    query = """
        SELECT l.*, lm.label as landmark_label 
        FROM logs l
        LEFT JOIN landmarks lm ON l.landmark_id = lm.id
        WHERE l.user_id=? AND l.date=?
    """
    logs = conn.execute(query, (user_id, date_str)).fetchall()
    
    result = []
    for log in logs:
        media = conn.execute("SELECT file_type, file_path FROM media WHERE log_id=?", (log['id'],)).fetchall()
        files = {m['file_type']: m['file_path'] for m in media}
        
        data = dict(log)
        data['files'] = files
        # Map the joined label to the expected object attribute
        data['landmark_name'] = log['landmark_label'] if log['landmark_label'] else "General/Evening"
        data['weather'] = json.loads(log['weather_json']) if log['weather_json'] else {}
        result.append(LogEntry(data))
        
    conn.close()
    return result

# Initialize on import
init_db()