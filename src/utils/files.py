import os
import shutil
import re
from datetime import datetime

MEDIA_ROOT = "data/media"

def sanitize(text):
    """Converts 'My Farm 1' to 'My_Farm_1' for safe filenames."""
    if not text: return "unknown_farm"
    return re.sub(r'[^a-zA-Z0-9]', '_', str(text))

def save_telegram_file(file_obj, user_id, farm_name, landmark_id, file_type):
    """
    Saves file as: data/media/{user_id}/{date}/{user_id}_{farm}_{landmark}_{type}.ext
    """
    # 1. Determine Extension
    if any(x in file_type for x in ["voice", "summary", "note"]):
        ext = "ogg"
    else:
        ext = "jpg"

    # 2. Create Directory
    date_str = datetime.now().strftime("%Y-%m-%d")
    directory = os.path.join(MEDIA_ROOT, str(user_id), date_str)
    if not os.path.exists(directory):
        os.makedirs(directory)
        
    # 3. Construct Filename (Prefix with User ID + Farm Name)
    safe_farm = sanitize(farm_name)
    filename = f"{user_id}_{safe_farm}_{landmark_id}_{file_type}.{ext}"
    final_path = os.path.join(directory, filename)
    
    # 4. Write File
    file_obj.seek(0)
    with open(final_path, 'wb') as destination:
        shutil.copyfileobj(file_obj, destination)
    
    return final_path