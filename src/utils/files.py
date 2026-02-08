import os
import shutil
from datetime import datetime

MEDIA_ROOT = "data/media"

def save_telegram_file(file_obj, user_id, landmark_id, file_type):
    """
    Saves a file to: data/media/{user_id}/{date}/{landmark_id}_{type}.ext
    """
    # 1. Determine Extension
    if "voice" in file_type or "summary" in file_type:
        ext = "ogg"
    else:
        ext = "jpg"

    # 2. Create the Directory
    date_str = datetime.now().strftime("%Y-%m-%d")
    directory = os.path.join(MEDIA_ROOT, str(user_id), date_str)
    
    if not os.path.exists(directory):
        os.makedirs(directory)
        
    # 3. Define the Filename
    filename = f"{landmark_id}_{file_type}.{ext}"
    final_path = os.path.join(directory, filename)
    
    # 4. WRITE THE FILE
    file_obj.seek(0)
    with open(final_path, 'wb') as destination:
        shutil.copyfileobj(file_obj, destination)
    
    return final_path