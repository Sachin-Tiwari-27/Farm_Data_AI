import os
import shutil
from datetime import datetime

MEDIA_ROOT = "data/media"

def save_telegram_file(file_obj, user_id, landmark_id, file_type):
    """
    Saves a file to: data/media/{user_id}/{date}/{landmark_id}_{type}.jpg
    """
    # 1. Create the Directory
    date_str = datetime.now().strftime("%Y-%m-%d")
    directory = os.path.join(MEDIA_ROOT, str(user_id), date_str)
    
    if not os.path.exists(directory):
        os.makedirs(directory)
        
    # 2. Define the Filename
    filename = f"{landmark_id}_{file_type}.jpg"
    final_path = os.path.join(directory, filename)
    
    # 3. WRITE THE FILE (This was missing!)
    # We rewind the file_obj to the beginning just in case
    file_obj.seek(0)
    
    with open(final_path, 'wb') as destination:
        shutil.copyfileobj(file_obj, destination)
    
    # Return the relative path for the DB, or absolute if you prefer
    return final_path