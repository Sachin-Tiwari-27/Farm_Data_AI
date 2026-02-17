import os
import logging
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from utils.files import save_telegram_file
from utils.transcriber import transcribe_audio
from utils.weather import get_weather_data
from utils.ai_agent.ai_agent import ask_ai
from utils.menus import MAIN_MENU_KBD, BTN_AI
from handlers.router import route_intent

logger = logging.getLogger(__name__)

# --- STATES ---
AI_PHOTO, AI_CONTEXT = range(2)
AI_FEEDBACK_NOTE = 3

# --- ENTRY POINT ---
async def start_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # Clear previous data for a clean start
    context.user_data.clear()
    context.user_data['ai_photos'] = []
    
    await update.message.reply_text(
        "🤖 **Ask AI**\n"
        "I can help you with your farm.\n\n"
        "📸 **First, send a photo of the crop/issue.**\n\n"
        "_(Or type 'skip' if you just want to ask a text question)_",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return AI_PHOTO

# --- STEP 1: HANDLE PHOTO ---
async def handle_ai_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Save Photo to list
    f = await update.message.photo[-1].get_file()
    idx = len(context.user_data.get('ai_photos', []))
    path = f"data/media/{user_id}_ai_q{idx}.jpg"
    await f.download_to_drive(path)
    
    if 'ai_photos' not in context.user_data:
        context.user_data['ai_photos'] = []
    context.user_data['ai_photos'].append(path)
    
    await update.message.reply_text(
        "✅ Photo received.\n\n"
        "**Now, describe the problem.**\n"
        "Record a 🎙 **Voice Note** or type a **Message**.\n"
        "_(You can also send more photos if needed)_",
        parse_mode='Markdown'
    )
    return AI_CONTEXT

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👌 No photo.\n\n"
        "**Describe your question.**\n"
        "Record a 🎙 **Voice Note** or type a **Message**.\n\n"
        "_Or type **'skip'** if you only want to ask a text question._",
        parse_mode='Markdown'
    )
    return AI_CONTEXT

async def handle_ai_photo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text during the AI photo stage."""
    text = update.message.text.strip().lower()
    
    # 1. Check for Skip
    if text in ['skip', '/skip']:
        return await skip_photo(update, context)
        
    # 2. Check for Menu Switch
    res = await route_intent(update, context)
    if res is not None:
        return res
        
    # 3. Invalid Text - Remind User
    await update.message.reply_text(
        "📸 **Ask AI: Photo Required**\n"
        "Please send a photo of the crop/issue.\n\n"
        "💡 _Or type **'skip'** if you only want to ask a text question._",
        parse_mode='Markdown'
    )
    return AI_PHOTO

# --- STEP 2: HANDLE CONTEXT & EXECUTE ---
async def handle_ai_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user_profile(user_id)
    
    # Notify immediately
    status_msg = await update.message.reply_text("⏳ **Analyzing...**")

    # 1. Get the Text Prompt (Transcribe if Voice)
    user_query = ""
    
    if update.message.voice:
        # Handle Voice
        f = await update.message.voice.get_file()
        voice_path = f"data/media/{user_id}_ai_voice.ogg"
        await f.download_to_drive(voice_path)
        
        # Transcribe (awaiting the async function we fixed earlier)
        user_query = await transcribe_audio(voice_path)
        
        # Cleanup voice file immediately
        try:
            if os.path.exists(voice_path):
                os.remove(voice_path)
        except:
            pass

        if not user_query:
            user_query = "Analyze this image and identify issues." # Fallback
    else:
        # Handle Text
        user_query = update.message.text
    
    # 2. Get the Photos
    image_paths = context.user_data.get('ai_photos', [])
    has_photo = len(image_paths) > 0

    # VALIDATION: Prevent wasteful API calls
    # If no photo and query is empty or 'skip', abort.
    is_empty_query = not user_query or user_query.strip().lower() in ['skip', '/skip', 'nothing', 'none']
    
    if not has_photo and is_empty_query:
        # Cleanup status message
        await status_msg.edit_text("❌ **Request Cancelled.**\n\nYou need to provide either a photo or a specific question for the AI to help you.")
        await update.message.reply_text("Returning to main menu.", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END

    # 3. Context Data
    location = {'lat': user.latitude, 'lon': user.longitude}
    weather = get_weather_data(user.latitude, user.longitude)

    # 4. Trigger Background Task
    context.application.create_task(
        run_ai_job(
            status_msg, 
            user_query, 
            image_paths, 
            user_id, 
            weather, 
            location
        )
    )

    # Return to Main Menu immediately
    await update.message.reply_text(
        "✅ **Request sent.** I'll ping you with the results shortly.",
        reply_markup=MAIN_MENU_KBD
    )
    return ConversationHandler.END

async def run_ai_job(msg_obj, query_text, images, user_id, weather, location):
    """Running in background to avoid blocking"""
    try:
        # Call the Agent
        response = await ask_ai(query_text, images, weather, location)
        
        result_text = response['text']
        model = response['model_used']
        
        # Log to DB and get ID
        log_id = db.log_ai_interaction(user_id, query_text, result_text, model)
        
        # 5. Deliver Result as New Message
        final_msg = f"🤖 **AI Insight:**\n\n{result_text}"
        
        # Try sending main message
        try:
            await msg_obj.chat.send_message(final_msg, parse_mode='Markdown')
        except Exception:
            try:
                await msg_obj.chat.send_message(final_msg, parse_mode='Markdown')
            except Exception:
                await msg_obj.chat.send_message(final_msg)
            
        # Optional: Delete the "Analyzing..." message
        try:
            await msg_obj.delete()
        except:
            pass
        
        # 6. SEND FEEDBACK PROMPT
        fb_kb = [
            [
                InlineKeyboardButton("👍 Good", callback_data=f"fb_{log_id}_good"),
                InlineKeyboardButton("🆗 OK", callback_data=f"fb_{log_id}_ok"),
                InlineKeyboardButton("👎 Bad", callback_data=f"fb_{log_id}_bad")
            ]
        ]
        await msg_obj.chat.send_message(
            "How was this response? 👇",
            reply_markup=InlineKeyboardMarkup(fb_kb)
        )
        
        # Cleanup temp files
        for img in images:
            if os.path.exists(img):
                try: os.remove(img)
                except: pass
            
    except Exception as e:
        logger.error(f"AI Job failed: {e}")
        try:
            await msg_obj.chat.send_message(f"⚠️ AI Failed: {str(e)}")
        except:
            pass

# --- FEEDBACK HANDLERS ---

async def handle_feedback_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    # data format: fb_{log_id}_{status}
    parts = data.split('_')
    log_id = parts[1]
    status = parts[2]
    
    # Update DB
    db.update_ai_feedback(log_id, status)
    
    # Store ID in context
    context.user_data['fb_log_id'] = log_id
    context.user_data['fb_status'] = status
    
    # Ask for note
    kb = [[InlineKeyboardButton("⏭ Skip Note", callback_data="fb_skip_note")]]
    await query.edit_message_text(
        f"✅ Feedback: **{status.title()}** saved.\n\n"
        "Would you like to add any details? (Voice/Text)",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )
    return AI_FEEDBACK_NOTE

async def handle_feedback_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_id = context.user_data.get('fb_log_id')
    status = context.user_data.get('fb_status')
    
    if not log_id:
        return ConversationHandler.END
        
    note = ""
    if update.message and update.message.voice:
        # Handle voice note feedback
        f = await update.message.voice.get_file()
        path = f"data/media/{update.effective_user.id}_fb_voice.ogg"
        await f.download_to_drive(path)
        note = await transcribe_audio(path)
        try: os.remove(path)
        except: pass
    elif update.message and update.message.text:
        note = update.message.text
    
    if note:
        db.update_ai_feedback(log_id, status, note)
        await update.message.reply_text("🙏 Thank you for your feedback!")
    
    return ConversationHandler.END

async def handle_ai_extra_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle supplemental photos sent during the context stage."""
    f = await update.message.photo[-1].get_file()
    user_id = update.effective_user.id
    idx = len(context.user_data.get('ai_photos', []))
    path = f"data/media/{user_id}_ai_q{idx}.jpg"
    await f.download_to_drive(path)
    context.user_data['ai_photos'].append(path)
    # Don't spam, just stay in context state
    return AI_CONTEXT

async def skip_feedback_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ Feedback saved.")
    return ConversationHandler.END


# --- HANDLER DEFINITIONS ---

ai_feedback_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(handle_feedback_click, pattern="^fb_")],
    states={
        AI_FEEDBACK_NOTE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback_note),
            MessageHandler(filters.VOICE, handle_feedback_note),
            CallbackQueryHandler(skip_feedback_note, pattern="^fb_skip_note$")
        ]
    },
    fallbacks=[
        CommandHandler('cancel', lambda u,c: ConversationHandler.END),
        MessageHandler(filters.TEXT, route_intent) # Menu items exit flow
    ],
    per_chat=True,
    per_user=True
)

# --- HANDLER DEFINITION ---
ai_handler = ConversationHandler(
    entry_points=[
        CommandHandler('ask', start_ai_chat),
        MessageHandler(filters.Regex(f"^{BTN_AI}$"), start_ai_chat)
    ],
    states={
        AI_PHOTO: [
            MessageHandler(filters.PHOTO, handle_ai_photo), 
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_photo_text)
        ],
        AI_CONTEXT: [
            MessageHandler(filters.PHOTO, handle_ai_extra_photo),
            MessageHandler(filters.VOICE, handle_ai_context),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_context)
        ]
    },
    fallbacks=[
        CommandHandler('cancel', lambda u,c: ConversationHandler.END),
        MessageHandler(filters.TEXT & filters.Regex("^❌ Cancel$"), lambda u,c: ConversationHandler.END),
        MessageHandler(filters.TEXT, route_intent)
    ],
    per_chat=True,
    per_user=True
)