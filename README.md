# Farm AI Assistant 🌾

A Telegram bot designed to be a digital assistant for farmers, automating daily check-ins, tracking crop health, and logging voice summaries.

## Features ✨

### 🌿 Daily Routine

- **Morning Check-in (`/collection`)**: Guided process to capture photos of specific landmarks (Wide shot, Close-up, Soil/Base).
- **Evening Summary (`/record`)**: Record a voice note to summarize the day's events.
- **Smart Scheduling**: Automatically schedules daily reminders based on your preferred times.
- **Timezone Aware**: Operates in your local timezone (Default: `Asia/Dubai`).

### 📸 Effortless Logging

- **Ad-hoc Captures**: Simply send a **Photo** or **Voice Note** to the bot at any time to save a quick snapshot or thought.
- **Landmark Tracking**: Monitor specific spots on your farm over time.
- **Status Logging**: Tag check-ins as Healthy, Issue/Pest, or Unsure.

### ⚙️ Profile Management (`/profile`)

- **Dashboard**: View your farm details and current schedule.
- **Edit on the Fly**: Update your Name or Daily Schedule directly from the dashboard.
- **Weather Integration**: Real-time weather updates during check-ins.

## Requirements 📋

- Python 3.8+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))

## Installation 🚀

1.  **Clone the repository:**

    ```bash
    git clone <repository_url>
    cd Farm_AI_Assistant
    ```

2.  **Set up Virtual Environment:**

    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**

    ```bash
    pip install -r requirement.txt
    ```

4.  **Configuration:**
    Create a `.env` file in the root directory:
    ```env
    TELEGRAM_TOKEN=your_telegram_bot_token_here
    ```

## Usage 💡

1.  **Start the Bot:**

    ```bash
    python src/main.py
    ```

2.  **Commands:**
    - `/start` - Register your farm and set up your profile.
    - `/collection` - Start the morning photo check-in.
    - `/record` - Record an evening voice summary.
    - `/profile` - View dashboard and edit settings.
    - `/cancel` - Stop the current action.

    **Debug Tools:**
    - `/jobs` - View upcoming scheduled reminders.
    - `/time` - Check the bot's current server time.

## Project Structure 📂

- `src/`
  - `main.py`: Core bot logic, scheduling, and conversation handlers.
  - `database.py`: SQLite database management (Users, Landmarks, Logs).
  - `weather.py`: Fetching weather data.
  - `utils/`: Helper functions for file management and validation.
- `data/`: Storage for photos, voice notes, and the database.
- `requirement.txt`: Project dependencies.

## License 📄

[MIT License](LICENSE)
