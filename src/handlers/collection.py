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

(CAPTURE_WIDE, CAPTURE_CLOSE, CAPTURE_SOIL, CONFIRM_PHOTOS, LOG_STATUS, VOICE_LOOP) = range(6)

async def run_transcription_bg(file_path, entry_id):
    if not file_path or not os.path.exists(file_path): return
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, file_path)
        if text: db.update_transcription(entry_id, text)
    except Exception: pass

async def save_temp_photo(update, context, key):
    try:
        os.makedirs("data/media", exist_ok=True)
        f = await update.message.photo[-1].get_file()
        path = f"data/media/{update.effective_user.id}_temp_{key}.jpg"
        await f.download_to_drive(path)
        context.user_data['temp_photos'][key] = path
        return True
    except Exception as e:
        logger.error(f"Save Error: {e}")
        return False

async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 1. GATEKEEPER CHECK
    user = db.get_user_profile(user_id)
    if not user:
        await update.message.reply_text(
            "⚠️ **Registration Required**\n\n"
            "I don't see your farm profile yet.\n"
            "Please tap /start to set up your farm.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    context.user_data.clear()
    
    pending_ids = db.get_pending_landmark_ids(user_id)
    if not pending_ids:
        await update.message.reply_text("✅ **All Morning Tasks Done!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END

    all_landmarks = db.get_user_landmarks(user_id)
    context.user_data['queue'] = [lm for lm in all_landmarks if lm.id in pending_ids]
    context.user_data['current_ptr'] = 0
    context.user_data['temp_photos'] = {}
    context.user_data['temp_voices'] = []
    
    user = db.get_user_profile(user_id)
    weather = get_weather_data(user.latitude, user.longitude)
    context.user_data['weather'] = weather or {}
    
    await update.message.reply_text(f"📝 **Starting Check-in** ({len(context.user_data['queue'])} spots).", parse_mode='Markdown')
    return await ask_wide_shot(update, context)

async def ask_wide_shot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    queue = context.user_data['queue']
    ptr = context.user_data['current_ptr']
    
    # Determine the message object to use
    if update.callback_query:
        msg = update.callback_query.message
    else:
        msg = update.message
    
    if ptr >= len(queue):
        await msg.reply_text("🎉 **Check-in Complete!**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
        return ConversationHandler.END
    
    lm = queue[ptr]
    context.user_data['temp_photos'] = {}
    context.user_data['temp_voices'] = []
    
    await msg.reply_text(f"📍 **{lm.label}**\n📸 Step 1: Send **Wide Shot** (Overall view).", parse_mode='Markdown')
    return CAPTURE_WIDE

async def handle_wide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return CAPTURE_WIDE
    await save_temp_photo(update, context, 'wide')
    await update.message.reply_text("✅ Received.\n📸 Step 2: Send **Close-up**.", parse_mode='Markdown')
    return CAPTURE_CLOSE

async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return CAPTURE_CLOSE
    await save_temp_photo(update, context, 'close')
    await update.message.reply_text("✅ Received.\n📸 Step 3: Send **Soil/Base**.", parse_mode='Markdown')
    return CAPTURE_SOIL

async def handle_soil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return CAPTURE_SOIL
    await save_temp_photo(update, context, 'soil')
    
    kb = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm_photos"), InlineKeyboardButton("🔄 Retake", callback_data="retake")]]
    await update.message.reply_text("✅ Photos done.", reply_markup=InlineKeyboardMarkup(kb))
    return CONFIRM_PHOTOS

async def handle_retake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔄 Restarting this spot...")
    return await ask_wide_shot(update, context)

async def ask_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("🟢 Healthy", callback_data="Healthy")], [InlineKeyboardButton("🔴 Issue", callback_data="Issue"), InlineKeyboardButton("🟠 Unsure", callback_data="Unsure")]]
    await query.edit_message_text("📊 **Assessment?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return LOG_STATUS

async def start_voice_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['temp_status'] = query.data
    kb = [[InlineKeyboardButton("➡️ Skip Note", callback_data="voice_done")]]
    await query.edit_message_text("🎙 **Record Note** (or Skip).", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VOICE_LOOP

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    context.user_data['temp_voices'].append(buf)
    kb = [[InlineKeyboardButton("✅ Finish Spot", callback_data="voice_done")]]
    await update.message.reply_text("🎙 **Saved.**", reply_markup=InlineKeyboardMarkup(kb))
    return VOICE_LOOP

async def finalize_spot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user_profile(update.effective_user.id)
    lm = context.user_data['queue'][context.user_data['current_ptr']]
    
    saved_paths = {}
    for k, p in context.user_data['temp_photos'].items():
        with open(p, 'rb') as f: saved_paths[k] = save_telegram_file(f, user.id, user.farm_name, lm.id, k)
    
    bg_voices = []
    for i, v_buf in enumerate(context.user_data['temp_voices']):
        path = save_telegram_file(v_buf, user.id, user.farm_name, lm.id, f"note_{i}")
        saved_paths[f"voice_{i}"] = path
        bg_voices.append(path)
        
    entry_id = db.create_entry(
        user.id, lm.id, saved_paths, 
        context.user_data['temp_status'], 
        context.user_data.get('weather', {}),
        transcription="⏳ Transcribing..." if bg_voices else ""
    )
    
    for v in bg_voices:
        context.application.create_task(run_transcription_bg(v, entry_id))

    await query.edit_message_text(f"✅ **Saved: {lm.label}**")
    context.user_data['current_ptr'] += 1
    return await ask_wide_shot(update, context)

# --- EVENING HANDLER ---
async def start_evening_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 1. GATEKEEPER CHECK
    user = db.get_user_profile(user_id)
    if not user:
        await update.message.reply_text(
            "⚠️ **Registration Required**\n\n"
            "I don't see your farm profile yet.\n"
            "Please tap /start to set up your farm.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    context.user_data.clear()
    if db.is_routine_done(user_id, 'evening'):
        await update.message.reply_text("✅ **Evening Summary Done.**", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
    await update.message.reply_text("🎙 **Evening Summary**\nRecord your daily observations.", parse_mode='Markdown')
    return VOICE_LOOP

async def save_evening_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    user = db.get_user_profile(update.effective_user.id)
    saved_path = save_telegram_file(buf, user.id, user.farm_name, 0, "daily_summary")
    entry_id = db.create_entry(user.id, 0, {"voice_path": saved_path}, "Summary", {}, transcription="⏳ Transcribing...")
    context.application.create_task(run_transcription_bg(saved_path, entry_id))
    
    await update.message.reply_text("✅ **Summary Saved.**", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

async def skip_evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Cancelled.")
    # Restore keyboard
    await query.message.reply_text("Use the menu below:", reply_markup=MAIN_MENU_KBD)
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
)