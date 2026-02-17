from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes
from utils.menus import BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD, BTN_AI

async def route_intent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Checks if message is a menu command and routes to the appropriate handler.
    This allows seamless switching between conversation handlers.
    """
    if not update.message or not update.message.text:
        return None
        
    text = update.message.text
    
    # Check if it's a menu button
    if text not in [BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD, BTN_AI]:
        return None  # Not a menu button, let the current handler deal with it
    
    # Clear state for clean switch
    context.user_data.clear()
    
    # Import here to avoid circular imports
    from handlers.collection import start_collection, start_evening_flow
    from handlers.adhoc import start_adhoc_menu
    from handlers.history import view_history
    from handlers.dashboard import view_dashboard
    
    # Route to the appropriate handler
    if text == BTN_MORNING:
        await start_collection(update, context)
    elif text == BTN_EVENING:
        await start_evening_flow(update, context)
    elif text == BTN_ADHOC:
        await start_adhoc_menu(update, context)
    elif text == BTN_HISTORY:
        await view_history(update, context)
    elif text == BTN_DASHBOARD:
        await view_dashboard(update, context)
    elif text == BTN_AI:
        from handlers.ai_chat import start_ai_chat
        await start_ai_chat(update, context)
    
    # Always return END to exit current conversation
    return ConversationHandler.END