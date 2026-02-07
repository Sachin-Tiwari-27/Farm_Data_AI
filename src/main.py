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

import database as db
from weather import get_weather_data
from utils.validators import parse_time
from utils.files import save_telegram_file

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# States
NAME, FARM, LOCATION, P_TIME, V_TIME, L_COUNT = range(6)
(L_START, CAPTURE_WIDE, CAPTURE_CLOSE, CAPTURE_SOIL, CONFIRM_SET, LOG_STATUS) = range(6, 12)

# --- MENU ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home / Register"),
        BotCommand("collection", "📸 Morning Check-in"),
        BotCommand("profile", "👤 My Profile"),
        BotCommand("cancel", "❌ Stop Action")
    ])

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"👋 **Welcome back, {user.full_name}!**\n🌱 **Farm:** {user.farm_name}\n\n"
            "Tap 'Menu' or type:\n/collection - Start Check-in\n/profile - View Details",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    await update.message.reply_text("👋 **Welcome.** Let's set up your profile.\n\nStep 1: What is your **Full Name**?", parse_mode='Markdown')
    return NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if not user: return await start(update, context)
    landmarks = db.get_user_landmarks(user.id)
    lm_text = "\n".join([f"• {lm.label}: {lm.last_status}" for lm in landmarks])
    await update.message.reply_text(
        f"👤 **{user.full_name}** | 🌱 {user.farm_name}\n\n"
        f"⏰ Photos: {user.photo_time} | Voice: {user.voice_time}\n"
        f"📍 **Landmarks:**\n{lm_text}", parse_mode='Markdown'
    )

# --- ONBOARDING HANDLERS ---
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Step 2: What is the **Name of your Farm**?", parse_mode='Markdown')
    return FARM

async def get_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['farm'] = update.message.text
    kb = [[KeyboardButton("📍 Share Farm Location", request_location=True)]]
    await update.message.reply_text("Step 3: Share **Farm Location**.", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True), parse_mode='Markdown')
    return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    context.user_data['lat'], context.user_data['lon'] = loc.latitude, loc.longitude
    await update.message.reply_text(
        "Step 4: **Morning Photo Time**?\n(e.g., type '7' for 07:00 or '7:30')", 
        reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown'
    )
    return P_TIME

async def get_p_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=False)
    if not t:
        await update.message.reply_text("Invalid. Try '7' or '07:00'.")
        return P_TIME
    context.user_data['p_time'] = t
    await update.message.reply_text(
        "Step 5: **Evening Voice Time**?\n(e.g., type '6' for 18:00 or '6:30')", 
        parse_mode='Markdown'
    )
    return V_TIME

async def get_v_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=True)
    if not t:
        await update.message.reply_text("Invalid. Try '6' or '18:00'.")
        return V_TIME
    context.user_data['v_time'] = t
    kb = [["3", "4", "5"]]
    await update.message.reply_text("Step 6: How many **Landmarks**?", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True), parse_mode='Markdown')
    return L_COUNT

async def get_l_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if count not in [3,4,5]: raise ValueError
        db.save_user_profile({
            'id': update.effective_user.id,
            'name': context.user_data['name'], 'farm': context.user_data['farm'],
            'lat': context.user_data['lat'], 'lon': context.user_data['lon'],
            'p_time': context.user_data['p_time'], 'v_time': context.user_data['v_time'],
            'l_count': count
        })
        await update.message.reply_text("✅ **Setup Complete!**\nUse /collection to start.", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Please choose 3, 4, or 5.")
        return L_COUNT

# --- COLLECTION HANDLERS ---
async def start_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    landmarks = db.get_user_landmarks(user_id)
    if not landmarks: 
        await update.message.reply_text("⚠️ Run /start first.")
        return ConversationHandler.END
        
    context.user_data.update({'landmarks': landmarks, 'current_idx': 0, 'temp_photos': {}})
    # Fetch weather once
    weather = get_weather_data(db.get_user_profile(user_id).latitude, db.get_user_profile(user_id).longitude)
    context.user_data['weather'] = weather or {}
    
    await update.message.reply_text(f"🌦 **Weather:** {weather.get('display_str', 'N/A')}", parse_mode='Markdown')
    return await request_landmark_photos(update, context)

async def request_landmark_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data['current_idx']
    
    # --- CRASH FIX START ---
    # We check if this came from a button (CallbackQuery) or a command (Message)
    if update.callback_query:
        # If it's a button click, we use the message attached to the button
        message_obj = update.callback_query.message
    else:
        # If it's the first time (/collection), we use the standard message
        message_obj = update.message
    # --- CRASH FIX END ---

    if idx >= len(context.user_data['landmarks']):
        await message_obj.reply_text("✅ **All Done!** Check back in the evening.")
        return ConversationHandler.END
    
    lm = context.user_data['landmarks'][idx]
    await message_obj.reply_text(
        f"📍 **{lm.label}** ({idx+1}/{len(context.user_data['landmarks'])})\n"
        f"Last Status: {lm.last_status}\n\n"
        "1️⃣ **WIDE SHOT**\n"
        "Tap the 📎 or 📷 icon to take a photo.",
        parse_mode='Markdown', reply_markup=ReplyKeyboardRemove()
    )
    return CAPTURE_WIDE

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_step, prompt):
    # Ensure it's actually a photo
    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a photo.")
        return None
        
    path = await update.message.photo[-1].get_file()
    dest = f"data/media/{update.effective_user.id}_temp_{key}.jpg"
    await path.download_to_drive(dest)
    context.user_data['temp_photos'][key] = dest
    
    if next_step == CONFIRM_SET:
        kb = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm"), InlineKeyboardButton("🔄 Retake", callback_data="retake")]]
        await update.message.reply_text("Photos captured. Look good?", reply_markup=InlineKeyboardMarkup(kb))
        return CONFIRM_SET
    
    await update.message.reply_text(prompt, parse_mode='Markdown')
    return next_step

async def handle_wide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_photo(update, context, 'wide', CAPTURE_CLOSE, "2️⃣ **CLOSE-UP**\nNow take a photo of leaves/fruit.")

async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_photo(update, context, 'close', CAPTURE_SOIL, "3️⃣ **SOIL / BASE**\nFinally, a photo of the roots.")

async def handle_soil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_photo(update, context, 'soil', CONFIRM_SET, "")

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "retake":
        await query.edit_message_text("Restarting this spot...")
        return await request_landmark_photos(update, context)
    
    kb = [
        [InlineKeyboardButton("🟢 Healthy", callback_data="Healthy"), InlineKeyboardButton("🔴 Issue", callback_data="Issue")],
        [InlineKeyboardButton("🟠 Unsure", callback_data="Unsure")]
    ]
    await query.edit_message_text("How does it look today?", reply_markup=InlineKeyboardMarkup(kb))
    return LOG_STATUS

async def log_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    lm = context.user_data['landmarks'][context.user_data['current_idx']]
    
    saved_paths = {}
    for p_type, temp_path in context.user_data['temp_photos'].items():
        with open(temp_path, 'rb') as f:
            saved_paths[p_type] = save_telegram_file(f, user_id, lm.id, p_type)
        if os.path.exists(temp_path): os.remove(temp_path)
            
    db.create_entry(user_id, lm.id, saved_paths, query.data, context.user_data.get('weather', {}))
    
    await query.edit_message_text(f"✅ Saved **{lm.label}**.", parse_mode='Markdown')
    context.user_data['current_idx'] += 1
    
    # Loop back to next landmark
    return await request_landmark_photos(update, context)

if __name__ == '__main__':
    if not TOKEN: exit("Error: TELEGRAM_TOKEN missing")
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    # --- FILTER FIX ---
    # We use (filters.TEXT & ~filters.COMMAND) to prevent "/profile" from being treated as a Name/Farm Name
    
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
    
    collection = ConversationHandler(
        entry_points=[CommandHandler('collection', start_collection)],
        states={
            CAPTURE_WIDE: [MessageHandler(filters.PHOTO, handle_wide)],
            CAPTURE_CLOSE: [MessageHandler(filters.PHOTO, handle_close)],
            CAPTURE_SOIL: [MessageHandler(filters.PHOTO, handle_soil)],
            CONFIRM_SET: [CallbackQueryHandler(handle_confirmation)],
            LOG_STATUS: [CallbackQueryHandler(log_status)]
        }, fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(onboard)
    app.add_handler(collection)
    app.add_handler(CommandHandler("profile", view_profile))
    
    print("🤖 Farm Bot LIVE.")
    app.run_polling()