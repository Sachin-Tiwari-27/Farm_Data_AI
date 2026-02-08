import os
import logging
from dotenv import load_dotenv

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ConversationHandler, CallbackQueryHandler, filters, ContextTypes, Application
)

# Internal Modules
import database as db
from weather import get_weather_data
from utils.validators import parse_time
from utils.files import save_telegram_file

# Load Environment
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- STATE DEFINITIONS ---
# Onboarding (0-5)
NAME, FARM, LOCATION, P_TIME, V_TIME, L_COUNT = range(6)

# Collection (6-11)
(
    L_START,        
    CAPTURE_WIDE,   
    CAPTURE_CLOSE,  
    CAPTURE_SOIL,   
    CONFIRM_SET,    
    LOG_STATUS      
) = range(6, 12)

# --- MENU SETUP ---
async def post_init(application: Application):
    """Sets the menu button commands when bot starts."""
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home / Register"),
        BotCommand("collection", "📸 Morning Check-in"),
        BotCommand("profile", "👤 View My Details"),
        BotCommand("cancel", "❌ Stop Current Action")
    ])

# --- COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point."""
    user = db.get_user_profile(update.effective_user.id)
    
    if user:
        await update.message.reply_text(
            f"👋 **Welcome back, {user.full_name}!**\n"
            f"🌱 **Farm:** {user.farm_name}\n\n"
            "**Quick Actions:**\n"
            "/collection - Start Morning Check-in\n"
            "/profile - View Details\n"
            "/update_profile - Edit Settings",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
        
    await update.message.reply_text(
        "👋 **Welcome to Farm Diary AI.**\nLet's set up your digital profile.\n\n"
        "Step 1: What is your **Full Name**?",
        parse_mode='Markdown'
    )
    return NAME

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the user profile."""
    user = db.get_user_profile(update.effective_user.id)
    if not user:
        await update.message.reply_text("⚠️ No profile found. Please run /start.")
        return

    # Fetch fresh landmarks
    landmarks = db.get_user_landmarks(user.id)
    lm_text = "\n".join([f"   • {lm.label}: {lm.last_status}" for lm in landmarks]) if landmarks else "   No landmarks set."

    msg = (
        f"👤 **Farmer Profile**\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"**Name:** {user.full_name}\n"
        f"**Farm:** {user.farm_name}\n"
        f"**Location:** {user.latitude:.4f}, {user.longitude:.4f}\n\n"
        f"⏰ **Schedule:**\n"
        f"   • Photos: {user.photo_time}\n"
        f"   • Voice: {user.voice_time}\n\n"
        f"📍 **Landmarks ({len(landmarks)}):**\n"
        f"{lm_text}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers the onboarding flow again."""
    await update.message.reply_text("⚙️ **Updating Profile**\nLet's re-enter your details.")
    await update.message.reply_text("Step 1: What is your **Full Name**?", parse_mode='Markdown')
    return NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Action cancelled. Type /start to return home.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- ONBOARDING CONVERSATION ---

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Step 2: What is the **Name of your Farm**?", parse_mode='Markdown')
    return FARM

async def get_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['farm'] = update.message.text
    kb = [[KeyboardButton("📍 Share Farm Location", request_location=True)]]
    await update.message.reply_text(
        "Step 3: Tap the button below to share the **Farm's Location**.",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='Markdown'
    )
    return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    context.user_data['lat'] = loc.latitude
    context.user_data['lon'] = loc.longitude
    await update.message.reply_text(
        "✅ Location verified.\n\n"
        "Step 4: Time for **Morning Photos**?\n(e.g., type '7' for 07:00 or '7:30')", 
        reply_markup=ReplyKeyboardRemove(), 
        parse_mode='Markdown'
    )
    return P_TIME

async def get_p_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=False)
    if not t:
        await update.message.reply_text("Invalid format. Try '7' or '07:00'.")
        return P_TIME
    context.user_data['p_time'] = t
    await update.message.reply_text(
        "Step 5: Time for **Evening Voice Summary**?\n(e.g., type '6' for 18:00 or '6:30')", 
        parse_mode='Markdown'
    )
    return V_TIME

async def get_v_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=True)
    if not t:
        await update.message.reply_text("Invalid format. Try '6' or '18:00'.")
        return V_TIME
    context.user_data['v_time'] = t
    kb = [["3", "4", "5"]]
    await update.message.reply_text(
        "Step 6: How many **Landmarks** (specific spots) to track?", 
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True), 
        parse_mode='Markdown'
    )
    return L_COUNT

async def get_l_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if count < 3 or count > 5: raise ValueError
        
        data = {
            'id': update.effective_user.id,
            'name': context.user_data['name'],
            'farm': context.user_data['farm'],
            'lat': context.user_data['lat'],
            'lon': context.user_data['lon'],
            'p_time': context.user_data['p_time'],
            'v_time': context.user_data['v_time'],
            'l_count': count
        }
        db.save_user_profile(data)
        
        await update.message.reply_text(
            "✅ **Profile Saved!**\n\n"
            "I am ready. Use /collection to start a morning check-in.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("Please select 3, 4, or 5.")
        return L_COUNT

# --- COLLECTION CONVERSATION (MODULE 2) ---

async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    landmarks = db.get_user_landmarks(user_id)
    
    if not landmarks:
        await update.message.reply_text("⚠️ No landmarks found. Run /update_profile first.")
        return ConversationHandler.END
        
    context.user_data['landmarks'] = landmarks
    context.user_data['current_idx'] = 0
    context.user_data['temp_photos'] = {}
    
    user = db.get_user_profile(user_id)
    weather = get_weather_data(user.latitude, user.longitude)
    context.user_data['weather'] = weather or {}
    
    w_str = weather['display_str'] if weather else "Offline"
    await update.message.reply_text(f"🌦 **Weather:** {w_str}", parse_mode='Markdown')
    
    return await request_landmark_photos(update, context)

async def request_landmark_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data['current_idx']
    landmarks = context.user_data['landmarks']
    
    # Handle CallbackQuery vs Message trigger
    if update.callback_query:
        msg_obj = update.callback_query.message
    else:
        msg_obj = update.message

    if idx >= len(landmarks):
        await msg_obj.reply_text("✅ **Check-in Complete!** See you this evening.")
        return ConversationHandler.END
        
    lm = landmarks[idx]
    
    await msg_obj.reply_text(
        f"📍 **{lm.label}** ({idx+1}/{len(landmarks)})\n"
        f"Last Status: {lm.last_status}\n\n"
        "1️⃣ **WIDE SHOT**\n"
        "Tap the 📎 (Paperclip) or 📷 icon to take a photo.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return CAPTURE_WIDE

async def handle_photo_step(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_step, next_prompt):
    """Generic handler with CRITICAL FIX for await get_file()."""
    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a photo.")
        return None

    # --- THE FIX IS HERE ---
    # We must await get_file() because it's an async coroutine
    photo_file = await update.message.photo[-1].get_file() 
    
    path = await photo_file.download_to_drive(f"data/media/{update.effective_user.id}_temp_{key}.jpg")
    context.user_data['temp_photos'][key] = path
    
    if next_step == CONFIRM_SET:
        kb = [
            [InlineKeyboardButton("✅ Confirm Photos", callback_data="confirm_set")],
            [InlineKeyboardButton("🔄 Retake Landmark", callback_data="retake_set")]
        ]
        await update.message.reply_text("Photos captured. Look good?", reply_markup=InlineKeyboardMarkup(kb))
        return CONFIRM_SET
    
    await update.message.reply_text(next_prompt, parse_mode='Markdown')
    return next_step

async def handle_wide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_photo_step(
        update, context, 'wide', CAPTURE_CLOSE, 
        "2️⃣ **CLOSE-UP**\nNow take a photo of the leaves or fruit."
    )

async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_photo_step(
        update, context, 'close', CAPTURE_SOIL, 
        "3️⃣ **SOIL / BASE**\nFinally, a photo of the roots/soil."
    )

async def handle_soil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_photo_step(update, context, 'soil', CONFIRM_SET, "")

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "retake_set":
        await query.edit_message_text("Okay, restarting this landmark.")
        return await request_landmark_photos(update, context)
        
    if query.data == "confirm_set":
        kb = [
            [InlineKeyboardButton("🟢 Healthy", callback_data="Healthy")],
            [InlineKeyboardButton("🔴 Issue / Pest", callback_data="Issue")],
            [InlineKeyboardButton("🟠 Not Sure", callback_data="Unsure")]
        ]
        await query.edit_message_text("How does it look today?", reply_markup=InlineKeyboardMarkup(kb))
        return LOG_STATUS

async def log_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data
    
    # Save Logic
    user_id = update.effective_user.id
    lm_idx = context.user_data['current_idx']
    lm_id = context.user_data['landmarks'][lm_idx].id
    
    saved_paths = {}
    for p_type, temp_path in context.user_data['temp_photos'].items():
        # Open temp file and pass to util
        with open(temp_path, 'rb') as f:
            final_path = save_telegram_file(f, user_id, lm_id, p_type)
            saved_paths[p_type] = final_path
        
        # Cleanup Temp
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    db.create_entry(
        user_id, lm_id, saved_paths, status, 
        context.user_data.get('weather', {})
    )
    
    await query.edit_message_text(f"✅ Saved Landmark {lm_idx + 1} as **{status}**.", parse_mode='Markdown')
    context.user_data['current_idx'] += 1
    return await request_landmark_photos(update, context)

if __name__ == '__main__':
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN not found in .env")
        exit(1)
        
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    # 1. Onboarding
    # Note: filters.TEXT & ~filters.COMMAND prevents "/profile" from being captured as a name
    onboard_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start), CommandHandler('update_profile', update_profile)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            FARM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_farm)],
            LOCATION: [MessageHandler(filters.LOCATION, get_location)],
            P_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_p_time)],
            V_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_time)],
            L_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_l_count)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # 2. Collection
    collection_handler = ConversationHandler(
        entry_points=[CommandHandler('collection', start_collection)],
        states={
            CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide)],
            CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close)],
            CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil)],
            CONFIRM_SET: [CallbackQueryHandler(handle_confirmation)],
            LOG_STATUS: [CallbackQueryHandler(log_status)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(onboard_handler)
    app.add_handler(collection_handler)
    app.add_handler(CommandHandler("profile", view_profile))
    
    print("🤖 Farm Diary Bot is LIVE. Press Ctrl+C to stop.")
    app.run_polling()