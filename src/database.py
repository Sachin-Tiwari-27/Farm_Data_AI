import json
import os
import uuid
from datetime import datetime

DB_FILE = "data/db/users.json"
LOGS_FILE = "data/db/logs.json"

# --- CONSTANTS: FARM ATTRIBUTES ---
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
        self.last_status = data.get('last_status', "Pending") # Populated dynamically later

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
        
        # NEW: Parse list of dictionaries into Landmark objects
        lm_data = data.get('landmarks', [])
        self.landmarks = [Landmark(lm) for lm in lm_data]

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
        
        # NEW: Environment snapshot
        self.landmark_context = data.get('landmark_context', {})
        self.landmark_name = data.get('landmark_name', f"Spot {self.landmark_id}")
        
        # Helpers
        self.img_wide = self.files.get('wide') or self.files.get('adhoc_photo')
        self.img_close = self.files.get('close')
        self.img_soil = self.files.get('soil')
        self.voice_path = self.files.get('voice_path') or self.files.get('adhoc_voice')

# --- INIT ---
def init_db():
    os.makedirs("data/db", exist_ok=True)
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f: json.dump({}, f)
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'w') as f: json.dump([], f)

init_db()

# --- USER FUNCTIONS ---
def get_user_profile(user_id):
    with open(DB_FILE, 'r') as f:
        data = json.load(f)
    u_data = data.get(str(user_id))
    return User(u_data) if u_data else None

def save_user_profile(user_data):
    """Expects user_data to have a 'landmarks' list of dicts"""
    with open(DB_FILE, 'r') as f:
        data = json.load(f)
    data[str(user_data['id'])] = user_data
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_all_users():
    with open(DB_FILE, 'r') as f:
        data = json.load(f)
    return [User(u) for u in data.values()]

# --- LANDMARK FUNCTIONS ---
def get_user_landmarks(user_id):
    """Returns rich Landmark objects with their latest status attached."""
    user = get_user_profile(user_id)
    if not user: return []
    
    landmarks = user.landmarks
    today = datetime.now().strftime("%Y-%m-%d")
    logs = get_logs_by_date(user_id, today)
    status_map = {l.get('landmark_id'): l.get('status') for l in logs}
    
    for lm in landmarks:
        lm.last_status = status_map.get(lm.id, "Pending")
    return landmarks

def get_landmark_by_id(user_id, landmark_id):
    user = get_user_profile(user_id)
    if not user: return None
    for lm in user.landmarks:
        if lm.id == landmark_id: return lm
    return None

# --- LOGGING FUNCTIONS ---
def create_entry(user_id, landmark_id, file_paths, status, weather, transcription=""):
    name = f"Spot {landmark_id}"
    context_snapshot = {}
    
    # 1. Look up rich details if it's a specific spot
    if landmark_id not in [0, 99]:
        lm = get_landmark_by_id(user_id, landmark_id)
        if lm:
            name = lm.label
            context_snapshot = {"env": lm.env, "medium": lm.medium}
            
    if landmark_id == 0: name = "Evening Summary"
    if landmark_id == 99: name = "Ad-Hoc"
    
    entry_id = str(uuid.uuid4())

    entry = {
        "id": entry_id,
        "user_id": user_id,
        "landmark_id": landmark_id,
        "landmark_name": name,
        "landmark_context": context_snapshot, # NEW: Save the snapshot
        "files": file_paths,
        "status": status,
        "weather": weather,
        "transcription": transcription,
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "has_note": True if file_paths.get('voice_path') or file_paths.get('adhoc_voice') else False
    }
    
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    logs.append(entry)
    with open(LOGS_FILE, 'w') as f:
        json.dump(logs, f, indent=4)
    
    return entry_id

def update_transcription(entry_id, text):
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    found = False
    for entry in logs:
        if entry.get('id') == entry_id:
            entry['transcription'] = text
            found = True
            break
    if found:
        with open(LOGS_FILE, 'w') as f:
            json.dump(logs, f, indent=4)

# --- HISTORY & CHECKS ---
def get_logs_by_date(user_id, date_str):
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    return [l for l in logs if str(l.get('user_id')) == str(user_id) and l.get('date') == date_str]

def is_routine_done(user_id, routine_type):
    today = datetime.now().strftime("%Y-%m-%d")
    logs = get_logs_by_date(user_id, today)
    logged_ids = [l.get('landmark_id') for l in logs]
    
    if routine_type == 'evening':
        return 0 in logged_ids 
        
    if routine_type == 'morning':
        landmarks = get_user_landmarks(user_id)
        morning_logs = [lid for lid in logged_ids if lid not in [0, 99]]
        return len(set(morning_logs)) >= len(landmarks)
    return False

def get_entries_by_date_range(user_id, start_date, end_date):
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    
    filtered = []
    for l in logs:
        if str(l.get('user_id')) != str(user_id): continue
        l_date = datetime.strptime(l['date'], '%Y-%m-%d').date()
        if start_date <= l_date <= end_date:
            filtered.append(l)
    
    grouped = {}
    for l in filtered:
        d = l['date']
        if d not in grouped: grouped[d] = {'entries': [], 'has_evening_summary': False}
        grouped[d]['entries'].append(l)
        if l['landmark_id'] == 0: grouped[d]['has_evening_summary'] = True
            
    return dict(sorted(grouped.items(), reverse=True))

def get_entries_for_date(user_id, date_str):
    raw_logs = get_logs_by_date(user_id, date_str)
    return [LogEntry(l) for l in raw_logs]