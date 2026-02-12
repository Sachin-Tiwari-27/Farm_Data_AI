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
ADHOC_WAIT_PHOTO, ADHOC_WAIT_VOICE, ADHOC_WAIT_PHOTO_REVERSE, ADHOC_WAIT_TAG = range(4)

# --- BACKGROUND WORKER ---
async def run_transcription_bg(file_path, entry_id):
    """Runs Whisper in a separate thread."""
    if not file_path or not os.path.exists(file_path): return

    logger.info(f"🧵 Starting BG Transcription for {entry_id}...")
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, file_path)
        if text:
            db.update_transcription(entry_id, text)
            logger.info(f"✅ BG Transcription done: {text[:20]}...")
    except Exception as e:
        logger.error(f"❌ BG Error: {e}")

# --- ENTRY POINTS ---

async def start_adhoc_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['adhoc_buffer'] = {}
    kb = [[InlineKeyboardButton("⏭ Skip Photo", callback_data="skip_photo")]]
    await update.message.reply_text(
        "📝 **Ad-Hoc Entry**\n📸 **Step 1:** Send a photo.", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )
    return ADHOC_WAIT_PHOTO

async def start_adhoc_direct_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['adhoc_buffer'] = {}
    return await process_adhoc_photo(update, context)

async def start_adhoc_direct_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['adhoc_buffer'] = {}
    return await process_adhoc_voice(update, context, is_first_step=True)

# --- MEDIA HANDLERS ---

async def process_adhoc_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    f = await update.message.photo[-1].get_file()
    path = await f.download_to_drive(f"data/media/{user_id}_temp_adhoc.jpg")
    context.user_data['adhoc_buffer']['adhoc_photo'] = path
    
    kb = [[InlineKeyboardButton("⏭ Skip Note", callback_data="skip_voice")]]
    await update.message.reply_text(
        "📸 Photo saved.\n🎙 **Step 2:** Add a voice note?", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )
    return ADHOC_WAIT_VOICE

async def skip_adhoc_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("⏭ Skip Note", callback_data="skip_voice")]]
    await query.edit_message_text(
        "⏩ Photo skipped.\n🎙 **Step 2:** Record a voice note?", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )
    return ADHOC_WAIT_VOICE

async def process_adhoc_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, is_first_step=False):
    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    context.user_data['adhoc_buffer']['voice_data'] = buf
    
    if is_first_step:
        kb = [[InlineKeyboardButton("⏭ Skip Photo", callback_data="skip_photo_reverse")]]
        await update.message.reply_text(
            "🎙 Note saved.\n📸 **Step 2:** Add a photo?", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
        return ADHOC_WAIT_PHOTO_REVERSE
    else:
        return await ask_landmark_tag(update, context)

async def skip_adhoc_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await ask_landmark_tag(update, context)

# --- REVERSE FLOW (Voice First) ---
async def process_adhoc_photo_reverse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    f = await update.message.photo[-1].get_file()
    path = await f.download_to_drive(f"data/media/{user_id}_temp_adhoc.jpg")
    context.user_data['adhoc_buffer']['adhoc_photo'] = path
    return await ask_landmark_tag(update, context)

async def skip_photo_reverse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await ask_landmark_tag(update, context)

# --- TAGGING LOGIC ---

async def ask_landmark_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks the user to link this note to a specific farm spot."""
    # FIX: Check if buffer is empty BEFORE asking for tags
    buffer = context.user_data.get('adhoc_buffer', {})
    if not buffer:
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ No photo or note added. Entry discarded.")
        else:
            await update.message.reply_text("❌ No photo or note added. Entry discarded.")
        return ConversationHandler.END

    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        user_id = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        user_id = update.effective_user.id
        
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
    
    await msg_func(
        "🏷 **Tag this observation:**\nSelect the spot this belongs to:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )
    return ADHOC_WAIT_TAG

async def finalize_adhoc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tag_data = query.data 
    landmark_id = int(tag_data.split('_')[1])
    
    user_id = query.from_user.id
    buffer = context.user_data.get('adhoc_buffer', {})
    
    user = db.get_user_profile(user_id)
    saved_paths = {}
    
    if 'adhoc_photo' in buffer:
        with open(buffer['adhoc_photo'], 'rb') as f:
            saved_paths['adhoc_photo'] = save_telegram_file(f, user.id, user.farm_name, landmark_id, "adhoc_photo")
        os.remove(buffer['adhoc_photo'])

    voice_path_for_bg = None
    if 'voice_data' in buffer:
        path = save_telegram_file(buffer['voice_data'], user.id, user.farm_name, landmark_id, "adhoc_voice")
        saved_paths['adhoc_voice'] = path
        voice_path_for_bg = path

    weather = get_weather_data(user.latitude, user.longitude) or {}
    
    transcription_status = "⏳ Transcribing..." if voice_path_for_bg else ""
    status = "Observation"
    
    entry_id = db.create_entry(
        user.id, 
        landmark_id, 
        saved_paths, 
        status, 
        weather, 
        transcription=transcription_status
    )
    
    if voice_path_for_bg:
        context.application.create_task(run_transcription_bg(voice_path_for_bg, entry_id))
    
    lm_label = "General"
    if landmark_id != 99:
        lm_obj = db.get_landmark_by_id(user_id, landmark_id)
        if lm_obj: lm_label = lm_obj.label
        
    await query.edit_message_text(
        f"✅ **Saved to {lm_label}.**\n\n Use 📝 Quick Ad-Hoc Note to add more notes.", 
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# --- EXPORT HANDLER ---
adhoc_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^📝 Quick Ad-Hoc Note$"), start_adhoc_menu),
        MessageHandler(filters.PHOTO, start_adhoc_direct_photo),
        MessageHandler(filters.VOICE, start_adhoc_direct_voice)
    ],
    states={
        # ... (keep states as is)
        ADHOC_WAIT_PHOTO: [
            MessageHandler(filters.PHOTO, process_adhoc_photo),
            CallbackQueryHandler(skip_adhoc_photo, pattern="^skip_photo$")
        ],
        ADHOC_WAIT_VOICE: [
            MessageHandler(filters.VOICE, process_adhoc_voice),
            CallbackQueryHandler(skip_adhoc_voice, pattern="^skip_voice$")
        ],
        ADHOC_WAIT_PHOTO_REVERSE: [
             MessageHandler(filters.PHOTO, process_adhoc_photo_reverse),
             CallbackQueryHandler(skip_photo_reverse, pattern="^skip_photo_reverse$")
        ],
        ADHOC_WAIT_TAG: [
            CallbackQueryHandler(finalize_adhoc, pattern="^tag_")
        ]
    },
    fallbacks=[
        CommandHandler('cancel', cancel),
        MessageHandler(filters.TEXT & ~filters.COMMAND, route_intent)
    ]
)