import os
import logging
import datetime
import io
import pytz
from dotenv import load_dotenv

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, InputMediaPhoto
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

# --- CONSTANTS ---
NAME, FARM, LOCATION, P_TIME, V_TIME, L_COUNT = range(6)
L_START, CAPTURE_WIDE, CAPTURE_CLOSE, CAPTURE_SOIL, CONFIRM_SET, LOG_STATUS, ADD_NOTE = range(6, 13)
VOICE_RECORD = 13
EDIT_NAME, EDIT_SCHED_M, EDIT_SCHED_E = range(14, 17)
VIEW_HISTORY = 17

MAIN_MENU_KBD = ReplyKeyboardMarkup([
    ['📸 Start Morning Check-in'],
    ['🎙 Record Evening Summary'],
    ['📊 View History', '👤 Dashboard'],
    ['🌦 Check Weather', '❓ Help']
], resize_keyboard=True)

# --- HELPER: REGISTRATION CHECK ---
async def ensure_registered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "⚠️ **Unknown User**\nPlease tap /start to register.",
            parse_mode='Markdown'
        )
        return None
    return user

# --- HELPER: ROUTINE CHECK ---
def is_routine_done(user_id, routine_type):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    logs = db.get_logs_by_date(user_id, today)
    logged_ids = [l.get('landmark_id') for l in logs]
    
    if routine_type == 'evening':
        return 0 in logged_ids 
        
    if routine_type == 'morning':
        landmarks = db.get_user_landmarks(user_id)
        # Filter for IDs 1, 2, 3... (Exclude 0 and 99)
        morning_logs = [lid for lid in logged_ids if lid not in [0, 99]]
        return len(set(morning_logs)) >= len(landmarks)
    
    return False

# --- SCHEDULER UTILS ---
async def schedule_user_jobs(application, user_id, p_time_str, v_time_str):
    jq = application.job_queue
    for name in [f"{user_id}_morning", f"{user_id}_evening"]:
        for job in jq.get_jobs_by_name(name): job.schedule_removal()
    
    try:
        tz = pytz.timezone('Asia/Dubai')
        p_time = datetime.datetime.strptime(p_time_str, "%H:%M").time().replace(tzinfo=tz)
        v_time = datetime.datetime.strptime(v_time_str, "%H:%M").time().replace(tzinfo=tz)
        jq.run_daily(trigger_morning, p_time, chat_id=user_id, name=f"{user_id}_morning")
        jq.run_daily(trigger_evening, v_time, chat_id=user_id, name=f"{user_id}_evening")
    except ValueError:
        logger.error(f"Time format error for user {user_id}")

async def trigger_morning(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(job.chat_id, "☀️ **Morning Check-in!**\nTime to walk the farm.", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')

async def trigger_evening(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(job.chat_id, "🌙 **Evening Summary**\nReady to record?", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home / Register"),
        BotCommand("history", "📊 View Entry History"),
        BotCommand("weather", "🌦 Check Farm Weather"),
        BotCommand("cancel", "❌ Stop Action")
    ])
    for user in db.get_all_users():
        await schedule_user_jobs(application, user.id, user.photo_time, user.voice_time)

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if user:
        await update.message.reply_text(f"👋 **Welcome back, {user.full_name}!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    await update.message.reply_text("👋 **Welcome.**\nLet's set up your farm profile.\n\nStep 1: What is your **Full Name**?", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
    return NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    kb = MAIN_MENU_KBD if user else ReplyKeyboardRemove()
    await update.message.reply_text("❌ Cancelled.", reply_markup=kb)
    return ConversationHandler.END

# --- PROFILE DASHBOARD ---
async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and not await ensure_registered(update, context): return ConversationHandler.END

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        msg_func = query.edit_message_text
    else:
        user_id = update.effective_user.id
        msg_func = update.message.reply_text

    user = db.get_user_profile(user_id)
    landmarks = db.get_user_landmarks(user.id)
    lm_text = "\n".join([f"• {lm.label}: {lm.last_status}" for lm in landmarks])

    msg = (f"👤 **{user.full_name}** | 🌱 {user.farm_name}\n📍 {user.latitude:.4f}, {user.longitude:.4f}\n"
           f"⏰ P: {user.photo_time} | V: {user.voice_time}\n📍 **Landmarks:**\n{lm_text}")
    kb = [[InlineKeyboardButton("✏️ Edit Name", callback_data="edit_name"), InlineKeyboardButton("✏️ Edit Schedule", callback_data="edit_sched")]]
    await msg_func(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ConversationHandler.END

# --- HISTORY DASHBOARD ---
async def view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        if not await ensure_registered(update, context): return ConversationHandler.END
        msg_func = update.message.reply_text
    else:
        query = update.callback_query
        await query.answer()
        msg_func = query.edit_message_text
    
    kb = [
        [InlineKeyboardButton("📅 Today", callback_data="hist_today")],
        [InlineKeyboardButton("📅 Yesterday", callback_data="hist_yesterday")],
        [InlineKeyboardButton("📅 Last 7 Days", callback_data="hist_week")]
    ]
    await msg_func("📊 **Entry History**\n\nSelect time period:", 
                   reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

async def show_history_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    period = query.data.replace('hist_', '')
    
    tz = pytz.timezone('Asia/Dubai')
    today = datetime.datetime.now(tz).date()
    
    if period == 'today':
        start_date = end_date = today
        title = "Today"
    elif period == 'yesterday':
        start_date = end_date = today - datetime.timedelta(days=1)
        title = "Yesterday"
    else:  # week
        start_date = today - datetime.timedelta(days=7)
        end_date = today
        title = "Last 7 Days"
    
    # Fetch RAW entries to avoid KeyError
    entries_by_date = db.get_entries_by_date_range(user_id, start_date, end_date)
    
    if not entries_by_date:
        await query.edit_message_text(f"📊 **{title}**\n\n_No entries found._", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_to_history")]]))
        return VIEW_HISTORY
    
    message = f"📊 **Entry History - {title}**\n{'='*30}\n\n"
    
    for date_str, day_data in entries_by_date.items():
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        message += f"📅 **{date_obj.strftime('%b %d')}**\n"
        
        # Loop through entries safely
        for entry in day_data.get('entries', []):
            # SAFE ACCESS: Use .get() to prevent KeyError
            lid = entry.get('landmark_id', -1)
            status = entry.get('status', 'Unknown')
            name = entry.get('landmark_name', f'Spot {lid}')
            
            icon = "⚪"
            if status == "Healthy": icon = "🟢"
            elif status == "Issue": icon = "🔴"
            elif status == "Unsure": icon = "🟠"
            
            # Special Icons
            if lid == 0: 
                icon = "🌙" # Evening
                name = "Evening Summary"
            elif lid == 99: 
                icon = "📸" # Ad-Hoc
            
            note_icon = "📝" if entry.get('has_note') else ""
            message += f"  {icon} {name}: {status} {note_icon}\n"
        message += "\n"
    
    kb = []
    for date_str in list(entries_by_date.keys())[:5]:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        kb.append([InlineKeyboardButton(f"📸 View {date_obj.strftime('%b %d')}", callback_data=f"view_date_{date_str}")])
    
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="back_to_history")])
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

async def show_date_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    date_str = query.data.replace('view_date_', '')
    entries = db.get_entries_for_date(user_id, date_str)
    
    if not entries:
        await query.edit_message_text("No entries found.")
        return VIEW_HISTORY
    
    # 1. Text Summary
    summary_text = f"📊 **History** ({date_str})\n━━━━━━━━━━━━━━━━\n"
    for entry in entries:
        t = entry.timestamp.strftime('%H:%M')
        if entry.landmark_id == 0:
             summary_text += f"🌙 **Evening Summary** ({t})\n"
        elif entry.landmark_id == 99:
             summary_text += f"⚠️ **Ad-Hoc Capture** ({t})\n"
        else:
             icon = "🟢" if entry.status == "Healthy" else "🔴" if entry.status == "Issue" else "🟠" if entry.status == "Unsure" else "⚪"
             summary_text += f"{icon} **{entry.landmark.label}:** {entry.status}\n"

    await query.edit_message_text(summary_text, parse_mode='Markdown')

    # 2. Send Media (Photos AND Voice)
    for entry in entries:
        media_group = []
        files_to_close = []
        
        # --- PHOTOS ---
        try:
            # Ad-Hoc Photo
            if entry.landmark_id == 99 and getattr(entry, 'img_wide', None) and os.path.exists(entry.img_wide):
                 fh = open(entry.img_wide, 'rb')
                 files_to_close.append(fh)
                 media_group.append(InputMediaPhoto(fh, caption=f"Ad-Hoc ({entry.timestamp.strftime('%H:%M')})"))
            
            # Routine Photos (Wide, Close, Soil)
            elif entry.landmark_id not in [0, 99]:
                for img_type in ['wide', 'close', 'soil']:
                    img_path = getattr(entry, f'img_{img_type}', None)
                    if img_path and os.path.exists(img_path):
                        fh = open(img_path, 'rb')
                        files_to_close.append(fh)
                        caption = f"{entry.landmark.label} - {img_type.capitalize()}" if not media_group else ""
                        media_group.append(InputMediaPhoto(fh, caption=caption))
            
            if media_group:
                await query.message.reply_media_group(media_group)
                
        except Exception as e:
            logger.error(f"Media error: {e}")
        finally:
            for fh in files_to_close: fh.close()

        # --- VOICE NOTES (Evening & Ad-Hoc) ---
        voice_path = getattr(entry, 'voice_path', None)
        
        if voice_path and os.path.exists(voice_path):
            caption = f"🎙 Note: {entry.landmark.label}"
            if entry.landmark_id == 0: caption = "🌙 Evening Summary"
            if entry.landmark_id == 99: caption = "🎙 Ad-Hoc Note"
            
            try:
                with open(voice_path, 'rb') as vf:
                    await query.message.reply_voice(voice=vf, caption=caption)
            except Exception as e:
                logger.error(f"Voice send error: {e}")

    kb = [[InlineKeyboardButton("◀️ Back to History", callback_data="back_to_history")]]
    await query.message.reply_text("\n\n─────────────────\n\n", reply_markup=InlineKeyboardMarkup(kb))
    return VIEW_HISTORY

# --- ONBOARDING & EDITING (Standard) ---
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
        await update.message.reply_text("✅ **Saved!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    except ValueError: return L_COUNT

async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✏️ New **Name**:")
    return EDIT_NAME
async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    db.save_user_profile({'id': user.id, 'name': update.message.text, 'farm': user.farm_name, 'lat': user.latitude, 'lon': user.longitude, 'p_time': user.photo_time, 'v_time': user.voice_time, 'l_count': user.landmark_count})
    await update.message.reply_text("✅ Name updated.", reply_markup=MAIN_MENU_KBD)
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
    await update.message.reply_text("✅ Schedule updated.", reply_markup=MAIN_MENU_KBD)
    return await view_profile(update, context)

# --- COLLECTION FLOW ---
async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and not await ensure_registered(update, context): return ConversationHandler.END
    user_id = update.effective_user.id
    if is_routine_done(user_id, 'morning'):
        await update.message.reply_text("✅ **Morning Check-in Complete**\nSend photos directly for **Ad-Hoc**.", parse_mode='Markdown', reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
    landmarks = db.get_user_landmarks(user_id)
    context.user_data.update({'landmarks': landmarks, 'current_idx': 0, 'temp_photos': {}, 'temp_status': None})
    weather = get_weather_data(db.get_user_profile(user_id).latitude, db.get_user_profile(user_id).longitude)
    context.user_data['weather'] = weather or {}
    await update.message.reply_text(f"🌦 **Weather:** {weather.get('display_str', 'N/A')}", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return await request_landmark_photos(update, context)

async def request_landmark_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: msg_obj = update.callback_query.message
    else: msg_obj = update.message
    idx = context.user_data['current_idx']
    if idx >= len(context.user_data['landmarks']):
        await msg_obj.reply_text("✅ **All Done!**", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
    lm = context.user_data['landmarks'][idx]
    await msg_obj.reply_text(f"📍 **{lm.label}** ({idx+1}/{len(context.user_data['landmarks'])})\n\n📸 **Step 1 of 3: Wide Shot**", parse_mode='Markdown')
    return CAPTURE_WIDE

async def handle_photo_step(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_step):
    if not update.message.photo: return None
    processing_msg = await update.message.reply_text("📤 _Uploading..._", parse_mode='Markdown')
    f = await update.message.photo[-1].get_file()
    user = db.get_user_profile(update.effective_user.id)
    path = await f.download_to_drive(f"data/media/{user.id}_temp_{key}.jpg")
    context.user_data['temp_photos'][key] = path
    await processing_msg.delete()
    if key == 'wide': await update.message.reply_text("✅ Wide shot saved!\n\n📸 **Step 2 of 3: Close-up**", parse_mode='Markdown')
    elif key == 'close': await update.message.reply_text("✅ Close-up saved!\n\n📸 **Step 3 of 3: Soil/Base**", parse_mode='Markdown')
    if next_step == CONFIRM_SET:
        kb = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm"), InlineKeyboardButton("🔄 Retake", callback_data="retake")]]
        await update.message.reply_text("Photos clear?", reply_markup=InlineKeyboardMarkup(kb))
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
    await query.edit_message_text("How does it look?", reply_markup=InlineKeyboardMarkup(kb))
    return LOG_STATUS

async def log_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data
    idx = context.user_data['current_idx']
    context.user_data['landmarks'][idx].last_status = status
    context.user_data['temp_status'] = status
    if status == "Healthy":
        await finalize_landmark_entry(update, context, voice_file=None)
        await query.edit_message_text(f"✅ Marked **{status}**.")
        context.user_data['current_idx'] += 1
        return await request_landmark_photos(update, context)
    else:
        kb = [[InlineKeyboardButton("🎙 Add Voice Note", callback_data="add_voice_note")], [InlineKeyboardButton("➡️ Skip Note", callback_data="skip_note")]]
        await query.edit_message_text(f"⚠️ Marked **{status}**\n\nWould you like to add details?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return ADD_NOTE

async def prompt_for_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎙 **Recording Mode**\n\nTap microphone to record.", parse_mode='Markdown')
    return ADD_NOTE

async def handle_landmark_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.voice: 
        await update.message.reply_text("Please send voice note.")
        return ADD_NOTE
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    await finalize_landmark_entry(update, context, voice_file=buf)
    await update.message.reply_text("✅ **Note Attached.**")
    context.user_data['current_idx'] += 1
    return await request_landmark_photos(update, context)

async def skip_landmark_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await finalize_landmark_entry(update, context, voice_file=None)
    await query.edit_message_text("✅ Recorded without note.")
    context.user_data['current_idx'] += 1
    return await request_landmark_photos(update, context)

async def finalize_landmark_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_file=None):
    user = db.get_user_profile(update.effective_user.id)
    lm = context.user_data['landmarks'][context.user_data['current_idx']]
    status = context.user_data['temp_status']
    saved_paths = {}
    for k, p in context.user_data['temp_photos'].items():
        with open(p, 'rb') as f: saved_paths[k] = save_telegram_file(f, user.id, user.farm_name, lm.id, k)
        if os.path.exists(p): os.remove(p)
    if voice_file:
        v_path = save_telegram_file(voice_file, user.id, user.farm_name, lm.id, "issue_note")
        saved_paths['voice_path'] = v_path
    db.create_entry(user.id, lm.id, saved_paths, status, context.user_data.get('weather', {}))

# --- EVENING ---
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and not await ensure_registered(update, context): return ConversationHandler.END
    if is_routine_done(update.effective_user.id, 'evening'):
        await update.message.reply_text("✅ **Evening Summary Recorded**", parse_mode='Markdown', reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
    await update.message.reply_text("🎙 **Recording...**\nTap mic to record.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return VOICE_RECORD

async def save_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.voice: return VOICE_RECORD
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    user = db.get_user_profile(update.effective_user.id)
    saved_path = save_telegram_file(buf, user.id, user.farm_name, 0, "daily_summary")
    
    # CRITICAL FIX: Explicitly log Landmark 0
    db.create_entry(user.id, 0, {"voice_path": saved_path}, "Summary", {})
    
    await update.message.reply_text("✅ **Summary Saved.**", parse_mode='Markdown', reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

async def check_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_registered(update, context)
    if not user: return
    loading_msg = await update.message.reply_text("🌦 _Fetching weather..._", parse_mode='Markdown')
    weather = get_weather_data(user.latitude, user.longitude)
    await loading_msg.delete()
    if not weather:
        await update.message.reply_text("⚠️ Unable to fetch weather.", reply_markup=MAIN_MENU_KBD)
        return
    msg = f"🌦 **Weather:** {weather['temp']}°C, {weather['desc']}\n💧 Hum: {weather['humidity']}% | 🌬 Wind: {weather['wind_speed']}m/s"
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_MENU_KBD)

# --- ADHOC ---
async def handle_adhoc_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📸 Start Morning Check-in': return await start_collection(update, context)
    if text == '🎙 Record Evening Summary': return await start_evening_flow(update, context)
    if text == '👤 Dashboard': return await view_profile(update, context)
    if text == '📊 View History': return await view_history(update, context)
    if text == '🌦 Check Weather': return await check_weather(update, context)
    if text == '❓ Help': 
        await update.message.reply_text("Use menu buttons below.", reply_markup=MAIN_MENU_KBD)
        return
    if update.message.photo or update.message.voice:
        user = await ensure_registered(update, context)
        if not user: return
        buf = io.BytesIO()
        saved_paths = {}
        ftype = ""
        if update.message.photo:
            f = await update.message.photo[-1].get_file()
            await f.download_to_memory(buf)
            saved_paths = {'wide': save_telegram_file(buf, user.id, user.farm_name, 99, "adhoc_photo")}
            ftype = "Photo"
            await update.message.reply_text("📸 **Snapshot saved.**", reply_markup=MAIN_MENU_KBD)
        elif update.message.voice:
            f = await update.message.voice.get_file()
            await f.download_to_memory(buf)
            saved_paths = {'voice_path': save_telegram_file(buf, user.id, user.farm_name, 99, "adhoc_voice")}
            ftype = "Voice"
            await update.message.reply_text("🎙 **Note saved.**", reply_markup=MAIN_MENU_KBD)
        db.create_entry(user.id, 99, saved_paths, f"Ad-Hoc {ftype}", {})

if __name__ == '__main__':
    if not TOKEN: exit("No TOKEN")
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Dubai'))
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
        entry_points=[CommandHandler('profile', view_profile), CallbackQueryHandler(edit_name_start, pattern="^edit_name$"), CallbackQueryHandler(edit_sched_start, pattern="^edit_sched$"), MessageHandler(filters.Regex("^👤 Dashboard$"), view_profile)],
        states={EDIT_NAME: [MessageHandler(filters.TEXT, edit_name_save)], EDIT_SCHED_M: [MessageHandler(filters.TEXT, edit_sched_m)], EDIT_SCHED_E: [MessageHandler(filters.TEXT, edit_sched_save)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    collection = ConversationHandler(
        entry_points=[CommandHandler('collection', start_collection), CallbackQueryHandler(start_collection, pattern="^start_collection$"), MessageHandler(filters.Regex("^📸 Start Morning Check-in$"), start_collection)],
        states={
            CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide)],
            CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close)],
            CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil)],
            CONFIRM_SET: [CallbackQueryHandler(handle_confirmation)],
            LOG_STATUS: [CallbackQueryHandler(log_status)],
            ADD_NOTE: [MessageHandler(filters.VOICE, handle_landmark_note), CallbackQueryHandler(prompt_for_voice_note, pattern="^add_voice_note$"), CallbackQueryHandler(skip_landmark_note, pattern="^skip_note$")]
        }, fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    evening = ConversationHandler(
        entry_points=[CommandHandler('record', start_evening_flow), CallbackQueryHandler(start_evening_flow, pattern="^start_evening$"), MessageHandler(filters.Regex("^🎙 Record Evening Summary$"), start_evening_flow)],
        states={VOICE_RECORD: [MessageHandler(filters.VOICE, save_voice_note)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    history = ConversationHandler(
        entry_points=[CommandHandler('history', view_history), MessageHandler(filters.Regex("^📊 View History$"), view_history)],
        states={VIEW_HISTORY: [CallbackQueryHandler(view_history, pattern="^back_to_history$"), CallbackQueryHandler(show_history_period, pattern="^hist_"), CallbackQueryHandler(show_date_details, pattern="^view_date_")]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(onboard)
    app.add_handler(edit_profile)
    app.add_handler(collection)
    app.add_handler(evening)
    app.add_handler(history)
    app.add_handler(CommandHandler('weather', check_weather))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VOICE, handle_adhoc_media))
    
    print("🤖 Farm Diary Bot LIVE.")
    app.run_polling()