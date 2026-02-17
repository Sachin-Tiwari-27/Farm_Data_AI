import os
import logging
import pytz
from dotenv import load_dotenv

from telegram import BotCommand, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, Application, Defaults, 
    ContextTypes, MessageHandler, filters, ConversationHandler
)

import database as db
from utils.menus import MAIN_MENU_KBD, MENU_BUTTONS
# Import Scheduler Tools
from utils.scheduler import restore_scheduled_jobs, send_debug_alert, schedule_user_jobs

# Import Handlers
from handlers.onboarding import onboarding_handler, start_onboarding
from handlers.collection import collection_handler, evening_handler
from handlers.adhoc import adhoc_handler
from handlers.dashboard import dashboard_handler
from handlers.history import history_handler
from handlers.ai_chat import ai_handler, ai_feedback_handler

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DEBUG COMMANDS (JOBS) ---
async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/jobs - List ALL system alerts for debugging."""
    all_jobs = context.job_queue.jobs()
    user_id = update.effective_user.id
    
    if not all_jobs:
        await update.message.reply_text("📭 **No jobs scheduled in the system.**", parse_mode='Markdown')
        return

    msg = f"🕰 **Scheduled Tasks ({len(all_jobs)} total):**\n"
    for job in all_jobs:
        # Check if this job belongs to the current user
        is_mine = str(user_id) in job.name
        star = "🌟 " if is_mine else ""
        
        next_run = job.next_t.strftime('%Y-%m-%d %H:%M') if job.next_t else "Expired/None"
        msg += f"{star}`{job.name}`: {next_run} ({job.data})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/alert [seconds] - Test the scheduler."""
    try:
        delay = int(context.args[0]) if context.args else 10
    except ValueError:
        delay = 10
        
    user_id = update.effective_user.id
    # Schedule a one-off job
    context.job_queue.run_once(send_debug_alert, delay, user_id=user_id, data=f"Test fired after {delay}s")
    await update.message.reply_text(f"🚀 **Debug Alert** scheduled in {delay} seconds.", parse_mode='Markdown')

# --- GLOBAL CANCEL ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Universal reset."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ **Action Cancelled.**\nReturning to main menu.", 
        reply_markup=MAIN_MENU_KBD, 
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# --- GLOBAL ROUTER (The Fallback) ---
async def global_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # If the text is one of our main menu buttons, do nothing and let the 
    # specific handlers (collection, history, etc.) catch it.
    if text in MENU_BUTTONS:
        return 

    # Regular welcome message for non-menu text
    user = db.get_user_profile(update.effective_user.id)
    await update.message.reply_text(f"Welcome back to {user.farm_name}!", reply_markup=MAIN_MENU_KBD)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ **System Glitch.**\nI've reset your session.", 
                reply_markup=MAIN_MENU_KBD, 
                parse_mode='Markdown'
            )
            context.user_data.clear()
        except: pass

# --- STARTUP LOGIC ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home"),
        BotCommand("jobs", "🕰 Check Schedule"),
        BotCommand("profile", "👤 Dashboard"),
        BotCommand("cancel", "❌ Reset Bot")
    ])
    # Restore jobs from DB
    await restore_scheduled_jobs(application)

if __name__ == '__main__':
    db.init_db() # Run migrations and setup
    if not TOKEN: exit("No TOKEN found")
    
    # 1. Timezone is critical for scheduler
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Dubai'))
    
    app = ApplicationBuilder().token(TOKEN).defaults(defaults).post_init(post_init).build()

    app.add_error_handler(error_handler)

    # 2. PRIORITY 1: Commands & Debug
    app.add_handler(CommandHandler('cancel', cancel))
    app.add_handler(CommandHandler('jobs', cmd_jobs))
    app.add_handler(CommandHandler('alert', cmd_alert))

    # 3. PRIORITY 2: Feature Handlers (SPECIFIC regex matchers)
    app.add_handler(dashboard_handler) 
    app.add_handler(onboarding_handler)
    app.add_handler(collection_handler)
    app.add_handler(evening_handler)
    app.add_handler(ai_handler)
    app.add_handler(ai_feedback_handler)
    app.add_handler(history_handler)
    app.add_handler(adhoc_handler)

    # 4. PRIORITY 3: Fallback Router (Catch-all)
    app.add_handler(CommandHandler('start', global_router))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), global_router))

    logger.info("✅ Bot started. Scheduler active.")
    app.run_polling()