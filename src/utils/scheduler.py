import logging
import datetime
import pytz
from telegram.ext import ContextTypes, Application
import database as db
from utils.menus import MAIN_MENU_KBD

logger = logging.getLogger(__name__)

# --- CALLBACKS ---
async def send_morning_alert(context: ContextTypes.DEFAULT_TYPE):
    """Checks if morning routine is done. If not, sends reminder."""
    job = context.job
    user_id = job.user_id
    
    # Smart Check: Don't annoy if already done
    if db.is_routine_done(user_id, 'morning'):
        logger.info(f"Skipping morning alert for {user_id} (Already done)")
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="☀️ **Good Morning!**\nTime to walk the farm and log your observations.\n\n Click on _(Start Morning Check-in)_ button to start.",
            reply_markup=MAIN_MENU_KBD,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send morning alert to {user_id}: {e}")

async def send_evening_alert(context: ContextTypes.DEFAULT_TYPE):
    """Checks if evening routine is done. If not, sends reminder."""
    job = context.job
    user_id = job.user_id
    
    if db.is_routine_done(user_id, 'evening'):
        logger.info(f"Skipping evening alert for {user_id} (Already done)")
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🌙 **Evening Summary**\nPlease record your daily voice note before you rest.\n\n Click on _(Record Evening Summary)_ button to start.",
            reply_markup=MAIN_MENU_KBD,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send evening alert to {user_id}: {e}")

async def send_debug_alert(context: ContextTypes.DEFAULT_TYPE):
    """For /alert command testing."""
    job = context.job
    await context.bot.send_message(
        chat_id=job.user_id, 
        text=f"🔔 **Debug Alert:** {job.data}",
        parse_mode='Markdown'
    )

# --- MANAGER ---
async def schedule_user_jobs(application: Application, user_id: int, p_time_str: str, v_time_str: str):
    """Removes old jobs for user and sets new ones with safety checks."""
    
    # 1. CRITICAL SAFETY CHECK: Ensure JobQueue is initialized
    if not application.job_queue:
        logger.error(f"❌ JobQueue not found. Cannot schedule jobs for user {user_id}. "
                     "Ensure 'python-telegram-bot[job-queue]' is installed.")
        return

    # 2. Clear existing jobs for this user using a safer method
    try:
        # We use get_jobs_by_name to find specifically named jobs
        for job_prefix in ["photo_user_", "voice_user_"]:
            current_jobs = application.job_queue.get_jobs_by_name(f"{job_prefix}{user_id}")
            for job in current_jobs:
                job.schedule_removal()
    except Exception as e:
        logger.warning(f"Issue clearing old jobs for {user_id}: {e}")

    # 3. Parse Times and Schedule
    try:
        # Get Timezone from defaults or fallback
        tz = None
        if hasattr(application, 'bot') and hasattr(application.bot, 'defaults'):
            tz = application.bot.defaults.tzinfo
        if not tz:
            tz = pytz.timezone('Asia/Dubai')
        
        # Morning Job
        ph_str, pm_str = p_time_str.split(':')
        m_time = datetime.time(hour=int(ph_str), minute=int(pm_str), tzinfo=tz)
        
        application.job_queue.run_daily(
            send_morning_alert, 
            m_time, 
            user_id=user_id, 
            name=f"photo_user_{user_id}", 
            data="morning",
            job_kwargs={"misfire_grace_time": 300, "coalesce": True}
        )
        
        # Evening Job
        vh_str, vm_str = v_time_str.split(':')
        e_time = datetime.time(hour=int(vh_str), minute=int(vm_str), tzinfo=tz)
        
        application.job_queue.run_daily(
            send_evening_alert, 
            e_time, 
            user_id=user_id, 
            name=f"voice_user_{user_id}", 
            data="evening",
            job_kwargs={"misfire_grace_time": 300, "coalesce": True}
        )
        
        logger.info(f"✅ Scheduled jobs for {user_id}: {m_time.strftime('%H:%M')} and {e_time.strftime('%H:%M')}")
        
    except Exception as e:
        logger.error(f"Failed to schedule for {user_id}: {e}")

async def restore_scheduled_jobs(application: Application):
    """Called on startup to reload all schedules from DB."""
    # Ensure JobQueue exists before trying to restore
    if not application.job_queue:
        logger.warning("⚠️ Skipping job restoration: JobQueue not initialized.")
        return

    logger.info("🔄 Restoring scheduled jobs...")
    ids = db.get_all_user_ids()
    count = 0
    for uid in ids:
        user = db.get_user_profile(uid)
        if user and user.photo_time and user.voice_time:
            await schedule_user_jobs(application, uid, user.photo_time, user.voice_time)
            count += 1
    logger.info(f"✅ Restored schedules for {count} users.")