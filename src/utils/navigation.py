from telegram import Update
from telegram.ext import ConversationHandler
from utils.menus import BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD

async def check_global_intent(update: Update, context):
    """
    Checks if the user text is a menu command.
    Returns the command key if found, else None.
    """
    if not update.message or not update.message.text:
        return None
        
    text = update.message.text
    if text in [BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD]:
        # We found a command!
        # Clear state to ensure clean switch
        context.user_data.clear()
        return text
    return None