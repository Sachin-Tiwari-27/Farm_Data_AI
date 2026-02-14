import os
import io
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from utils.files import save_telegram_file
from utils.transcriber import transcribe_audio
from utils.weather import get_weather_data
from utils.menus import MAIN_MENU_KBD
from handlers.router import route_intent

logger = logging.getLogger(__name__)

# --- STATES ---
(CAPTURE_WIDE, CAPTURE_CLOSE, CAPTURE_SOIL, CONFIRM_PHOTOS, LOG_STATUS, VOICE_LOOP) = range(6)

# --- HELPERS ---
async def run_transcription_bg(file_path, entry_id):
    if not file_path or not os.path.exists(file_path): return
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, file_path)
        if text: db.update_transcription(entry_id, text)
    except Exception: pass

# --- MORNING FLOW START ---
async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if not user or not user.landmarks:
        await update.message.reply_text("⚠️ You have no landmarks set up. Use /start to configure them.")
        return ConversationHandler.END

    # Initialize Queue
    context.user_data['queue'] = user.landmarks
    context.user_data['current_ptr'] = 0
    
    return await ask_wide_shot(update, context)

async def ask_wide_shot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    queue = context.user_data.get('queue')
    ptr = context.user_data.get('current_ptr')
    
    # Check if we are done
    if ptr >= len(queue):
        await update.effective_message.reply_text("✅ **All spots checked!** You are done for the morning.", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    
    lm = queue[ptr]
    # Reset temp storage for this specific spot
    context.user_data['temp_photos'] = {}
    context.user_data['temp_voices'] = []
    context.user_data['weather'] = get_weather_data(db.get_user_profile(update.effective_user.id).latitude, db.get_user_profile(update.effective_user.id).longitude)
    
    msg_text = (
        f"📍 **Spot {ptr+1}/{len(queue)}: {lm.label}**\n"
        f"🌱 Env: {lm.env}\n"
        f"📸 **Step 1:** Take a **Wide Shot**."
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        
    return CAPTURE_WIDE

# --- PHOTO HANDLERS ---
async def save_temp_photo(update, context, key):
    try:
        f = await update.message.photo[-1].get_file()
        path = f"data/media/{update.effective_user.id}_temp_{key}.jpg"
        os.makedirs("data/media", exist_ok=True)
        await f.download_to_drive(path)
        context.user_data['temp_photos'][key] = path
    except Exception as e:
        logger.error(f"Photo save error: {e}")

async def handle_wide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_temp_photo(update, context, "wide")
    await update.message.reply_text("📸 **Step 2:** Now take a **Close-up** (leaves/fruit).")
    return CAPTURE_CLOSE

async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_temp_photo(update, context, "close")
    await update.message.reply_text("📸 **Step 3:** Finally, take a **Soil/Base** photo.")
    return CAPTURE_SOIL

async def handle_soil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_temp_photo(update, context, "soil")
    
    # Review Keyboard
    kb = [
        [InlineKeyboardButton("✅ Confirm Photos", callback_data="confirm_photos")],
        [InlineKeyboardButton("🔄 Retake", callback_data="retake")]
    ]
    await update.message.reply_text("Photos captured. Proceed?", reply_markup=InlineKeyboardMarkup(kb))
    return CONFIRM_PHOTOS

async def handle_retake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("🔄 Restarting this spot. Please send the **Wide Shot** again.")
    return CAPTURE_WIDE

# --- STATUS & VOICE ---
async def ask_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = [
        [InlineKeyboardButton("🟢 Healthy", callback_data="Healthy")],
        [InlineKeyboardButton("🔴 Issue", callback_data="Issue")],
        [InlineKeyboardButton("🟠 Unsure", callback_data="Unsure")]
    ]
    await query.edit_message_text("🩺 **What is the status of this spot?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return LOG_STATUS

async def start_voice_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['temp_status'] = query.data
    
    kb = [[InlineKeyboardButton("⏭️ Skip / Done", callback_data="voice_done")]]
    await query.edit_message_text(
        f"Selected: **{query.data}**\n\n🎙 **Voice Notes:**\nRecord observations now. You can send multiple.\nPress Done when finished.",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )
    return VOICE_LOOP

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    context.user_data['temp_voices'].append(buf)
    await update.message.reply_text("🎤 Note saved. Record another or press **Skip/Done**.", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip / Done", callback_data="voice_done")]]))
    return VOICE_LOOP

# --- FINALIZE SPOT ---
async def finalize_spot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user_profile(update.effective_user.id)
    
    # Get the current landmark
    lm = context.user_data['queue'][context.user_data['current_ptr']]
    
    # Save Photos
    saved_paths = {}
    for k, p in context.user_data['temp_photos'].items():
        with open(p, 'rb') as f:
            saved_paths[k] = save_telegram_file(f, user.id, user.farm_name, lm.id, k)
        # Cleanup temp
        try: os.remove(p)
        except: pass
    
    # Save Voices
    bg_voices = []
    for i, v_buf in enumerate(context.user_data['temp_voices']):
        path = save_telegram_file(v_buf, user.id, user.farm_name, lm.id, f"note_{i}")
        saved_paths[f"voice_{i}"] = path
        bg_voices.append(path)
        
    # --- DB CALL (SQLite) ---
    entry_id = db.create_entry(
        user.id, lm.id, saved_paths, 
        context.user_data['temp_status'], 
        context.user_data.get('weather', {}),
        category='morning' 
    )
    
    for v in bg_voices:
        context.application.create_task(run_transcription_bg(v, entry_id))

    await query.edit_message_text(f"✅ **Saved: {lm.label}**")
    context.user_data['current_ptr'] += 1
    return await ask_wide_shot(update, context)

# --- EVENING FLOW ---
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌙 **Evening Check-in**\n"
        "Please record a voice note summarizing your day (activities, issues, plans for tomorrow).",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return VOICE_LOOP

async def save_evening_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    user = db.get_user_profile(update.effective_user.id)
    
    saved_path = save_telegram_file(buf, user.id, user.farm_name, 0, "daily_summary")
    
    # --- DB CALL (SQLite) ---
    entry_id = db.create_entry(
        user.id, 0, {"voice_path": saved_path}, 
        "Summary", {}, 
        category='evening',
        transcription="⏳ Transcribing..."
    )
    
    context.application.create_task(run_transcription_bg(saved_path, entry_id))
    
    await update.message.reply_text("✅ **Summary Saved.**", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

async def skip_evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("❌ Cancelled.", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

# --- EXPORT HANDLERS ---
collection_handler = ConversationHandler(
    entry_points=[
        CommandHandler('collection', start_collection),
        MessageHandler(filters.Regex("^📸 Start Morning Check-in$"), start_collection)
    ],
    states={
        CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide), MessageHandler(filters.TEXT, route_intent)],
        CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close), MessageHandler(filters.TEXT, route_intent)],
        CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil), MessageHandler(filters.TEXT, route_intent)],
        CONFIRM_PHOTOS: [CallbackQueryHandler(ask_status, pattern="confirm_photos"), CallbackQueryHandler(handle_retake, pattern="retake")],
        LOG_STATUS: [CallbackQueryHandler(start_voice_loop)],
        VOICE_LOOP: [CallbackQueryHandler(finalize_spot, pattern="voice_done"), MessageHandler(filters.VOICE, handle_voice), MessageHandler(filters.TEXT, route_intent)]
    },
    fallbacks=[MessageHandler(filters.TEXT, route_intent)],
    per_message=False
)

evening_handler = ConversationHandler(
    entry_points=[
        CommandHandler('record', start_evening_flow),
        MessageHandler(filters.Regex("^🎙 Record Evening Summary$"), start_evening_flow)
    ],
    states={
        VOICE_LOOP: [
            CallbackQueryHandler(skip_evening, pattern="voice_done"),
            MessageHandler(filters.VOICE, save_evening_note),
            MessageHandler(filters.TEXT, route_intent)
        ]
    },
    fallbacks=[MessageHandler(filters.TEXT, route_intent)],
    per_chat=True
)