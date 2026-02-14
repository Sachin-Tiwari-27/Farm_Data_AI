# Farm AI Assistant 🌾

A professional, AI-powered Telegram bot designed to help farmers automate daily logs, track crop health, and maintain a detailed farm diary. Featuring a premium menu-driven interface, automated AI transcriptions, and localized weather integration.

## Features ✨

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
- **Automated Transcription**: Background voice-to-text processing for all voice notes.

### ⚙️ Farm Management & Insights

- **Enhanced History** (📊): Browse logs by date with intuitive media group views. See photos, voice transcripts, and weather conditions for any previous entry.
- **Interactive Dashboard** (👤): Manage your farm profile and customize landmarks (Add/Rename/Delete) on the fly.
- **Weather Integration**: Automatically captures precise weather data (temp, humidity, conditions) during every entry using the Agromonitoring API.
- **Persistent Menu**: A robust, custom keyboard interface for seamless one-tap navigation.

## Technical Stack �️

- **Core**: Python 3.12+
- **Bot Framework**: `python-telegram-bot` (v22.6)
- **Database**: Hybrid **SQLite** (Source of Truth) + **JSON Shadow Mirror** (Background Sync).
- **AI/ML**: `faster-whisper` (Base model with int8 quantization).
- **APIs**: Agromonitoring (Weather), OpenStreetMap (Reverse Geocoding logic).

## Installation 🚀

1. **Clone the repository:**

   ```bash
   git clone <repository_url>
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

4. **Configuration:**
   Create a `.env` file in the root directory:
   ```env
   TELEGRAM_TOKEN=your_telegram_bot_token_here
   AGRO_API_KEY=your_agromonitoring_api_key_here
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
     - 📝 **Quick Ad-Hoc Note**
     - 📊 **View History**
     - 👤 **Dashboard**

## Project Structure 📂

- `src/`
  - `main.py`: Entry point, global router, and core event loop.
  - `database.py`: Core logic for SQLite + JSON sync storage.
  - `handlers/`: Module-based conversation flows (Onboarding, Collection, History, etc.).
  - `utils/`: UI menus, file management, weather, and AI transcription helpers.
- `data/`
  - `db/`: Database files (`farm.db`, `users.json`, `logs.json`).
  - `media/`: Organized storage for photos and voice recordings.
- `requirements.txt`: Project dependencies list.
- `pyproject.toml`: Project metadata and dependency management.

## License 📄

[MIT License](LICENSE)
