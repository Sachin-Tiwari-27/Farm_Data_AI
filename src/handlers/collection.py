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
(CAPTURE_FLUID, CONFIRM_PHOTOS, LOG_STATUS, VOICE_LOOP) = range(4)

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
    
    # 1. DELTA CHECK: What is actually pending?
    pending_ids = db.get_pending_landmark_ids(user_id)
    all_landmarks = db.get_user_landmarks(user_id)
    
    # Filter full objects based on pending IDs
    pending_landmarks = [lm for lm in all_landmarks if lm.id in pending_ids]
    
    if not pending_landmarks:
        # ALL DONE SCENARIO
        kb = [[InlineKeyboardButton("🔄 Re-run All Spots", callback_data="rerun_all")]]
        await update.message.reply_text(
            "✅ **All Caught Up!**\nAll spots have been logged today.", 
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode='Markdown'
        )
        return ConversationHandler.END # We handle rerun via callback, but need a persistent listener? 
        # Actually, if we return END, we can't capture the callback. 
        # So we return a specific state OR we rely on the router.
        # Let's make a specific mini-state for this menu or just send message.
        # Better: Send message, if they click rerun, it triggers a command that forces full list.
    
    # Initialize Session
    context.user_data.update({
        'queue': pending_landmarks,
        'current_ptr': 0,
        'temp_photos': [],
        'temp_voices': [],
        'temp_status': None,
        'msg_id': None
    })
    
    user = db.get_user_profile(user_id)
    weather = get_weather_data(user.latitude, user.longitude)
    context.user_data['weather'] = weather or {}
    
    await update.message.reply_text(
        f"🌦 **Weather:** {weather.get('desc', 'N/A')} ({weather.get('temp', 'N/A')}°C)\n"
        f"📝 **{len(pending_landmarks)} spots** remaining.", 
        parse_mode='Markdown', reply_markup=ReplyKeyboardRemove()
    )
    return await request_next_landmark(update, context)

async def request_next_landmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ptr = context.user_data['current_ptr']
    queue = context.user_data['queue']
    
    if ptr >= len(queue):
        await context.bot.send_message(update.effective_chat.id, "🎉 **Check-in Complete!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    
    lm = queue[ptr]
    
    # Clean Previous Session Data
    context.user_data['temp_photos'] = []
    context.user_data['temp_voices'] = []
    context.user_data['temp_status'] = None
    
    msg = await context.bot.send_message(
        update.effective_chat.id,
        f"📍 **{lm.label}**\n"
        f"🏠 {lm.env} | 🌱 {lm.medium}\n"
        f"────────────────\n"
        f"📸 **Add Photos** (Select multiple or send one by one).", 
        parse_mode='Markdown'
    )
    context.user_data['msg_id'] = msg.message_id
    return CAPTURE_FLUID

# --- FLUID PHOTO BUFFER ---

async def handle_photo_fluid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return CAPTURE_FLUID
    
    f = await update.message.photo[-1].get_file()
    user = db.get_user_profile(update.effective_user.id)
    
    # Save to temp
    idx = len(context.user_data['temp_photos']) + 1
    path = await f.download_to_drive(f"data/media/{user.id}_temp_p{idx}.jpg")
    context.user_data['temp_photos'].append(path)
    
    # Update Counter Message
    count = len(context.user_data['temp_photos'])
    
    kb = [[InlineKeyboardButton("✅ Done / Next", callback_data="photos_done")]]
    
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['msg_id'],
            text=f"📥 **Received {count} photo(s).**\nSend more or tap Done.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    except Exception: pass
    
    return CAPTURE_FLUID

# --- STATUS ---

async def finish_photos_ask_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = [
        [InlineKeyboardButton("🟢 Healthy", callback_data="Healthy")],
        [InlineKeyboardButton("🔴 Issue", callback_data="Issue"), InlineKeyboardButton("🟠 Unsure", callback_data="Unsure")]
    ]
    await query.edit_message_text("📊 **Assessment?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return LOG_STATUS

async def log_status_start_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data
    context.user_data['temp_status'] = status
    
    # Prompt for Voice based on status
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
    await query.edit_message_text(f"{msg}\n🎙 **Record Voice Note(s)** or tap Finish.", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VOICE_LOOP

# --- INFINITE VOICE LOOP ---

async def handle_voice_infinite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    
    context.user_data['temp_voices'].append(buf)
    count = len(context.user_data['temp_voices'])
    
    kb = [[InlineKeyboardButton("✅ Finish Spot", callback_data="voice_done")]]
    await update.message.reply_text(f"🎙 **Note {count} saved.** Add another or Finish.", reply_markup=InlineKeyboardMarkup(kb))
    return VOICE_LOOP

async def guard_voice_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Graceful fail if they type text instead of voice."""
    await update.message.reply_text("⚠️ **Expecting Voice Note.**\nRecord a note or tap **Finish** to move on.")
    return VOICE_LOOP

# --- FINALIZATION ---

async def finalize_spot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user_profile(update.effective_user.id)
    queue = context.user_data['queue']
    ptr = context.user_data['current_ptr']
    lm = queue[ptr]
    
    saved_paths = {}
    
    # Process Photos
    for i, p in enumerate(context.user_data['temp_photos']):
        with open(p, 'rb') as f: 
            saved_paths[f"photo_{i}"] = save_telegram_file(f, user.id, user.farm_name, lm.id, f"p{i}")
        try: os.remove(p)
        except: pass
        
    # Process Voices
    bg_voice_paths = []
    for i, v_buf in enumerate(context.user_data['temp_voices']):
        v_path = save_telegram_file(v_buf, user.id, user.farm_name, lm.id, f"note_{i}")
        saved_paths[f"voice_{i}"] = v_path
        bg_voice_paths.append(v_path)
    
    t_status = "⏳ Transcribing..." if bg_voice_paths else ""
    
    entry_id = db.create_entry(
        user.id, lm.id, saved_paths, 
        context.user_data['temp_status'], 
        context.user_data.get('weather', {}), 
        transcription=t_status
    )
    
    # Launch BG Tasks for ALL voices
    for v_path in bg_voice_paths:
        context.application.create_task(run_transcription_bg(v_path, entry_id))
        
    await query.edit_message_text(f"✅ **Saved: {lm.label}**")
    
    # Next
    context.user_data['current_ptr'] += 1
    return await request_next_landmark(update, context)

# --- EVENING FLOW (Simplified) ---
# ... (Evening flow can remain similar but update fallbacks) ...
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db.is_routine_done(update.effective_user.id, 'evening'):
        await update.message.reply_text("✅ **Evening Summary Done.**", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
    await update.message.reply_text("🎙 **Evening Summary**\nRecord your daily observations.", reply_markup=ReplyKeyboardRemove())
    return VOICE_LOOP # Re-use the loop logic? Or keep simple. Let's keep simple for now.

async def save_evening_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    user = db.get_user_profile(update.effective_user.id)
    saved_path = save_telegram_file(buf, user.id, user.farm_name, 0, "daily_summary")
    entry_id = db.create_entry(user.id, 0, {"voice_path": saved_path}, "Summary", {}, transcription="⏳ Transcribing...")
    context.application.create_task(run_transcription_bg(saved_path, entry_id))
    await update.message.reply_text("✅ **Saved.**", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

# --- EXPORT ---
collection_handler = ConversationHandler(
    entry_points=[CommandHandler('collection', start_collection), MessageHandler(filters.Regex("^📸 Start Morning Check-in$"), start_collection)],
    states={
        CAPTURE_FLUID: [
            MessageHandler(filters.PHOTO, handle_photo_fluid),
            CallbackQueryHandler(finish_photos_ask_status, pattern="photos_done")
        ],
        LOG_STATUS: [CallbackQueryHandler(log_status_start_voice)],
        VOICE_LOOP: [
            MessageHandler(filters.VOICE, handle_voice_infinite),
            CallbackQueryHandler(finalize_spot, pattern="voice_done"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, guard_voice_input)
        ]
    },
    fallbacks=[
        CommandHandler('cancel', start_collection),
        MessageHandler(filters.TEXT, route_intent)
    ]
)

evening_handler = ConversationHandler(
    entry_points=[CommandHandler('record', start_evening_flow), MessageHandler(filters.Regex("^🎙 Record Evening Summary$"), start_evening_flow)],
    states={VOICE_LOOP: [MessageHandler(filters.VOICE, save_evening_note)]}, # Re-using state constant
    fallbacks=[MessageHandler(filters.TEXT, route_intent)]
)