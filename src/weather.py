import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("AGRO_API_KEY")
BASE_URL = "https://api.agromonitoring.com/agro/1.0/weather"

def k_to_c(kelvin):
    return round(kelvin - 273.15, 2)

def get_weather_data(lat, lon):
    try:
        # Current Weather
        curr_res = requests.get(f"{BASE_URL}?lat={lat}&lon={lon}&appid={API_KEY}")
        curr_res.raise_for_status()
        c = curr_res.json()

        # Forecast
        fore_res = requests.get(f"{BASE_URL}/forecast?lat={lat}&lon={lon}&appid={API_KEY}")
        fore_res.raise_for_status()
        f_list = fore_res.json()

        # Extracting based on your example structure
        data = {
            "temp": k_to_c(c['main']['temp']),
            "temp_min": k_to_c(c['main']['temp_min']),
            "temp_max": k_to_c(c['main']['temp_max']),
            "pressure": c['main']['pressure'],
            "humidity": c['main']['humidity'],
            "wind_speed": c['wind'].get('speed', 0),
            "wind_deg": c['wind'].get('deg', 0),
            "desc": c['weather'][0]['description'],
            "forecast_temp": k_to_c(f_list[0]['main']['temp']) if f_list else None
        }
        
        # String for AI Prompt
        data['display_str'] = (
            f"Current: {data['temp']}°C ({data['desc'].capitalize()}). "
            f"Humidity: {data['humidity']}%, Wind: {data['wind_speed']}m/s at {data['wind_deg']}°. "
            f"Next forecast: {data['forecast_temp']}°C."
        )
        
        return data
    except Exception as e:
        logging.error(f"Weather Fetch Error: {e}")
        return None