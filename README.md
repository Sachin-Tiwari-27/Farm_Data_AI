# Farm AI Assistant

A Telegram bot designed to help farmers track their farm's status, log daily check-ins, and monitor crop health through photo documentation.

## Features

- **User Onboarding**: Easy setup to register your farm, location, and preferred schedules.
- **Morning Check-in**: Guided process to capture photos of specific landmarks on your farm (Wide shot, Close-up, Soil/Base).
- **Status Logging**: Log the status of your crops (Healthy, Issue/Pest, Unsure) after taking photos.
- **Weather Integration**: Automatically fetches and displays weather data for your farm's location.
- **Profile Management**: View and update your farm details and preferences.

## Prerequisites

- Python 3.8 or higher
- A Telegram Bot Token (obtained from [@BotFather](https://t.me/BotFather))

## Installation

1.  **Clone the repository:**

    ```bash
    git clone <repository_url>
    cd Farm_AI_Assistant
    ```

2.  **Create a virtual environment (optional but recommended):**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**

    ```bash
    pip install -r requirement.txt
    ```

4.  **Configuration:**
    Create a `.env` file in the root directory and add your Telegram Bot Token:
    ```env
    TELEGRAM_TOKEN=your_telegram_bot_token_here
    ```

## Usage

1.  **Run the bot:**

    ```bash
    python src/main.py
    ```

2.  **Start interacting:**
    Open Telegram and search for your bot.
    - `/start`: Begin the onboarding process or return to home.
    - `/collection`: Start the morning check-in to log photos and status.
    - `/profile`: View your current profile and farm details.
    - `/cancel`: Stop the current action.

## Project Structure

- `src/`: Source code for the bot.
  - `main.py`: Main entry point and bot logic.
  - `database.py`: Database interactions (User and Landmark management).
  - `weather.py`: Weather data fetching logic.
  - `utils/`: Utility functions.
- `data/`: Directory for storing media and other data.
- `requirement.txt`: Python dependencies.
