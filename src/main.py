import os
import logging
import datetime
import io
import pytz
from dotenv import load_dotenv

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ConversationHandler, CallbackQueryHandler, filters, ContextTypes, Application, Defaults
)

import database as db
from weather import get_weather_data
from utils.validators import parse_time
from utils.files import save_telegram_file

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- STATES ---
NAME, FARM, LOCATION, P_TIME, V_TIME, L_COUNT = range(6)
L_START, CAPTURE_WIDE, CAPTURE_CLOSE, CAPTURE_SOIL, CONFIRM_SET, LOG_STATUS = range(6, 12)
VOICE_RECORD = 12
EDIT_NAME, EDIT_SCHED_M, EDIT_SCHED_E = range(13, 16)

# --- SCHEDULER UTILS ---
async def schedule_user_jobs(application, user_id, p_time_str, v_time_str):
    jq = application.job_queue
    
    # 1. Clean Old Jobs
    for name in [f"{user_id}_morning", f"{user_id}_evening"]:
        for job in jq.get_jobs_by_name(name): job.schedule_removal()
    
    # 2. Parse Times with Timezone
    try:
        tz = pytz.timezone('Asia/Dubai')
        p_time = datetime.datetime.strptime(p_time_str, "%H:%M").time().replace(tzinfo=tz)
        v_time = datetime.datetime.strptime(v_time_str, "%H:%M").time().replace(tzinfo=tz)
    except ValueError:
        logger.error(f"Time format error for user {user_id}")
        return

    # 3. Schedule with chat_id (Standardized)
    jq.run_daily(trigger_morning, p_time, chat_id=user_id, name=f"{user_id}_morning")
    jq.run_daily(trigger_evening, v_time, chat_id=user_id, name=f"{user_id}_evening")
    logger.info(f"Updated schedule for User {user_id} at {p_time} / {v_time}")

async def trigger_morning(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        kb = [[InlineKeyboardButton("📸 Start Collection", callback_data="start_collection")]]
        await context.bot.send_message(job.chat_id, "☀️ **Morning Check-in!**\nReady?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        logger.info(f"Morning trigger sent to {job.chat_id}")
    except Exception as e:
        logger.error(f"Failed to send Morning trigger: {e}")

async def trigger_evening(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        kb = [[InlineKeyboardButton("🎙 Record Summary", callback_data="start_evening")]]
        await context.bot.send_message(job.chat_id, "🌙 **Evening Summary**\nHow was the day?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        logger.info(f"Evening trigger sent to {job.chat_id}")
    except Exception as e:
        logger.error(f"Failed to send Evening trigger: {e}")

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home"),
        BotCommand("collection", "📸 Morning Check-in"),
        BotCommand("record", "🎙 Evening Summary"),
        BotCommand("profile", "👤 Dashboard"),
        BotCommand("cancel", "❌ Stop")
    ])
    for user in db.get_all_users():
        await schedule_user_jobs(application, user.id, user.photo_time, user.voice_time)

# --- ADHOC HANDLER ---
async def handle_adhoc_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if not user: return 
    buf = io.BytesIO()
    if update.message.photo:
        f = await update.message.photo[-1].get_file()
        await f.download_to_memory(buf)
        save_telegram_file(buf, user.id, 99, "adhoc_photo")
        await update.message.reply_text("📸 **Snapshot saved.**", parse_mode='Markdown')
    elif update.message.voice:
        f = await update.message.voice.get_file()
        await f.download_to_memory(buf)
        save_telegram_file(buf, user.id, 99, "adhoc_voice")
        await update.message.reply_text("🎙 **Note saved.**", parse_mode='Markdown')

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if user:
        await update.message.reply_text(f"👋 **Welcome back, {user.full_name}!**", parse_mode='Markdown')
        return ConversationHandler.END
    await update.message.reply_text("👋 **Welcome.** Step 1: **Full Name**?", parse_mode='Markdown')
    return NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        msg_func = query.edit_message_text
    else:
        user_id = update.effective_user.id
        msg_func = update.message.reply_text

    user = db.get_user_profile(user_id)
    if not user: 
        if update.message: return await start(update, context)
        return

    landmarks = db.get_user_landmarks(user.id)
    lm_text = "\n".join([f"• {lm.label}: {lm.last_status}" for lm in landmarks])

    msg = (f"👤 **{user.full_name}** | 🌱 {user.farm_name}\n📍 {user.latitude:.4f}, {user.longitude:.4f}\n"
           f"⏰ P: {user.photo_time} | V: {user.voice_time}\n📍 **Landmarks:**\n{lm_text}")

    kb = [[InlineKeyboardButton("✏️ Edit Name", callback_data="edit_name"), InlineKeyboardButton("✏️ Edit Schedule", callback_data="edit_sched")]]
    await msg_func(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ConversationHandler.END

# --- EDIT HANDLERS ---
async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✏️ New **Name**:")
    return EDIT_NAME
async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    db.save_user_profile({'id': user.id, 'name': update.message.text, 'farm': user.farm_name, 'lat': user.latitude, 'lon': user.longitude, 'p_time': user.photo_time, 'v_time': user.voice_time, 'l_count': user.landmark_count})
    await update.message.reply_text("✅ Name updated.")
    return await view_profile(update, context)
async def edit_sched_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✏️ New **Morning Time** (e.g. '7'):")
    return EDIT_SCHED_M
async def edit_sched_m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=False)
    if not t: return EDIT_SCHED_M
    context.user_data['new_p_time'] = t
    await update.message.reply_text("✏️ New **Evening Time** (e.g. '6'):")
    return EDIT_SCHED_E
async def edit_sched_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=True)
    if not t: return EDIT_SCHED_E
    user = db.get_user_profile(update.effective_user.id)
    db.save_user_profile({'id': user.id, 'name': user.full_name, 'farm': user.farm_name, 'lat': user.latitude, 'lon': user.longitude, 'p_time': context.user_data['new_p_time'], 'v_time': t, 'l_count': user.landmark_count})
    await schedule_user_jobs(context.application, user.id, context.user_data['new_p_time'], t)
    await update.message.reply_text("✅ Schedule updated.")
    return await view_profile(update, context)

# --- ONBOARDING ---
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Step 2: **Farm Name**?", parse_mode='Markdown')
    return FARM
async def get_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['farm'] = update.message.text
    kb = [[KeyboardButton("📍 Share Farm Location", request_location=True)]]
    await update.message.reply_text("Step 3: **Location**.", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True), parse_mode='Markdown')
    return LOCATION
async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    context.user_data['lat'], context.user_data['lon'] = loc.latitude, loc.longitude
    await update.message.reply_text("Step 4: **Morning Time**? (e.g. '7')", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
    return P_TIME
async def get_p_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=False)
    if not t: return P_TIME
    context.user_data['p_time'] = t
    await update.message.reply_text("Step 5: **Evening Time**? (e.g. '6')", parse_mode='Markdown')
    return V_TIME
async def get_v_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=True)
    if not t: return V_TIME
    context.user_data['v_time'] = t
    kb = [["3", "4", "5"]]
    await update.message.reply_text("Step 6: **Landmarks Count**?", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True), parse_mode='Markdown')
    return L_COUNT
async def get_l_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if count not in [3,4,5]: raise ValueError
        user_id = update.effective_user.id
        db.save_user_profile({'id': user_id, 'name': context.user_data['name'], 'farm': context.user_data['farm'], 'lat': context.user_data['lat'], 'lon': context.user_data['lon'], 'p_time': context.user_data['p_time'], 'v_time': context.user_data['v_time'], 'l_count': count})
        await schedule_user_jobs(context.application, user_id, context.user_data['p_time'], context.user_data['v_time'])
        await update.message.reply_text("✅ **Saved!**", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        return ConversationHandler.END
    except ValueError: return L_COUNT

# --- COLLECTION ---
async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    msg_func = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    user_id = update.effective_user.id
    landmarks = db.get_user_landmarks(user_id)
    if not landmarks: return ConversationHandler.END
    context.user_data.update({'landmarks': landmarks, 'current_idx': 0, 'temp_photos': {}})
    weather = get_weather_data(db.get_user_profile(user_id).latitude, db.get_user_profile(user_id).longitude)
    context.user_data['weather'] = weather or {}
    await msg_func(f"🌦 **Weather:** {weather.get('display_str', 'N/A')}", parse_mode='Markdown')
    return await request_landmark_photos(update, context)

async def request_landmark_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: msg_obj = update.callback_query.message
    elif update.message: msg_obj = update.message
    else: return ConversationHandler.END
    idx = context.user_data['current_idx']
    if idx >= len(context.user_data['landmarks']):
        await msg_obj.reply_text("✅ **Done!**")
        return ConversationHandler.END
    lm = context.user_data['landmarks'][idx]
    await msg_obj.reply_text(f"📍 **{lm.label}** ({idx+1}/{len(context.user_data['landmarks'])})\nStatus: {lm.last_status}\n\n📸 **Capture 3 Views:**\n1. Wide\n2. Close-up\n3. Soil\n\n💡 *Tip: Send 3 photos at once!*", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return CAPTURE_WIDE

async def handle_photo_step(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_step):
    if not update.message.photo: return None
    f = await update.message.photo[-1].get_file()
    path = await f.download_to_drive(f"data/media/{update.effective_user.id}_temp_{key}.jpg")
    context.user_data['temp_photos'][key] = path
    if next_step == CONFIRM_SET:
        kb = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm"), InlineKeyboardButton("🔄 Retake", callback_data="retake")]]
        await update.message.reply_text("Photos received. Confirm?", reply_markup=InlineKeyboardMarkup(kb))
        return CONFIRM_SET
    return next_step

async def handle_wide(update: Update, context: ContextTypes.DEFAULT_TYPE): return await handle_photo_step(update, context, 'wide', CAPTURE_CLOSE)
async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE): return await handle_photo_step(update, context, 'close', CAPTURE_SOIL)
async def handle_soil(update: Update, context: ContextTypes.DEFAULT_TYPE): return await handle_photo_step(update, context, 'soil', CONFIRM_SET)
async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "retake": 
        await query.edit_message_text("Restarting spot...")
        return await request_landmark_photos(update, context)
    kb = [[InlineKeyboardButton("🟢 Healthy", callback_data="Healthy"), InlineKeyboardButton("🔴 Issue", callback_data="Issue"), InlineKeyboardButton("🟠 Unsure", callback_data="Unsure")]]
    await query.edit_message_text("Status?", reply_markup=InlineKeyboardMarkup(kb))
    return LOG_STATUS
async def log_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lm = context.user_data['landmarks'][context.user_data['current_idx']]
    saved = {}
    for k, p in context.user_data['temp_photos'].items():
        with open(p, 'rb') as f: saved[k] = save_telegram_file(f, user_id, lm.id, k)
        if os.path.exists(p): os.remove(p)
    db.create_entry(user_id, lm.id, saved, query.data, context.user_data.get('weather', {}))
    await query.edit_message_text(f"✅ Saved **{lm.label}**.", parse_mode='Markdown')
    context.user_data['current_idx'] += 1
    return await request_landmark_photos(update, context)

# --- EVENING ---
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    msg_func = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    await msg_func("🎙 **Recording...**\nTap mic to record.", parse_mode='Markdown')
    return VOICE_RECORD
async def save_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.voice: return VOICE_RECORD
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    save_telegram_file(buf, update.effective_user.id, 0, "daily_summary")
    await update.message.reply_text("✅ **Summary Saved.**", parse_mode='Markdown')
    return ConversationHandler.END

# --- DEBUG ---
async def debug_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows EXACT run date and timezone of jobs."""
    jobs = context.job_queue.jobs()
    if not jobs:
        await update.message.reply_text("📭 No jobs scheduled.")
        return

    text = "📋 **Active Jobs:**\n"
    for job in jobs:
        # Show Full Date + Timezone
        next_t = job.next_t.strftime('%Y-%m-%d %H:%M:%S %Z') if job.next_t else "N/A"
        text += f"- `{job.name}`:\n  Runs at **{next_t}**\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')
    
async def debug_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now().astimezone()
    await update.message.reply_text(f"🕒 **Local:** {now.strftime('%H:%M:%S')}\n📍 **Zone:** {now.tzname()}")

# --- BUILD ---
if __name__ == '__main__':
    if not TOKEN: exit("No TOKEN")
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Dubai')) # GLOBAL TIMEZONE DEFAULT
    app = ApplicationBuilder().token(TOKEN).defaults(defaults).post_init(post_init).build()

    onboard = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            FARM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_farm)],
            LOCATION: [MessageHandler(filters.LOCATION, get_location)],
            P_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_p_time)],
            V_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_time)],
            L_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_l_count)]
        }, fallbacks=[CommandHandler('cancel', cancel)]
    )

    edit_profile = ConversationHandler(
        entry_points=[
            CommandHandler('profile', view_profile),
            CallbackQueryHandler(edit_name_start, pattern="^edit_name$"),
            CallbackQueryHandler(edit_sched_start, pattern="^edit_sched$")
        ],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save)],
            EDIT_SCHED_M: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_sched_m)],
            EDIT_SCHED_E: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_sched_save)],
        }, fallbacks=[CommandHandler('cancel', cancel)]
    )

    collection = ConversationHandler(
        entry_points=[CommandHandler('collection', start_collection), CallbackQueryHandler(start_collection, pattern="^start_collection$")],
        states={
            CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide)],
            CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close)],
            CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil)],
            CONFIRM_SET: [CallbackQueryHandler(handle_confirmation)],
            LOG_STATUS: [CallbackQueryHandler(log_status)]
        }, fallbacks=[CommandHandler('cancel', cancel)]
    )

    evening = ConversationHandler(
        entry_points=[CommandHandler('record', start_evening_flow), CallbackQueryHandler(start_evening_flow, pattern="^start_evening$")],
        states={VOICE_RECORD: [MessageHandler(filters.VOICE, save_voice_note)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(onboard)
    app.add_handler(edit_profile)
    app.add_handler(collection)
    app.add_handler(evening)
    app.add_handler(MessageHandler(filters.PHOTO | filters.VOICE, handle_adhoc_media))
    app.add_handler(CommandHandler("jobs", debug_jobs))
    app.add_handler(CommandHandler("time", debug_time))
    
    print("🤖 Farm Diary Bot LIVE.")
    app.run_polling()