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
from utils.menus import MAIN_MENU_KBD

logger = logging.getLogger(__name__)

(ADHOC_BUFFER, ADHOC_TAG) = range(2)

async def run_transcription_bg(file_path, entry_id):
    if not file_path or not os.path.exists(file_path): return
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, file_path)
        if text: db.update_transcription(entry_id, text)
    except Exception: pass

async def start_adhoc_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    context.user_data['adhoc_photos'] = []
    context.user_data['adhoc_voices'] = []
    context.user_data['msg_id'] = None
    
    # Initial prompt with Skip button only
    msg = (
        "📝 **Ad-Hoc Entry**\n"
        "────────────────\n"
        "Send **Photo(s)** 📸 and/or **Voice Note(s)** 🎙.\n\n"
        "You can send multiple items - I'll group them together."
    )
    kb = [[InlineKeyboardButton("⏭ Skip (No Entry)", callback_data="adhoc_skip")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ADHOC_BUFFER

async def start_adhoc_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    context.user_data['adhoc_photos'] = []
    context.user_data['adhoc_voices'] = []
    context.user_data['msg_id'] = None
    
    if update.message.photo: return await buffer_photo(update, context)
    elif update.message.voice: return await buffer_voice(update, context)
    return ADHOC_BUFFER

# --- REACTIVE BUFFER ---

async def update_buffer_ui(update, context):
    p_count = len(context.user_data['adhoc_photos'])
    v_count = len(context.user_data['adhoc_voices'])
    
    # Delete old status to keep chat clean
    if context.user_data.get('msg_id'):
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data['msg_id'])
        except Exception: pass
    
    # Build dynamic message based on what was received
    items = []
    if p_count > 0: items.append(f"**{p_count} Photo{'s' if p_count > 1 else ''}** 📸")
    if v_count > 0: items.append(f"**{v_count} Voice Note{'s' if v_count > 1 else ''}** 🎙")
    
    if items:
        msg = f"✅ **Received:** {' + '.join(items)}\n\n"
        # Suggest what they can add next
        if p_count > 0 and v_count == 0:
            msg += "💡 You can add voice notes too 🎙, or tap Done."
        elif v_count > 0 and p_count == 0:
            msg += "💡 You can add photos too 📸, or tap Done."
        else:
            msg += "📎 Add more or tap Done to save."
        
        kb = [
            [InlineKeyboardButton("➕ Add More", callback_data="add_more")],
            [InlineKeyboardButton("✅ Done", callback_data="adhoc_done")]
        ]
    else:
        # Shouldn't happen, but just in case
        msg = "📎 Send photos or voice notes."
        kb = [[InlineKeyboardButton("⏭ Skip", callback_data="adhoc_skip")]]
    
    new_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=msg,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )
    context.user_data['msg_id'] = new_msg.message_id

async def buffer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return ADHOC_BUFFER
    
    user_id = update.effective_user.id
    f = await update.message.photo[-1].get_file()
    idx = len(context.user_data['adhoc_photos'])
    path = await f.download_to_drive(f"data/media/{user_id}_adhoc_p{idx}.jpg")
    context.user_data['adhoc_photos'].append(path)
    
    await update_buffer_ui(update, context)
    return ADHOC_BUFFER

async def buffer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.voice: return ADHOC_BUFFER

    f = await update.message.voice.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    context.user_data['adhoc_voices'].append(buf)
    
    await update_buffer_ui(update, context)
    return ADHOC_BUFFER

async def handle_add_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicked 'Add More' button - show clear prompt for more content"""
    query = update.callback_query
    await query.answer()
    
    # Get current counts
    p_count = len(context.user_data['adhoc_photos'])
    v_count = len(context.user_data['adhoc_voices'])
    
    # Build summary
    items = []
    if p_count > 0: items.append(f"**{p_count} Photo{'s' if p_count > 1 else ''}** 📸")
    if v_count > 0: items.append(f"**{v_count} Voice Note{'s' if v_count > 1 else ''}** 🎙")
    
    msg = f"✅ **Current:** {' + '.join(items)}\n\n📎 **Send more photos or voice notes...**"
    
    # Show Skip button to allow canceling
    kb = [[InlineKeyboardButton("⏭ Skip / Done", callback_data="adhoc_done")]]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    # Update msg_id so next item replaces this message
    context.user_data['msg_id'] = query.message.message_id
    
    # Stay in ADHOC_BUFFER state
    return ADHOC_BUFFER

async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicked Skip - cancel the ad-hoc entry"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ **Ad-hoc entry cancelled.**")
    await query.message.reply_text("Use the menu below 👇 for other options", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

async def ask_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Check if user sent anything
    p_count = len(context.user_data.get('adhoc_photos', []))
    v_count = len(context.user_data.get('adhoc_voices', []))
    
    if p_count == 0 and v_count == 0:
        await query.edit_message_text("❌ **No content to save.**\n\nYou didn't send any photos or voice notes.")
        await query.message.reply_text("Use the menu below:", reply_markup=MAIN_MENU_KBD)
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
    for i, p in enumerate(context.user_data['adhoc_photos']):
        with open(p, 'rb') as f:
            saved_paths[f"photo_{i}"] = save_telegram_file(f, user.id, user.farm_name, lm_id, f"adhoc_p{i}")
        try: os.remove(p)
        except: pass
        
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
    # Restore keyboard
    
    await query.message.reply_text("Use the menu below:", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

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
            CallbackQueryHandler(handle_add_more, pattern="add_more"),
            CallbackQueryHandler(handle_skip, pattern="adhoc_skip"),
            CallbackQueryHandler(ask_tag, pattern="adhoc_done"),
            MessageHandler(filters.TEXT, route_intent)
        ],
        ADHOC_TAG: [CallbackQueryHandler(finalize_adhoc, pattern="^tag_")]
    },
    fallbacks=[
        CommandHandler('cancel', start_adhoc_menu),
        MessageHandler(filters.TEXT, route_intent)
    ],
    
)