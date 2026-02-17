def build_agronomist_prompt(user_query, weather_info=None, location=None, prev_context=None):
    """
    Constructs a context-aware prompt for the AI Agronomist.
    """
    # 1. Format Weather Context
    w_text = "Data Unavailable"
    if weather_info and isinstance(weather_info, dict):
        temp = weather_info.get('temp', 'N/A')
        hum = weather_info.get('humidity', 'N/A')
        wind = weather_info.get('wind_speed', 'N/A')
        w_text = f"{temp}°C, {hum}% Humidity, Wind {wind} m/s"
    
    # 2. Format Location
    loc_text = "Unknown"
    if location and isinstance(location, dict):
        loc_text = f"{location.get('lat', 0):.4f}, {location.get('lon', 0):.4f}"

    # 3. The Core Persona
    prompt = f"""
ROLE: Senior Agricultural Consultant & Agronomist
LOCATION: {loc_text}
WEATHER: {w_text}
PREVIOUS CONTEXT: {prev_context if prev_context else "None"}

USER QUERY: {user_query}

INSTRUCTIONS:
1. Give IMPORTANCE to USER QUERY, WEATHER and LOCATION .
2. FORMAT: Use Markdown(bold keys, bullet points) for readability on Telegram chat.
3. CRITICAL: Keep your response SHORT (under 150 words) to prevent system load.
""".strip()

    return prompt