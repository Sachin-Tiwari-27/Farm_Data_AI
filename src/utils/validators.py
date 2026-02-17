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
    elif is_evening and hour < 12:
        # Smart Context: If no am/pm given but we're in evening flow
        hour += 12

    # FINAL RANGE CHECK (User Request: Morning 0-11:59, Evening 12-23:59)
    if is_evening:
        if hour < 12: return None # Must be 12:00 or later
    else:
        if hour >= 12: return None # Must be before 12:00
            
    return f"{hour:02d}:{minute:02d}"

def validate_landmark_count(text):
    """Ensures input is a number between 1 and 20."""
    if not text.isdigit():
        return None
    val = int(text)
    if 1 <= val <= 20:
        return val
    return None