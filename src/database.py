import json
import os
import uuid
from datetime import datetime

DB_FILE = "data/db/users.json"
LOGS_FILE = "data/db/logs.json"

# --- DATA CLASSES ---
class User:
    def __init__(self, data):
        self.id = data.get('id')
        self.full_name = data.get('name')
        self.farm_name = data.get('farm')
        self.latitude = data.get('lat')
        self.longitude = data.get('lon')
        self.photo_time = data.get('p_time')
        self.voice_time = data.get('v_time')
        self.landmark_count = data.get('l_count')

class Landmark:
    def __init__(self, id, label, status="Pending"):
        self.id = id
        self.label = label
        self.last_status = status

class LogEntry:
    def __init__(self, data):
        self.user_id = data.get('user_id')
        self.landmark_id = data.get('landmark_id')
        self.status = data.get('status')
        self.timestamp = datetime.fromisoformat(data.get('timestamp'))
        self.files = data.get('files', {})
        self.has_note = data.get('has_note', False)
        self.transcription = data.get('transcription', "")
        
        # Helpers
        self.img_wide = self.files.get('wide') or self.files.get('adhoc_photo')
        self.img_close = self.files.get('close')
        self.img_soil = self.files.get('soil')
        self.voice_path = self.files.get('voice_path') or self.files.get('adhoc_voice')

        label = data.get('landmark_name', f"Spot {self.landmark_id}")
        if self.landmark_id == 0: label = "Evening Summary"
        if self.landmark_id == 99: label = "Ad-Hoc"
        self.landmark = Landmark(self.landmark_id, label, self.status)

# --- INIT ---
def init_db():
    os.makedirs("data", exist_ok=True)
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
def get_routine_landmarks(user_id):
    user = get_user_profile(user_id)
    if not user: return []
    return [Landmark(i, f"Spot {i}") for i in range(1, user.landmark_count + 1)]

def get_user_landmarks(user_id):
    landmarks = get_routine_landmarks(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    logs = get_logs_by_date(user_id, today)
    status_map = {l['landmark_id']: l['status'] for l in logs}
    for lm in landmarks:
        lm.last_status = status_map.get(lm.id, "Pending")
    return landmarks

# --- LOGGING FUNCTIONS ---
def create_entry(user_id, landmark_id, file_paths, status, weather, transcription=""):
    name = f"Spot {landmark_id}"
    if landmark_id == 0: name = "Evening Summary"
    if landmark_id == 99: name = "Ad-Hoc"

    entry_id = str(uuid.uuid4())

    entry = {
        "id": entry_id,
        "user_id": user_id,
        "landmark_id": landmark_id,
        "landmark_name": name,
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

# --- HISTORY & CHECKS ---
def get_logs_by_date(user_id, date_str):
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    return [l for l in logs if str(l.get('user_id')) == str(user_id) and l.get('date') == date_str]

def is_routine_done(user_id, routine_type):
    """
    Checks if Morning (all spots) or Evening (summary) is done today.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    logs = get_logs_by_date(user_id, today)
    logged_ids = [l.get('landmark_id') for l in logs]
    
    if routine_type == 'evening':
        return 0 in logged_ids 
        
    if routine_type == 'morning':
        landmarks = get_routine_landmarks(user_id)
        # Filter for Routine IDs (1..N) excluding 0 and 99
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

def update_transcription(entry_id, text):
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    
    for entry in logs:
        if entry.get('id') == entry_id:
            entry['transcription'] = text
            break
            
    with open(LOGS_FILE, 'w') as f:
        json.dump(logs, f, indent=4)