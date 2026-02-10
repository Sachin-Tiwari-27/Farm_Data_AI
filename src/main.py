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
    """Strict Gatekeeper: Forces /start if user not found."""
    user = db.get_user_profile(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "⚠️ **Unknown User**\nI don't have a profile for you yet.\n\nPlease tap /start to register.",
            parse_mode='Markdown'
        )
        return None
    return user

# --- HELPER: ROUTINE CHECK (NEW) ---
def is_routine_done(user_id, routine_type):
    """Checks if the user has already completed the routine today."""
    today = datetime.datetime.now().date()
    # db.get_entries_by_date_range returns data keyed by YYYY-MM-DD string
    entries = db.get_entries_by_date_range(user_id, today, today)
    date_str = today.strftime('%Y-%m-%d')
    day_data = entries.get(date_str)
    
    if not day_data:
        return False
        
    if routine_type == 'evening':
        return day_data.get('has_evening_summary', False)
        
    if routine_type == 'morning':
        # Check completion (Filter out Ad-Hoc)
        entered_landmarks = [e for e in day_data.get('entries', []) if e['landmark_name'] != "Ad-Hoc"]
        # Use only routine landmarks for total count
        total = len(db.get_routine_landmarks(user_id))
        return len(entered_landmarks) >= total
        
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
    
    # Proper entry point for Onboarding
    await update.message.reply_text("👋 **Welcome.**\nLet's set up your farm profile.\n\nStep 1: What is your **Full Name**?", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
    return NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    kb = MAIN_MENU_KBD if user else ReplyKeyboardRemove()
    await update.message.reply_text("❌ Cancelled.", reply_markup=kb)
    return ConversationHandler.END

# --- PROFILE DASHBOARD ---
async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message: 
        if not await ensure_registered(update, context): return ConversationHandler.END

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        msg_func = query.edit_message_text
    else:
        user_id = update.effective_user.id
        msg_func = update.message.reply_text

    user = db.get_user_profile(user_id)
    # Use routine landmarks only for profile display or clearly mark Ad-Hoc
    landmarks = db.get_user_landmarks(user_id)
    # Sort: Routine first, then Ad-Hoc
    landmarks.sort(key=lambda x: (x.label == "Ad-Hoc", x.id))
    
    lm_text = "\n".join([f"• {lm.label}: {lm.last_status}" for lm in landmarks])

    msg = (f"👤 **{user.full_name}** | 🌱 {user.farm_name}\n📍 {user.latitude:.4f}, {user.longitude:.4f}\n"
           f"⏰ P: {user.photo_time} | V: {user.voice_time}\n📍 **Landmarks:**\n{lm_text}")
    kb = [[InlineKeyboardButton("✏️ Edit Name", callback_data="edit_name"), InlineKeyboardButton("✏️ Edit Schedule", callback_data="edit_sched")]]
    await msg_func(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ConversationHandler.END

# --- HISTORY DASHBOARD ---
async def view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point for history viewing"""
    if update.message:
        if not await ensure_registered(update, context): return ConversationHandler.END
        msg_func = update.message.reply_text
    else:
        query = update.callback_query
        await query.answer()
        msg_func = query.edit_message_text
    
    # Show date range options
    kb = [
        [InlineKeyboardButton("📅 Today", callback_data="hist_today")],
        [InlineKeyboardButton("📅 Yesterday", callback_data="hist_yesterday")],
        [InlineKeyboardButton("📅 Last 7 Days", callback_data="hist_week")],
        [InlineKeyboardButton("📅 Last 30 Days", callback_data="hist_month")]
    ]
    await msg_func("📊 **Entry History**\n\nSelect time period:", 
                   reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

async def show_history_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display entries for selected period"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    period = query.data.replace('hist_', '')
    
    # Calculate date range
    tz = pytz.timezone('Asia/Dubai')
    today = datetime.datetime.now(tz).date()
    
    if period == 'today':
        start_date = today
        end_date = today
        title = "Today"
    elif period == 'yesterday':
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
        title = "Yesterday"
    elif period == 'week':
        start_date = today - datetime.timedelta(days=7)
        end_date = today
        title = "Last 7 Days"
    else:  # month
        start_date = today - datetime.timedelta(days=30)
        end_date = today
        title = "Last 30 Days"
    
    # Get entries from database
    entries_by_date = db.get_entries_by_date_range(user_id, start_date, end_date)
    
    if not entries_by_date:
        await query.edit_message_text(
            f"📊 **{title}**\n\n_No entries found for this period._",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_to_history")]])
        )
        return VIEW_HISTORY
    
    # Format the display
    message = f"📊 **Entry History - {title}**\n{'='*30}\n\n"
    
    for date_str, day_data in entries_by_date.items():
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        day_name = date_obj.strftime('%A')
        
        # Check completion
        total_landmarks = len(db.get_routine_landmarks(user_id))
        completed_landmarks = len([e for e in day_data['entries'] if e['landmark_name'] != "Ad-Hoc"])
        has_evening = day_data['has_evening_summary']
        
        completion_icon = "✅" if completed_landmarks >= total_landmarks else "⚠️"
        evening_icon = "🎙" if has_evening else "➖"
        
        message += f"**{date_obj.strftime('%b %d')}** ({day_name}) {completion_icon}\n"
        message += f"Morning: {completed_landmarks}/{total_landmarks} landmarks | Evening: {evening_icon}\n\n"
        
        # Show landmark statuses
        for entry in day_data['entries']:
            icon = "🟢" if entry['status'] == "Healthy" else "🔴" if entry['status'] == "Issue" else "🟠"
            note_icon = "📝" if entry['has_note'] else ""
            message += f"  {icon} {entry['landmark_name']}: {entry['status']} {note_icon}\n"
        
        message += "\n"
    
    # Add navigation buttons
    kb = []
    for date_str in list(entries_by_date.keys())[:5]:  # Show first 5 dates as quick access
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        kb.append([InlineKeyboardButton(
            f"📸 View {date_obj.strftime('%b %d')}", 
            callback_data=f"view_date_{date_str}"
        )])
    
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="back_to_history")])
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

async def show_date_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed view with images for a specific date"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    date_str = query.data.replace('view_date_', '')
    
    entries = db.get_entries_for_date(user_id, date_str)
    
    if not entries:
        await query.edit_message_text("No entries found.")
        return VIEW_HISTORY
    
    # Send images as media groups per landmark
    for entry in entries:
        media_group = []
        files_to_close = []
        
        try:
            # Add images to media group
            for img_type in ['wide', 'close', 'soil']:
                img_path = getattr(entry, f'img_{img_type}', None)
                if img_path and os.path.exists(img_path):
                    fh = open(img_path, 'rb')
                    files_to_close.append(fh)
                    caption = f"{entry.landmark.label} - {img_type.capitalize()}" if not media_group else ""
                    media_group.append(InputMediaPhoto(fh, caption=caption))
            
            if media_group:
                await query.message.reply_media_group(media_group)
                
                # Send status info
                icon = "🟢" if entry.status == "Healthy" else "🔴" if entry.status == "Issue" else "🟠"
                
                # Format timestamp for context
                entry_time = entry.timestamp.strftime('%I:%M %p')
                
                status_msg = f"{icon} **{entry.landmark.label}**: {entry.status}\n"
                status_msg += f"🕐 Logged at {entry_time}\n"
                
                # Replace "Current:" with "Weather:" for historical entries
                weather_display = entry.weather_summary.replace("Current:", "Weather:")
                status_msg += f"🌡️ {weather_display}\n"
                
                if entry.voice_path and os.path.exists(entry.voice_path):
                    status_msg += "📝 Voice note attached\n"
                
                await query.message.reply_text(status_msg, parse_mode='Markdown')
                
                # Send voice note if exists
                if entry.voice_path and os.path.exists(entry.voice_path):
                    with open(entry.voice_path, 'rb') as vf:
                        await query.message.reply_voice(vf)
                        
        except Exception as e:
            logger.error(f"Error sending media: {e}")
        finally:
            for fh in files_to_close:
                fh.close()
    
    # Back button
    kb = [[InlineKeyboardButton("◀️ Back to History", callback_data="back_to_history")]]
    await query.message.reply_text(
        "─────────────────",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return VIEW_HISTORY

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
        await update.message.reply_text("✅ **Saved!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    except ValueError: return L_COUNT

# --- EDITING HANDLERS ---
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
    if update.message:
        if not await ensure_registered(update, context): return ConversationHandler.END
    
    user_id = update.effective_user.id
    
    # NEW: Check if routine is already done today
    if is_routine_done(user_id, 'morning'):
        await update.message.reply_text(
            "✅ **Morning Check-in Complete**\n"
            "You have already checked all spots today.\n\n"
            "💡 **Tip:** Send photos directly to this chat to save them as **Ad-Hoc** observations.",
            parse_mode='Markdown', reply_markup=MAIN_MENU_KBD
        )
        return ConversationHandler.END

    # Use only routine landmarks for collection flow
    landmarks = db.get_routine_landmarks(user_id)
    if not landmarks: return ConversationHandler.END
    
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
        summary = "📊 **Daily Farm Status**\n━━━━━━━━━━━━━━━━\n"
        for lm in context.user_data['landmarks']:
            icon = "🟢" if lm.last_status == "Healthy" else "🔴" if lm.last_status == "Issue" else "🟠"
            summary += f"{icon} **{lm.label}:** {lm.last_status}\n"
        
        await msg_obj.reply_text(summary, parse_mode='Markdown')
        await msg_obj.reply_text("✅ **All Done!**", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
    
    lm = context.user_data['landmarks'][idx]
    
    # Clear, step-by-step instructions
    msg = (
        f"📍 **{lm.label}** ({idx+1}/{len(context.user_data['landmarks'])})\n\n"
        f"📸 **Step 1 of 3: Wide Shot**\n\n"
        f"Take a photo showing the overall area of this landmark.\n"
        f"_Tap the 📎 button → Camera → Take photo_"
    )
    
    await msg_obj.reply_text(msg, parse_mode='Markdown')
    return CAPTURE_WIDE

async def handle_photo_step(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_step):
    if not update.message.photo: return None
    
    # Show processing message immediately
    processing_msg = await update.message.reply_text("📤 _Uploading..._", parse_mode='Markdown')
    
    f = await update.message.photo[-1].get_file()
    user = db.get_user_profile(update.effective_user.id)
    path = await f.download_to_drive(f"data/media/{user.id}_temp_{key}.jpg")
    context.user_data['temp_photos'][key] = path
    
    # Delete processing message
    await processing_msg.delete()
    
    # Confirm receipt and guide next step
    if key == 'wide':
        await update.message.reply_text("✅ Wide shot saved!\n\n📸 **Step 2 of 3: Close-up**\n\nZoom in on the plants/crops.", parse_mode='Markdown')
    elif key == 'close':
        await update.message.reply_text("✅ Close-up saved!\n\n📸 **Step 3 of 3: Soil/Base**\n\nPhoto of the ground or base area.", parse_mode='Markdown')
    
    if next_step == CONFIRM_SET:
        # Show final processing message
        review_msg = await update.message.reply_text("📋 _Preparing review..._", parse_mode='Markdown')
        
        media_group = []
        files_to_close = []
        try:
            for k in ['wide', 'close', 'soil']:
                p = context.user_data['temp_photos'].get(k)
                if p:
                    fh = open(p, 'rb')
                    files_to_close.append(fh)
                    media_group.append(InputMediaPhoto(fh, caption=f"{k.capitalize()} View"))
            if media_group: 
                await update.message.reply_media_group(media_group)
                await review_msg.delete()
        except Exception as e: 
            logger.error(f"Album error: {e}")
            await review_msg.edit_text("⚠️ _Error loading preview_", parse_mode='Markdown')
        finally: 
            for fh in files_to_close: fh.close()

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
        # IMPROVED: Show two clear options instead of just skip
        kb = [
            [InlineKeyboardButton("🎙 Add Voice Note", callback_data="add_voice_note")],
            [InlineKeyboardButton("➡️ Skip Note", callback_data="skip_note")]
        ]
        await query.edit_message_text(
            f"⚠️ Marked **{status}**\n\n"
            "Would you like to add details about this issue?", 
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
        return ADD_NOTE

async def prompt_for_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User chose to add a voice note - prompt them to record"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎙 **Recording Mode**\n\n"
        "Tap the microphone button below and describe the issue.\n\n"
        "_I'm listening..._",
        parse_mode='Markdown'
    )
    return ADD_NOTE

async def handle_landmark_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.voice: 
        await update.message.reply_text("Please send a voice note or use /cancel to stop.")
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
        with open(p, 'rb') as f: 
            saved_paths[k] = save_telegram_file(f, user.id, user.farm_name, lm.id, k)
        if os.path.exists(p): os.remove(p)
    
    if voice_file:
        v_path = save_telegram_file(voice_file, user.id, user.farm_name, lm.id, "issue_note")
        saved_paths['voice_path'] = v_path
        
    db.create_entry(user.id, lm.id, saved_paths, status, context.user_data.get('weather', {}))

# --- EVENING ---
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        if not await ensure_registered(update, context): return ConversationHandler.END

    user_id = update.effective_user.id

    # NEW: Check if routine is already done
    if is_routine_done(user_id, 'evening'):
        await update.message.reply_text(
            "✅ **Evening Summary Recorded**\n"
            "You have already recorded your summary for today.\n\n"
            "🎙 **Tip:** Just send a voice note directly if you forgot something.",
            parse_mode='Markdown', reply_markup=MAIN_MENU_KBD
        )
        return ConversationHandler.END

    await update.message.reply_text("🎙 **Recording...**\nTap mic to record.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return VOICE_RECORD

async def save_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.voice: return VOICE_RECORD
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    user = db.get_user_profile(update.effective_user.id)
    
    # Save to file using utility
    saved_path = save_telegram_file(buf, user.id, user.farm_name, 0, "daily_summary")
    
    # Save to DB (Fix: Ensure evening summaries are logged)
    # Using save_evening_summary from database.py instead of create_entry with id 0
    db.save_evening_summary(user.id, saved_path)
    await update.message.reply_text("✅ **Summary Saved.**", parse_mode='Markdown', reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

# --- WEATHER CHECK ---
async def check_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display current weather and forecast for the farm"""
    user = await ensure_registered(update, context)
    if not user: return
    
    # Show loading message
    loading_msg = await update.message.reply_text("🌦 _Fetching weather data..._", parse_mode='Markdown')
    
    # Get weather
    weather = get_weather_data(user.latitude, user.longitude)
    
    await loading_msg.delete()
    
    if not weather:
        await update.message.reply_text(
            "⚠️ Unable to fetch weather data at the moment.\nPlease try again later.",
            reply_markup=MAIN_MENU_KBD
        )
        return
    
    # Format detailed weather message
    msg = "🌦 **Farm Weather Report**\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Current conditions
    msg += f"🌡️ **Temperature:** {weather['temp']}°C\n"
    msg += f"   └ Feels like: {weather['temp_min']}°C - {weather['temp_max']}°C\n\n"
    
    msg += f"☁️ **Condition:** {weather['desc'].capitalize()}\n\n"
    
    msg += f"💧 **Humidity:** {weather['humidity']}%\n"
    msg += f"🌬️ **Wind:** {weather['wind_speed']} m/s"
    
    if weather.get('wind_deg'):
        # Convert wind degree to direction
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        idx = round(weather['wind_deg'] / 45) % 8
        msg += f" ({directions[idx]})"
    
    msg += f"\n🔽 **Pressure:** {weather['pressure']} hPa\n\n"
    
    # Forecast
    if weather.get('forecast_temp'):
        msg += f"📅 **Next Forecast:** {weather['forecast_temp']}°C\n\n"
    
    # Farming tips based on conditions
    msg += "🌾 **Farm Tips:**\n"
    
    if weather['temp'] > 35:
        msg += "• ⚠️ High heat - ensure adequate irrigation\n"
    elif weather['temp'] < 10:
        msg += "• ⚠️ Cold weather - protect sensitive crops\n"
    
    if weather['humidity'] > 80:
        msg += "• 💧 High humidity - watch for fungal issues\n"
    elif weather['humidity'] < 30:
        msg += "• 🌵 Low humidity - increase watering\n"
    
    if weather['wind_speed'] > 10:
        msg += "• 🌬️ Strong winds - check plant supports\n"
    
    if not any([weather['temp'] > 35, weather['temp'] < 10, weather['humidity'] > 80, weather['humidity'] < 30, weather['wind_speed'] > 10]):
        msg += "• ✅ Good conditions for farming!\n"
    
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
        await update.message.reply_text(
            "**Farm AI Assistant Help** 🌾\n\n"
            "**Main Features:**\n"
            "📸 Morning Check-in - Capture farm status\n"
            "🎙 Evening Summary - Record daily notes\n"
            "📊 View History - See past entries\n"
            "👤 Dashboard - Manage your profile\n"
            "🌦 Check Weather - Current conditions & forecast\n\n"
            "**Quick Actions:**\n"
            "• Send any photo → Quick snapshot\n"
            "• Send any voice → Quick note\n\n"
            "Use /cancel to stop any action.",
            reply_markup=MAIN_MENU_KBD,
            parse_mode='Markdown'
        )
        return

    if update.message.photo or update.message.voice:
        user = await ensure_registered(update, context)
        if not user: return

        buf = io.BytesIO()
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
            
        # FIX: Log Adhoc to Database
        # 1. Get/Create Ad-Hoc Landmark
        lm_id = db.get_or_create_adhoc_landmark(user.id)
        
        # 2. Create Entry
        db.create_entry(user.id, lm_id, saved_paths, f"Ad-Hoc {ftype}", {})

# --- BUILD ---
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
        entry_points=[
            CommandHandler('profile', view_profile), 
            CallbackQueryHandler(edit_name_start, pattern="^edit_name$"), 
            CallbackQueryHandler(edit_sched_start, pattern="^edit_sched$"), 
            MessageHandler(filters.Regex("^👤 Dashboard$"), view_profile)
        ],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT, edit_name_save)], 
            EDIT_SCHED_M: [MessageHandler(filters.TEXT, edit_sched_m)], 
            EDIT_SCHED_E: [MessageHandler(filters.TEXT, edit_sched_save)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    collection = ConversationHandler(
        entry_points=[
            CommandHandler('collection', start_collection), 
            CallbackQueryHandler(start_collection, pattern="^start_collection$"), 
            MessageHandler(filters.Regex("^📸 Start Morning Check-in$"), start_collection)
        ],
        states={
            CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide)],
            CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close)],
            CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil)],
            CONFIRM_SET: [CallbackQueryHandler(handle_confirmation)],
            LOG_STATUS: [CallbackQueryHandler(log_status)],
            ADD_NOTE: [
                MessageHandler(filters.VOICE, handle_landmark_note), 
                CallbackQueryHandler(prompt_for_voice_note, pattern="^add_voice_note$"),
                CallbackQueryHandler(skip_landmark_note, pattern="^skip_note$")
            ]
        }, 
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    evening = ConversationHandler(
        entry_points=[
            CommandHandler('record', start_evening_flow), 
            CallbackQueryHandler(start_evening_flow, pattern="^start_evening$"), 
            MessageHandler(filters.Regex("^🎙 Record Evening Summary$"), start_evening_flow)
        ],
        states={VOICE_RECORD: [MessageHandler(filters.VOICE, save_voice_note)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    history = ConversationHandler(
        entry_points=[
            CommandHandler('history', view_history),
            MessageHandler(filters.Regex("^📊 View History$"), view_history)
        ],
        states={
            VIEW_HISTORY: [
                CallbackQueryHandler(view_history, pattern="^back_to_history$"),
                CallbackQueryHandler(show_history_period, pattern="^hist_"),
                CallbackQueryHandler(show_date_details, pattern="^view_date_")
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(onboard)
    app.add_handler(edit_profile)
    app.add_handler(collection)
    app.add_handler(evening)
    app.add_handler(history)
    app.add_handler(CommandHandler('weather', check_weather))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VOICE, handle_adhoc_media))
    
    print("🤖 Farm Diary Bot LIVE (Clean & Robust).")
    app.run_polling()