# Farm AI Assistant 🌾

A professional Telegram bot assistant for farmers, automating daily check-ins, tracking crop health, and logging voice summaries with a premium, menu-driven interface.

## Features ✨

### 🌿 Daily Routine

- **Morning Check-in** (📸): Guided 3-photo flow for specific landmarks:
  1. **Wide Shot** (Overall view)
  2. **Close-up** (Plant health)
  3. **Soil/Base** (Moisture/Environment)
  - Followed by **Status Assessment** (Healthy, Issue, Unsure) and optional **Voice Note**.
- **Evening Summary** (🎙): Quick voice recording for daily farm-level observations. No tagging required.
- **Smart Gatekeeper**: Automatically detects unregistered users and prompts for setup.

### 📸 Effortless Logging

- **Smart Ad-hoc Capture**: Send any **Photo** or **Voice Note** instantly.
  - **"Add More" Feedback**: Group multiple photos and notes together with real-time counting.
  - **Tagging**: Link ad-hoc entries to specific landmarks or save as general notes.
- **Automated Transcription**: Background voice-to-text processing for all voice notes.

### ⚙️ Farm Management

- **Interactive Dashboard**: View farm profile and manage landmarks (Add/Rename/Delete).
- **History & Reports**: Browse logs by date (Today, Yesterday, Last 7 Days, Last Month).
- **Weather Integration**: Dynamic weather data capture during every check-in.
- **Persistent Menu**: A robust custom keyboard that stays available for easy navigation.

## Requirements 📋

- Python 3.12+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Agromonitoring API Key

## Installation 🚀

1. **Clone the repository:**

   ```bash
   git clone <repository_url>
   cd Farm_AI_Assistant
   ```

2. **Set up Virtual Environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\\Scripts\\activate
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
   - Use `/start` for the first-time guided onboarding.
   - Interact via the **Main Menu Keyboard**:
     - 📸 **Start Morning Check-in**
     - 🎙 **Record Evening Summary**
     - 📝 **Quick Ad-Hoc Note**
     - 📊 **View History**
     - 👤 **Dashboard**

## Project Structure 📂

- `src/`
  - `main.py`: Entry point, global router, and core bot loop.
  - `database.py`: JSON-based data storage (`users.json`, `logs.json`).
  - `handlers/`: Module-based conversation flows (Onboarding, Collection, Ad-hoc, etc.).
  - `utils/`: UI menus, file management, weather, and transcription helpers.
- `data/`
  - `db/`: JSON database files.
  - `media/`: Organized storage for photos and voice notes (`/user/date/filename`).
- `requirements.txt`: Project dependencies.

## License 📄

[MIT License](LICENSE)
