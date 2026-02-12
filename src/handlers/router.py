import datetime
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from utils.menus import BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD, MAIN_MENU_KBD
import database as db

async def route_intent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
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
    
    await update.message.reply_text("🤷‍♂️ Unknown command. Use the menu.", parse_mode='Markdown')
    return None

async def proactive_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user_profile(user_id)
    
    if not user:
        from handlers.onboarding import start_onboarding
        await start_onboarding(update, context)
        return

    # Accurate Checks
    morning_done = db.is_routine_done(user_id, 'morning')
    evening_done = db.is_routine_done(user_id, 'evening')
    pending_count = len(db.get_pending_landmark_ids(user_id))
    
    now_hour = datetime.datetime.now().hour
    greeting = f"👋 **Hi {user.full_name}!**"
    
    if 6 <= now_hour < 14 and not morning_done:
        suggestion = f"☀️ Your Morning Check-in for **{pending_count} spots** is pending."
    elif now_hour >= 16 and not evening_done:
        suggestion = "🌙 Ready to record your **Evening Summary**?"
        if not morning_done:
            suggestion = f"🚜 Busy day? You have **{pending_count} morning spots** + Evening Summary pending."
    elif morning_done and evening_done:
        suggestion = "✅ All tasks complete. Great job today!"
    else:
        suggestion = "👇 Select an action below."

    await update.message.reply_text(f"{greeting}\n\n{suggestion}", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')