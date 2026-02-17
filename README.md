# Farm AI Assistant 🌾

A professional, AI-powered Telegram bot designed to help farmers automate daily logs, track crop health, and maintain a detailed farm diary. Featuring a premium menu-driven interface, automated AI transcriptions, smart generative AI advice, and localized weather integration.

## Features ✨

### 🤖 AI Agronomist

- **Ask AI** (🤖): Get instant expert advice on crop issues.
  - **Visual Diagnosis**: Send photos of pests, diseases, or deficiencies for AI analysis.
  - **Context-Aware**: The AI considers your farm's location and current weather data.
  - **Feedback Loop**: Rate the advice (👍/👎) to improve future responses.

### 🌿 Daily Routine

- **Morning Check-in** (📸): A guided 3-photo workflow for each tracked landmark:
  1. **Wide Shot** (Overall view)
  2. **Close-up** (Plant health)
  3. **Soil/Base** (Moisture/Environment)
  - Followed by **Status Assessment** (Healthy, Issue, Unsure) and optional **Voice Note**.
- **Evening Summary** (🎙): Quick voice recording for daily farm-level observations. No tagging required.
- **Smart Gatekeeper**: Automatically detects unregistered users and prompts for setup.

### 📸 Effortless Logging & AI

- **Smart Ad-hoc Capture**: Send any **Photo** or **Voice Note** instantly.
  - **"Add More" Feedback**: Group multiple photos and notes together with real-time counting.
  - **Tagging**: Link ad-hoc entries to specific landmarks or save as general notes.
- **Automated Transcription**: Background voice-to-text processing for all voice notes using `faster-whisper`.

### ⚙️ Farm Management & Insights

- **Enhanced History** (📊): Browse logs by date with intuitive media group views. See photos, voice transcripts, and weather conditions for any previous entry.
- **Interactive Dashboard** (👤): Manage your farm profile and customize landmarks (Add/Rename/Delete) on the fly.
- **Weather Integration**: Automatically captures precise weather data (temp, humidity, conditions) during every entry.
- **Persistent Menu**: A robust, custom keyboard interface for seamless one-tap navigation.

## Technical Stack 🛠️

- **Core**: Python 3.12+
- **Bot Framework**: `python-telegram-bot` (v22.6)
- **Database**: Hybrid **SQLite** (Source of Truth) + **JSON Shadow Mirror** (Background Sync).
- **Speech AI**: `faster-whisper` (Int8 quantized model for efficient CPU inference).
- **Generative AI**: `google-genai` (Gemini 2.5 Flash for vision and reasoning).
- **APIs**: Agromonitoring (Weather), OpenStreetMap (Reverse Geocoding).

## Installation 🚀

1. **Clone the repository:**

   ```bash
   git clone https://github.com/Sachin-Tiwari-27/Farm_AI_Assistant.git
   cd Farm_AI_Assistant
   ```

2. **Set up Virtual Environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   _(Note: You may need to install ffmpeg on your system for audio processing)_

4. **Configuration:**
   Create a `.env` file in the root directory:
   ```env
   TELEGRAM_TOKEN=your_telegram_bot_token_here
   GEMINI_API_KEY=your_google_gemini_api_key_here
   # Optional: Weather API Key if integrated
   # AGRO_API_KEY=your_agromonitoring_api_key_here
   ```

## Usage 💡

1. **Start the Bot:**

   ```bash
   python src/main.py
   ```

2. **Core Workflow:**
   - Tap `/start` to begin the guided farm setup.
   - Use the **Main Menu Keyboard** for all interactions:
     - 📸 **Start Morning Check-in**
     - 🎙 **Record Evening Summary**
     - 🤖 **Ask AI Expert**
     - 📝 **Quick Ad-Hoc Note**
     - 📊 **View History**
     - 👤 **Dashboard**

## Project Structure 📂

- `src/`
  - `main.py`: Entry point, global router, and core event loop.
  - `database.py`: Core logic for SQLite + JSON sync storage.
  - `handlers/`: Module-based conversation flows.
    - `ai_chat.py`: Logic for AI Agronomist interactions.
    - `collection.py`: Morning/Evening routines.
    - `adhoc.py`: Quick entry handling.
    - `history.py`: Log browsing and reporting.
  - `utils/`: UI menus, file management, weather, and AI helpers.
    - `ai_agent/`: Prompts and API client for Google GenAI.
- `data/`
  - `db/`: Database files (`farm.db`, `users.json`, `logs.json`).
  - `media/`: Organized storage for photos and voice recordings.
- `requirements.txt`: Project dependencies list.
- `pyproject.toml`: Modern Python project metadata.

## License 📄

[MIT License](LICENSE)
