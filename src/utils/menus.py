from telegram import ReplyKeyboardMarkup

# --- MENU TEXT CONSTANTS ---
BTN_MORNING = "📸 Start Morning Check-in"
BTN_EVENING = "🎙 Record Evening Summary"
BTN_ADHOC = "📝 Quick Ad-Hoc Note"
BTN_HISTORY = "📊 View History"
BTN_DASHBOARD = "👤 Dashboard"
BTN_AI = "🤖 Ask AI"

# --- KEYBOARDS ---
MAIN_MENU_KBD = ReplyKeyboardMarkup([
    [BTN_MORNING],
    [BTN_EVENING],
    [BTN_ADHOC, BTN_AI],
    [BTN_HISTORY, BTN_DASHBOARD]
], resize_keyboard=True)

MENU_BUTTONS = [BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_AI, BTN_HISTORY, BTN_DASHBOARD]