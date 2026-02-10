import json
import os
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
    """Helper class to allow object-style access (entry.status) in main.py"""
    def __init__(self, data):
        self.user_id = data.get('user_id')
        self.landmark_id = data.get('landmark_id')
        self.status = data.get('status')
        self.timestamp = datetime.fromisoformat(data.get('timestamp'))
        self.files = data.get('files', {})
        self.has_note = data.get('has_note', False)
        
        # Helper attributes for easier access
        self.img_wide = self.files.get('wide') or self.files.get('adhoc_photo')
        self.img_close = self.files.get('close')
        self.img_soil = self.files.get('soil')
        self.voice_path = self.files.get('voice_path') or self.files.get('adhoc_voice')

        # Construct a mock Landmark object for display
        label = data.get('landmark_name', f"Spot {self.landmark_id}")
        if self.landmark_id == 0: label = "Evening Summary"
        if self.landmark_id == 99: label = "Ad-Hoc"
        self.landmark = Landmark(self.landmark_id, label, self.status)

# --- INITIALIZATION ---
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
    """Returns only the fixed spots (1, 2, 3...) for routine checking."""
    user = get_user_profile(user_id)
    if not user: return []
    return [Landmark(i, f"Spot {i}") for i in range(1, user.landmark_count + 1)]

def get_user_landmarks(user_id):
    """Returns routine landmarks with their latest status attached."""
    landmarks = get_routine_landmarks(user_id)
    # Get today's logs to update status
    today = datetime.now().strftime("%Y-%m-%d")
    logs = get_logs_by_date(user_id, today)
    
    status_map = {l['landmark_id']: l['status'] for l in logs}
    
    for lm in landmarks:
        lm.last_status = status_map.get(lm.id, "Pending")
    return landmarks

def get_or_create_adhoc_landmark(user_id):
    return 99

# --- LOGGING FUNCTIONS (WRITE) ---
def create_entry(user_id, landmark_id, file_paths, status, weather):
    # Determine Landmark Name for easier reading
    name = f"Spot {landmark_id}"
    if landmark_id == 0: name = "Evening Summary"
    if landmark_id == 99: name = "Ad-Hoc"

    entry = {
        "user_id": user_id,
        "landmark_id": landmark_id,
        "landmark_name": name,
        "files": file_paths,
        "status": status,
        "weather": weather,
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "has_note": True if file_paths.get('voice_path') or file_paths.get('adhoc_voice') else False
    }
    
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    logs.append(entry)
    with open(LOGS_FILE, 'w') as f:
        json.dump(logs, f, indent=4)

def save_evening_summary(user_id, voice_path):
    """Specific wrapper for evening summary to ensure consistency."""
    create_entry(user_id, 0, {"voice_path": voice_path}, "Summary", {})

# --- HISTORY FUNCTIONS (READ) ---
def get_logs_by_date(user_id, date_str):
    """Returns raw list of dicts for a specific date (Used by Routine Check)."""
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    return [l for l in logs if str(l.get('user_id')) == str(user_id) and l.get('date') == date_str]

def get_entries_by_date_range(user_id, start_date, end_date):
    """Returns a Dictionary grouped by Date (Used by History Menu)."""
    with open(LOGS_FILE, 'r') as f:
        logs = json.load(f)
    
    # Filter logs
    filtered = []
    for l in logs:
        if str(l.get('user_id')) != str(user_id): continue
        l_date = datetime.strptime(l['date'], '%Y-%m-%d').date()
        if start_date <= l_date <= end_date:
            filtered.append(l)
    
    # Group by Date
    grouped = {}
    for l in filtered:
        d = l['date']
        if d not in grouped:
            grouped[d] = {'entries': [], 'has_evening_summary': False}
        grouped[d]['entries'].append(l)
        if l['landmark_id'] == 0:
            grouped[d]['has_evening_summary'] = True
            
    # Sort dates descending (newest first)
    return dict(sorted(grouped.items(), reverse=True))

def get_entries_for_date(user_id, date_str):
    """Returns list of LogEntry Objects (Used by Detailed View)."""
    raw_logs = get_logs_by_date(user_id, date_str)
    return [LogEntry(l) for l in raw_logs]

