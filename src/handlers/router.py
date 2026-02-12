from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from utils.menus import BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD

async def route_intent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Silent Switcher:
    1. Detects the menu click.
    2. Manually runs the target start function (showing the new UI).
    3. Returns END to kill the old conversation.
    """
    text = update.message.text
    
    # Lazy imports to avoid circular dependency issues at module level
    if text == BTN_MORNING:
        from handlers.collection import start_collection
        await start_collection(update, context)
        return ConversationHandler.END
        
    elif text == BTN_EVENING:
        from handlers.collection import start_evening_flow
        await start_evening_flow(update, context)
        return ConversationHandler.END
        
    elif text == BTN_ADHOC:
        from handlers.adhoc import start_adhoc_menu
        await start_adhoc_menu(update, context)
        return ConversationHandler.END

    elif text == BTN_HISTORY:
        from handlers.history import view_history
        await view_history(update, context)
        return ConversationHandler.END

    elif text == BTN_DASHBOARD:
        from handlers.dashboard import view_dashboard
        await view_dashboard(update, context)
        return ConversationHandler.END
    
    # Generic "Unknown Command" fallback (if not a menu button)
    await update.message.reply_text(
        "🤷‍♂️ **I didn't catch that.**\n"
        "Please use the menu buttons or tap /cancel.",
        parse_mode='Markdown'
    )
    return None # Keep state active