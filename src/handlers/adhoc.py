import os
import io
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, CommandHandler, filters

import database as db
from utils.files import save_telegram_file
from utils.transcriber import transcribe_audio
from utils.weather import get_weather_data
from handlers.router import route_intent

logger = logging.getLogger(__name__)

# --- STATES ---
(ADHOC_BUFFER, ADHOC_TAG) = range(2)

# --- WORKER ---
async def run_transcription_bg(file_path, entry_id):
    if not file_path or not os.path.exists(file_path): return
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, file_path)
        if text: db.update_transcription(entry_id, text)
    except Exception as e: logger.error(e)

# --- ENTRY ---
async def start_adhoc_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['adhoc_photos'] = []
    context.user_data['adhoc_voices'] = []
    
    msg = "📝 **Ad-Hoc Entry**\n\n📥 **Drop Zone Active:**\nSend Photos 📸 and Voice Notes 🎙 in any order.\nTap **Done** when finished."
    kb = [[InlineKeyboardButton("✅ Done / Tag", callback_data="adhoc_done")]]
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ADHOC_BUFFER

async def start_adhoc_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Initializes buffer with the first item received
    context.user_data['adhoc_photos'] = []
    context.user_data['adhoc_voices'] = []
    
    if update.message.photo:
        return await buffer_photo(update, context)
    elif update.message.voice:
        return await buffer_voice(update, context)
    return ADHOC_BUFFER

# --- BUFFER LOGIC ---

async def buffer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    f = await update.message.photo[-1].get_file()
    idx = len(context.user_data['adhoc_photos'])
    path = await f.download_to_drive(f"data/media/{user_id}_adhoc_p{idx}.jpg")
    context.user_data['adhoc_photos'].append(path)
    return await update_buffer_status(update, context)

async def buffer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    context.user_data['adhoc_voices'].append(buf)
    return await update_buffer_status(update, context)

async def update_buffer_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p_count = len(context.user_data['adhoc_photos'])
    v_count = len(context.user_data['adhoc_voices'])
    
    msg = f"📥 **Buffer:** {p_count} Photos | {v_count} Notes.\nSend more or tap Done."
    kb = [[InlineKeyboardButton("✅ Done / Tag", callback_data="adhoc_done")]]
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ADHOC_BUFFER

# --- TAGGING ---

async def ask_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Check emptiness
    if not context.user_data['adhoc_photos'] and not context.user_data['adhoc_voices']:
        await query.edit_message_text("❌ Empty. Cancelled.")
        return ConversationHandler.END

    user_id = query.from_user.id
    landmarks = db.get_user_landmarks(user_id)
    
    kb = []
    row = []
    for lm in landmarks:
        row.append(InlineKeyboardButton(f"📍 {lm.label}", callback_data=f"tag_{lm.id}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("🌍 General / No Tag", callback_data="tag_99")])
    
    await query.edit_message_text("🏷 **Tag this Entry:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ADHOC_TAG

async def finalize_adhoc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lm_id = int(query.data.split('_')[1])
    user_id = query.from_user.id
    user = db.get_user_profile(user_id)
    
    saved_paths = {}
    
    # Save Photos
    for i, p in enumerate(context.user_data['adhoc_photos']):
        with open(p, 'rb') as f:
            saved_paths[f"photo_{i}"] = save_telegram_file(f, user.id, user.farm_name, lm_id, f"adhoc_p{i}")
        try: os.remove(p)
        except: pass
        
    # Save Voices
    bg_voices = []
    for i, buf in enumerate(context.user_data['adhoc_voices']):
        path = save_telegram_file(buf, user.id, user.farm_name, lm_id, f"adhoc_note{i}")
        saved_paths[f"voice_{i}"] = path
        bg_voices.append(path)
        
    entry_id = db.create_entry(
        user.id, lm_id, saved_paths, "Observation", 
        get_weather_data(user.latitude, user.longitude), 
        transcription="⏳ Transcribing..." if bg_voices else ""
    )
    
    for v in bg_voices:
        context.application.create_task(run_transcription_bg(v, entry_id))
        
    await query.edit_message_text("✅ **Ad-Hoc Entry Saved.**")
    return ConversationHandler.END

# --- EXPORT ---
adhoc_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^📝 Quick Ad-Hoc Note$"), start_adhoc_menu),
        MessageHandler(filters.PHOTO, start_adhoc_direct),
        MessageHandler(filters.VOICE, start_adhoc_direct)
    ],
    states={
        ADHOC_BUFFER: [
            MessageHandler(filters.PHOTO, buffer_photo),
            MessageHandler(filters.VOICE, buffer_voice),
            CallbackQueryHandler(ask_tag, pattern="adhoc_done")
        ],
        ADHOC_TAG: [CallbackQueryHandler(finalize_adhoc, pattern="^tag_")]
    },
    fallbacks=[
        CommandHandler('cancel', start_adhoc_menu),
        MessageHandler(filters.TEXT & ~filters.COMMAND, route_intent)
    ]
)