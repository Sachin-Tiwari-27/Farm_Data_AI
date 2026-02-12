import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from utils.validators import parse_time, validate_landmark_count

logger = logging.getLogger(__name__)

# --- STATES ---
(NAME, FARM, LOCATION, P_TIME, V_TIME, 
 L_COUNT, L_ENV_BATCH, L_MED_BATCH, L_NAMING_LOOP) = range(9)

# --- ENTRY POINT ---
async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    if user:
        await update.message.reply_text(f"👋 **Welcome back, {user.full_name}!**", parse_mode='Markdown')
        return ConversationHandler.END
    
    await update.message.reply_text(
        "👋 **Welcome to Farm Diary.**\nLet's set up your farm profile.\n\nStep 1: What is your **Full Name**?", 
        reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown'
    )
    return NAME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- BASIC PROFILE STEPS ---
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Step 2: **Farm Name**?", parse_mode='Markdown')
    return FARM

async def get_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['farm'] = update.message.text
    kb = [[KeyboardButton("📍 Share Farm Location", request_location=True)]]
    await update.message.reply_text("Step 3: **Location**.", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True), parse_mode='Markdown')
    return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        context.user_data['lat'] = update.message.location.latitude
        context.user_data['lon'] = update.message.location.longitude
    else:
        # Fallback if they type text instead of sharing location
        context.user_data['lat'] = 0.0
        context.user_data['lon'] = 0.0
        
    await update.message.reply_text("Step 4: **Morning Check-in Time**? (e.g. '7' or '7:30 am')", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
    return P_TIME

async def get_p_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=False)
    if not t: 
        await update.message.reply_text("⚠️ Invalid time. Try '07:00' or '7'.")
        return P_TIME
    context.user_data['p_time'] = t
    await update.message.reply_text("Step 5: **Evening Summary Time**? (e.g. '18:00' or '6 pm')", parse_mode='Markdown')
    return V_TIME

async def get_v_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text, is_evening=True)
    if not t: 
        await update.message.reply_text("⚠️ Invalid time. Try '18:00' or '6'.")
        return V_TIME
    context.user_data['v_time'] = t
    
    # --- START LANDMARK CONFIG ---
    kb = [
        [InlineKeyboardButton("3 Spots", callback_data="3"), InlineKeyboardButton("4 Spots", callback_data="4")],
        [InlineKeyboardButton("5 Spots", callback_data="5"), InlineKeyboardButton("6 Spots", callback_data="6")],
        [InlineKeyboardButton("⌨️ Type a Number", callback_data="custom")]
    ]
    await update.message.reply_text(
        "Step 6: **How many distinct spots** do you want to track?", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )
    return L_COUNT

# --- BATCH SETUP LOGIC ---

async def get_l_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    msg = update.message
    
    count = None
    
    # Handle Button Click
    if query:
        await query.answer()
        if query.data == "custom":
            await query.edit_message_text("⌨️ **Type the number of spots (1-20):**", parse_mode='Markdown')
            return L_COUNT
        count = int(query.data)
        reply_func = query.edit_message_text
    
    # Handle Text Input (Custom)
    elif msg:
        count = validate_landmark_count(msg.text)
        if not count:
            await msg.reply_text("⚠️ Please enter a number between 1 and 20.")
            return L_COUNT
        reply_func = msg.reply_text

    context.user_data['l_count'] = count
    
    # Ask Environment Batch
    kb = [
        [InlineKeyboardButton("All Open Field", callback_data="all_field")],
        [InlineKeyboardButton("All Polyhouse", callback_data="all_poly")],
        [InlineKeyboardButton("All CEA (Indoor)", callback_data="all_cea")],
        [InlineKeyboardButton("🔀 Mixed Types", callback_data="mixed")]
    ]
    await reply_func(f"✅ Tracking **{count} spots**.\n\nAre they all in the same environment?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return L_ENV_BATCH

async def get_env_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    
    # Map selection to DB Constants
    if choice == "all_field": context.user_data['batch_env'] = db.ENV_FIELD
    elif choice == "all_poly": context.user_data['batch_env'] = db.ENV_POLY
    elif choice == "all_cea": context.user_data['batch_env'] = db.ENV_CEA
    else: context.user_data['batch_env'] = None # Mixed
    
    # Ask Medium Batch
    kb = [
        [InlineKeyboardButton("All Soil", callback_data="all_soil")],
        [InlineKeyboardButton("All Cocopeat", callback_data="all_coco")],
        [InlineKeyboardButton("All Hydroponic", callback_data="all_hydro")],
        [InlineKeyboardButton("🔀 Mixed Mediums", callback_data="mixed")]
    ]
    await query.edit_message_text("🌱 Are they using the same **Growing Medium**?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return L_MED_BATCH

async def get_medium_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    
    # Map selection
    if choice == "all_soil": context.user_data['batch_med'] = db.MED_SOIL
    elif choice == "all_coco": context.user_data['batch_med'] = db.MED_COCO
    elif choice == "all_hydro": context.user_data['batch_med'] = db.MED_HYDRO
    else: context.user_data['batch_med'] = None # Mixed
    
    # Initialize Loop
    context.user_data['current_lm_idx'] = 1
    context.user_data['final_landmarks'] = []
    
    await start_naming_loop(query, context)
    return L_NAMING_LOOP

# --- NAMING LOOP ---

async def start_naming_loop(update_obj, context):
    """Called recursively to name each spot."""
    idx = context.user_data['current_lm_idx']
    total = context.user_data['l_count']
    
    # Check if done
    if idx > total:
        return await finish_onboarding(update_obj, context)
    
    # If "Mixed" was chosen, we default to Field/Soil and tell user to edit later (Fast Track)
    # Or we can ask details. For this Phase 2B, let's keep it fast:
    # We ask for NAME. If they skipped "Batch" settings, we apply defaults.
    
    default_name = f"Spot {idx}"
    
    kb = [[InlineKeyboardButton(f"⏩ Skip (Keep '{default_name}')", callback_data="skip_name")]]
    
    # Show "Finish Early" button if we have done at least 3
    if idx > 3:
        kb.append([InlineKeyboardButton("✅ Finish Setup Now", callback_data="finish_early")])
        
    msg = f"🏷 **Name for Spot {idx}/{total}?**\n(e.g., 'North Tunnel', 'Tomato Patch')"
    
    if hasattr(update_obj, 'edit_message_text'):
        await update_obj.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update_obj.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
    return L_NAMING_LOOP

async def handle_naming_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles both Text Input (Custom Name) and Button Click (Skip/Finish)."""
    idx = context.user_data['current_lm_idx']
    
    # 1. Determine Name
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "finish_early":
            return await finish_onboarding(query, context)
        # data == "skip_name"
        name = f"Spot {idx}"
        msg_obj = query
    else:
        name = update.message.text
        msg_obj = update
        
    # 2. Determine Env/Medium (Apply Batch or Default)
    env = context.user_data.get('batch_env', db.ENV_FIELD) # Default to Field if mixed
    med = context.user_data.get('batch_med', db.MED_SOIL)  # Default to Soil if mixed
    
    # 3. Create Landmark Dict
    lm = {
        "id": idx,
        "label": name,
        "env": env,
        "medium": med
    }
    context.user_data['final_landmarks'].append(lm)
    
    # 4. Next Iteration
    context.user_data['current_lm_idx'] += 1
    return await start_naming_loop(msg_obj, context)

# --- FINALIZE ---

async def finish_onboarding(update_obj, context: ContextTypes.DEFAULT_TYPE):
    # If finished early, fill the rest with defaults
    current_list = context.user_data['final_landmarks']
    target_count = context.user_data['l_count']
    
    next_id = len(current_list) + 1
    while len(current_list) < target_count:
        current_list.append({
            "id": next_id,
            "label": f"Spot {next_id}",
            "env": context.user_data.get('batch_env', db.ENV_FIELD),
            "medium": context.user_data.get('batch_med', db.MED_SOIL)
        })
        next_id += 1
        
    # Save to DB
    user_id = update_obj.from_user.id
    profile = {
        'id': user_id,
        'name': context.user_data['name'],
        'farm': context.user_data['farm'],
        'lat': context.user_data['lat'],
        'lon': context.user_data['lon'],
        'p_time': context.user_data['p_time'],
        'v_time': context.user_data['v_time'],
        'l_count': len(current_list), # Actual count
        'landmarks': current_list # The list of dicts
    }
    
    db.save_user_profile(profile)
    
    # Message
    final_msg = "✅ **Setup Complete!**\n\nYour farm is ready. You can edit specific spot details (Environment/Medium) in the **Dashboard**."
    
    # We need to trigger the Main Menu. 
    # Since we are in a modular file, we can't import MAIN_MENU_KBD easily. 
    # We will send a text reply, and the main.py will handle the menu on next interaction 
    # OR we define a simple one here.
    
    kb = ReplyKeyboardMarkup([
        ['📸 Start Morning Check-in'],
        ['🎙 Record Evening Summary'],
        ['📝 Quick Ad-Hoc Note'],
        ['📊 View History', '👤 Dashboard']
    ], resize_keyboard=True)

    if hasattr(update_obj, 'edit_message_text'):
        await update_obj.edit_message_text(final_msg, parse_mode='Markdown')
        await update_obj.message.reply_text("👇 Use the menu below:", reply_markup=kb)
    else:
        await update_obj.message.reply_text(final_msg, parse_mode='Markdown', reply_markup=kb)

    return ConversationHandler.END

# --- EXPORT HANDLER ---
onboarding_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start_onboarding)],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        FARM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_farm)],
        LOCATION: [MessageHandler(filters.LOCATION | filters.TEXT, get_location)],
        P_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_p_time)],
        V_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_time)],
        L_COUNT: [CallbackQueryHandler(get_l_count), MessageHandler(filters.TEXT & ~filters.COMMAND, get_l_count)],
        L_ENV_BATCH: [CallbackQueryHandler(get_env_batch)],
        L_MED_BATCH: [CallbackQueryHandler(get_medium_batch)],
        L_NAMING_LOOP: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_naming_input),
            CallbackQueryHandler(handle_naming_input)
        ]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)