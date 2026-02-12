import os
import io
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from utils.files import save_telegram_file
from utils.transcriber import transcribe_audio
from utils.weather import get_weather_data
from utils.menus import MAIN_MENU_KBD
from handlers.router import route_intent

logger = logging.getLogger(__name__)

# --- STATES ---
(CAPTURE_WIDE, CAPTURE_CLOSE, CAPTURE_SOIL, 
 CONFIRM_SET, LOG_STATUS, ADD_NOTE, VOICE_RECORD) = range(7)

# --- BACKGROUND WORKER ---
async def run_transcription_bg(file_path, entry_id):
    if not file_path or not os.path.exists(file_path): return
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, file_path)
        if text: db.update_transcription(entry_id, text)
    except Exception as e:
        logger.error(f"BG Whisper Error: {e}")

# --- MORNING FLOW ---

async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.is_routine_done(user_id, 'morning'):
         await update.message.reply_text("✅ **Morning Routine Done.**\nUse Ad-Hoc for extras.", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
         return ConversationHandler.END

    landmarks = db.get_user_landmarks(user_id)
    if not landmarks:
        await update.message.reply_text("⚠️ No spots configured.", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END

    context.user_data.update({
        'landmarks': landmarks,
        'current_idx': 0,
        'temp_photos': {},
        'temp_status': None,
        'msg_id': None # For editing
    })
    
    user = db.get_user_profile(user_id)
    weather = get_weather_data(user.latitude, user.longitude)
    context.user_data['weather'] = weather or {}
    
    await update.message.reply_text(
        f"🌦 **Weather:** {weather.get('desc', 'N/A')} ({weather.get('temp', 'N/A')}°C)\nStarting check-in...", 
        parse_mode='Markdown', reply_markup=ReplyKeyboardRemove()
    )
    return await request_landmark_photos(update, context)

async def request_landmark_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handles loop reset
    idx = context.user_data['current_idx']
    landmarks = context.user_data['landmarks']
    
    if idx >= len(landmarks):
        await context.bot.send_message(update.effective_chat.id, "🎉 **All Spots Checked!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    
    lm = landmarks[idx]
    
    # New Message for new spot
    msg = await context.bot.send_message(
        update.effective_chat.id,
        f"📍 **{lm.label}** ({idx+1}/{len(landmarks)})\n"
        f"🏠 {lm.env} | 🌱 {lm.medium}\n"
        f"────────────────\n"
        f"📸 **Step 1/3:** Send Wide Shot.", 
        parse_mode='Markdown'
    )
    context.user_data['msg_id'] = msg.message_id
    context.user_data['temp_photos'] = {} # Reset
    return CAPTURE_WIDE

# --- PHOTO STEPS (Feedback Loop) ---

async def handle_photo_step(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_step):
    if not update.message.photo: return None
    
    f = await update.message.photo[-1].get_file()
    user = db.get_user_profile(update.effective_user.id)
    path = await f.download_to_drive(f"data/media/{user.id}_temp_{key}.jpg")
    
    context.user_data['temp_photos'][key] = path
    
    # Progress Bar Text Logic
    idx = context.user_data['current_idx']
    lm = context.user_data['landmarks'][idx]
    
    base_txt = f"📍 **{lm.label}** ({idx+1}/{len(context.user_data['landmarks'])})\n🏠 {lm.env} | 🌱 {lm.medium}\n────────────────\n"
    
    status_txt = ""
    if 'wide' in context.user_data['temp_photos']: status_txt += "✅ Wide Shot received.\n"
    if 'close' in context.user_data['temp_photos']: status_txt += "✅ Close-up received.\n"
    if 'soil' in context.user_data['temp_photos']: status_txt += "✅ Soil shot received.\n"
    
    next_instr = ""
    if key == 'wide': next_instr = "📸 **Step 2/3:** Send Close-up."
    elif key == 'close': next_instr = "📸 **Step 3/3:** Send Soil/Base shot."
    
    # Edit the prompt message
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['msg_id'],
            text=f"{base_txt}{status_txt}{next_instr}",
            parse_mode='Markdown'
        )
    except Exception: pass # Ignore edit errors if message too old
    
    # Delete the user's photo message to keep chat clean? (Optional, skipping for now)

    if next_step == CONFIRM_SET:
        kb = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm"), InlineKeyboardButton("🔄 Retake", callback_data="retake")]]
        await update.message.reply_text("Photos clear?", reply_markup=InlineKeyboardMarkup(kb))
    
    return next_step

async def handle_wide(update: Update, context: ContextTypes.DEFAULT_TYPE): return await handle_photo_step(update, context, 'wide', CAPTURE_CLOSE)
async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE): return await handle_photo_step(update, context, 'close', CAPTURE_SOIL)
async def handle_soil(update: Update, context: ContextTypes.DEFAULT_TYPE): return await handle_photo_step(update, context, 'soil', CONFIRM_SET)

# --- STATUS & NOTES ---

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "retake": 
        await query.edit_message_text("🔄 Restarting this spot...")
        return await request_landmark_photos(update, context)
        
    kb = [
        [InlineKeyboardButton("🟢 Healthy", callback_data="Healthy")],
        [InlineKeyboardButton("🔴 Issue", callback_data="Issue"), InlineKeyboardButton("🟠 Unsure", callback_data="Unsure")]
    ]
    await query.edit_message_text("How does it look?", reply_markup=InlineKeyboardMarkup(kb))
    return LOG_STATUS

async def log_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data
    context.user_data['temp_status'] = status
    
    # Dynamic Prompts
    if status == "Healthy":
        msg = "✅ **Marked Healthy.**\nAny observations to add? (Optional)"
        kb = [[InlineKeyboardButton("🎙 Add Note", callback_data="add_voice"), InlineKeyboardButton("⏩ Skip", callback_data="skip_note")]]
    elif status == "Issue":
        msg = "⚠️ **Issue Flagged.**\nWhat do you see? (e.g., 'Pests', 'Yellowing')\n*Voice Note Recommended.*"
        kb = [[InlineKeyboardButton("🎙 Describe Issue", callback_data="add_voice")]] # No skip for issue? Let's allow skip via text command if really needed, but push for voice.
        kb.append([InlineKeyboardButton("⏩ Skip (Not Recommended)", callback_data="skip_note")])
    else: # Unsure
        msg = "🟠 **Unsure.**\nDescribe what feels wrong or why you are suspicious."
        kb = [[InlineKeyboardButton("🎙 Explain", callback_data="add_voice"), InlineKeyboardButton("⏩ Skip", callback_data="skip_note")]]

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ADD_NOTE

async def prompt_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("🎙 **Listening...**\n(Tap the mic button)")
    return ADD_NOTE

async def handle_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    await finalize_landmark_entry(update, context, voice_file=buf)
    await update.message.reply_text("✅ Note Saved.")
    context.user_data['current_idx'] += 1
    return await request_landmark_photos(update, context)

async def skip_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await finalize_landmark_entry(update, context, voice_file=None)
    await query.edit_message_text("✅ Saved.")
    context.user_data['current_idx'] += 1
    return await request_landmark_photos(update, context)

# --- SAVING ---

async def finalize_landmark_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_file=None):
    user = db.get_user_profile(update.effective_user.id)
    lm = context.user_data['landmarks'][context.user_data['current_idx']]
    
    saved_paths = {}
    for k, p in context.user_data['temp_photos'].items():
        with open(p, 'rb') as f: saved_paths[k] = save_telegram_file(f, user.id, user.farm_name, lm.id, k)
        try: os.remove(p)
        except: pass
    
    bg_voice = None
    if voice_file:
        v_path = save_telegram_file(voice_file, user.id, user.farm_name, lm.id, "issue_note")
        saved_paths['voice_path'] = v_path
        bg_voice = v_path
    
    t_status = "⏳ Transcribing..." if bg_voice else ""
    entry_id = db.create_entry(user.id, lm.id, saved_paths, context.user_data['temp_status'], context.user_data.get('weather', {}), transcription=t_status)
    
    if bg_voice:
        context.application.create_task(run_transcription_bg(bg_voice, entry_id))

# --- EVENING FLOW (unchanged) ---
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db.is_routine_done(update.effective_user.id, 'evening'):
        await update.message.reply_text("✅ **Already Recorded.**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    await update.message.reply_text("🎙 **Evening Summary**\nRecord your daily observations.", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
    return VOICE_RECORD

async def save_evening_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    
    user = db.get_user_profile(update.effective_user.id)
    saved_path = save_telegram_file(buf, user.id, user.farm_name, 0, "daily_summary")
    
    entry_id = db.create_entry(user.id, 0, {"voice_path": saved_path}, "Summary", {}, transcription="⏳ Transcribing...")
    context.application.create_task(run_transcription_bg(saved_path, entry_id))
    
    await update.message.reply_text("✅ **Summary Saved.**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
    return ConversationHandler.END

# --- EXPORT HANDLERS ---
collection_handler = ConversationHandler(
    entry_points=[CommandHandler('collection', start_collection), MessageHandler(filters.Regex("^📸 Start Morning Check-in$"), start_collection)],
    states={
        CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide)],
        CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close)],
        CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil)],
        CONFIRM_SET: [CallbackQueryHandler(handle_confirmation)],
        LOG_STATUS: [CallbackQueryHandler(log_status)],
        ADD_NOTE: [MessageHandler(filters.VOICE, handle_note), CallbackQueryHandler(prompt_voice, pattern="^add_voice$"), CallbackQueryHandler(skip_note, pattern="^skip_note$")]
    },
    fallbacks=[
        CommandHandler('cancel', start_collection), 
        MessageHandler(filters.TEXT & ~filters.COMMAND, route_intent) 
    ]
)

evening_handler = ConversationHandler(
    entry_points=[CommandHandler('record', start_evening_flow), MessageHandler(filters.Regex("^🎙 Record Evening Summary$"), start_evening_flow)],
    states={VOICE_RECORD: [MessageHandler(filters.VOICE, save_evening_note)]},
    fallbacks=[MessageHandler(filters.TEXT, route_intent)]
)