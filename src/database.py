import json
import os
import uuid
from datetime import datetime

# Define paths
DB_DIR = "data/db"
MEDIA_DIR = "data/media"
DB_FILE = os.path.join(DB_DIR, "users.json")
LOGS_FILE = os.path.join(DB_DIR, "logs.json")

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
        self.id = data.get('id')
        self.label = data.get('label', f"Spot {self.id}")
        self.env = data.get('env', ENV_FIELD)
        self.medium = data.get('medium', MED_SOIL)
        self.last_status = data.get('last_status', "Pending")

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "env": self.env,
            "medium": self.medium
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
        self.landmarks = [Landmark(lm) for lm in lm_data]

    def to_dict(self):
        return {
            "id": self.id, "name": self.full_name, "farm": self.farm_name,
            "lat": self.latitude, "lon": self.longitude,
            "p_time": self.photo_time, "v_time": self.voice_time,
            "landmarks": [l.to_dict() for l in self.landmarks]
        }

class LogEntry:
    def __init__(self, data):
        self.id = data.get('id')
        self.user_id = data.get('user_id')
        self.landmark_id = data.get('landmark_id')
        self.status = data.get('status')
        self.timestamp = datetime.fromisoformat(data.get('timestamp'))
        self.files = data.get('files', {})
        self.has_note = data.get('has_note', False)
        self.transcription = data.get('transcription', "")
        self.landmark_name = data.get('landmark_name', f"Spot {self.landmark_id}")
        self.photos = [v for k, v in self.files.items() if 'photo' in k or 'jpg' in v]
        self.voice_paths = [v for k, v in self.files.items() if 'voice' in k or 'ogg' in v]

# --- INIT ---
def init_db():
    """Defensive Initialization: Creates folders and empty JSONs if missing."""
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f: json.dump({}, f)
    
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'w') as f: json.dump([], f)

init_db()

# --- USER FUNCTIONS ---
def get_user_profile(user_id):
    try:
        with open(DB_FILE, 'r') as f:
            data = json.load(f)
        u_data = data.get(str(user_id))
        return User(u_data) if u_data else None
    except Exception:
        return None

def save_user_profile(user_data):
    try:
        with open(DB_FILE, 'r') as f:
            data = json.load(f)
    except: data = {}
    
    data[str(user_data['id'])] = user_data
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_user_landmarks(user_id):
    user = get_user_profile(user_id)
    return user.landmarks if user else []

def get_landmark_by_id(user_id, landmark_id):
    user = get_user_profile(user_id)
    if not user: return None
    for lm in user.landmarks:
        if lm.id == landmark_id: return lm
    return None

# --- LOGGING FUNCTIONS ---
def get_logs_by_date(user_id, date_str):
    try:
        with open(LOGS_FILE, 'r') as f: logs = json.load(f)
        return [l for l in logs if str(l.get('user_id')) == str(user_id) and l.get('date') == date_str]
    except: return []

def get_pending_landmark_ids(user_id):
    user = get_user_profile(user_id)
    if not user: return []
    today = datetime.now().strftime("%Y-%m-%d")
    logs = get_logs_by_date(user_id, today)
    logged_ids = set(l.get('landmark_id') for l in logs)
    all_ids = set(lm.id for lm in user.landmarks)
    return sorted(list(all_ids - logged_ids))

def is_routine_done(user_id, routine_type):
    if routine_type == 'evening':
        today = datetime.now().strftime("%Y-%m-%d")
        logs = get_logs_by_date(user_id, today)
        return any(l.get('landmark_id') == 0 for l in logs)
    if routine_type == 'morning':
        return len(get_pending_landmark_ids(user_id)) == 0
    return False

def create_entry(user_id, landmark_id, file_paths, status, weather, transcription=""):
    name = "Ad-Hoc"
    if landmark_id == 0: name = "Evening Summary"
    else:
        lm = get_landmark_by_id(user_id, landmark_id)
        if lm: name = lm.label

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "landmark_id": landmark_id,
        "landmark_name": name,
        "files": file_paths,
        "status": status,
        "weather": weather,
        "transcription": transcription,
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "has_note": any("voice" in k for k in file_paths.keys())
    }
    
    try:
        with open(LOGS_FILE, 'r') as f: logs = json.load(f)
    except: logs = []
    
    logs.append(entry)
    with open(LOGS_FILE, 'w') as f: json.dump(logs, f, indent=4)
    return entry['id']

def update_transcription(entry_id, text):
    try:
        with open(LOGS_FILE, 'r') as f: logs = json.load(f)
        for entry in logs:
            if entry.get('id') == entry_id:
                entry['transcription'] = text
                break
        with open(LOGS_FILE, 'w') as f: json.dump(logs, f, indent=4)
    except: pass

def get_entries_for_date(user_id, date_str):
    raw = get_logs_by_date(user_id, date_str)
    return [LogEntry(l) for l in raw]

def get_entries_by_date_range(user_id, start_date, end_date):
    try:
        with open(LOGS_FILE, 'r') as f: logs = json.load(f)
    except: return {}
    
    filtered = []
    for l in logs:
        if str(l.get('user_id')) != str(user_id): continue
        try:
            l_date = datetime.strptime(l['date'], '%Y-%m-%d').date()
            if start_date <= l_date <= end_date: filtered.append(l)
        except: pass
        
    grouped = {}
    for l in filtered:
        d = l['date']
        if d not in grouped: grouped[d] = {'entries': []}
        grouped[d]['entries'].append(l)
    return dict(sorted(grouped.items(), reverse=True))