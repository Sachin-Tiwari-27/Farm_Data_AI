import os
import logging
import pytz
from dotenv import load_dotenv

from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, Application, Defaults
)

import database as db
from handlers.onboarding import onboarding_handler
from handlers.adhoc import adhoc_handler

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- JOB SCHEDULER ---
async def schedule_user_jobs(application, user_id, p_time_str, v_time_str):
    jq = application.job_queue
    for name in [f"{user_id}_morning", f"{user_id}_evening"]:
        for job in jq.get_jobs_by_name(name): job.schedule_removal()
    try:
        tz = pytz.timezone('Asia/Dubai')
        from datetime import datetime
        p_time = datetime.strptime(p_time_str, "%H:%M").time().replace(tzinfo=tz)
        v_time = datetime.strptime(v_time_str, "%H:%M").time().replace(tzinfo=tz)
        
        jq.run_daily(trigger_morning, p_time, chat_id=user_id, name=f"{user_id}_morning")
        jq.run_daily(trigger_evening, v_time, chat_id=user_id, name=f"{user_id}_evening")
    except ValueError: pass

async def trigger_morning(context):
    await context.bot.send_message(context.job.chat_id, "☀️ **Morning Check-in!**\nType /collection to start.", parse_mode='Markdown')

async def trigger_evening(context):
    await context.bot.send_message(context.job.chat_id, "🌙 **Evening Summary**\nType /record to start.", parse_mode='Markdown')

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home / Register"),
        BotCommand("profile", "👤 Dashboard"),
        BotCommand("history", "📊 View History"),
        BotCommand("cancel", "❌ Stop Action")
    ])
    # Restore schedules
    for user in db.get_all_users():
        await schedule_user_jobs(application, user.id, user.photo_time, user.voice_time)

if __name__ == '__main__':
    if not TOKEN: exit("No TOKEN")
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Dubai'))
    app = ApplicationBuilder().token(TOKEN).defaults(defaults).post_init(post_init).build()

    # Register Handlers
    app.add_handler(onboarding_handler)
    app.add_handler(adhoc_handler)
    
    print("🤖 Farm Diary Bot LIVE (Phase 2C: Ad-Hoc Tagging).")
    app.run_polling()