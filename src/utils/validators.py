import re

def parse_time(input_str, is_evening=False):
    """
    Smart parses time.
    '7' -> 07:00 (if morning)
    '6' -> 18:00 (if evening context)
    '17:00' -> 17:00
    """
    if not input_str: return None
    s = input_str.strip().lower().replace('.', ':')
    
    # Check for simple number (e.g., "7" or "6")
    if s.isdigit():
        hour = int(s)
        if is_evening and hour < 12:
            hour += 12  # Convert 6 -> 18
        return f"{hour:02d}:00"

    # Regex for HH:MM or HH:MM am/pm
    match = re.search(r'(\d{1,2})(:(\d{2}))?\s*(am|pm)?', s)
    if not match:
        return None
    
    hour, _, minute, meridian = match.groups()
    hour = int(hour)
    minute = int(minute) if minute else 0
    
    if hour > 23: return None
    if minute > 59: return None
    
    # Handle explicit AM/PM
    if meridian:
        if meridian == 'pm' and hour != 12:
            hour += 12
        elif meridian == 'am' and hour == 12:
            hour = 0
    # Handle inferred PM (if no meridian provided, e.g. "6:30" in evening section)
    elif is_evening and hour < 12:
        hour += 12
        
    return f"{hour:02d}:{minute:02d}"