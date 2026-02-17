import logging
import math
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from utils.menus import MAIN_MENU_KBD
import database as db
from handlers.router import route_intent
from handlers.onboarding import cancel as global_cancel
from utils.validators import parse_time

logger = logging.getLogger(__name__)

# --- STATES ---
DASH_MAIN, DASH_EDIT_MENU, DASH_RENAME, DASH_ENV, DASH_MED, DASH_ADD_NAME, DASH_ADD_ENV, DASH_ADD_MED, DASH_UP_PHOTO, DASH_UP_VOICE = range(10)
ITEMS_PER_PAGE = 5  # Pagination Limit

# --- ENTRY POINT ---
async def view_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the Farm Profile and List of Landmarks with Pagination."""
    user = db.get_user_profile(update.effective_user.id)
    if not user:
        msg = "⚠️ No profile found. Use /start."
        if update.message: await update.message.reply_text(msg)
        else: await update.callback_query.edit_message_text(msg)
        return ConversationHandler.END

    # Reset temp state
    context.user_data['edit_lm_id'] = None
    
    # Handle Page Number
    page = context.user_data.get('dash_page', 0)
    
    # Setup Message Function
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        msg_func = query.edit_message_text
    else:
        msg_func = update.message.reply_text

    # Pagination Logic
    total_spots = len(user.landmarks)
    total_pages = math.ceil(total_spots / ITEMS_PER_PAGE)
    
    # Safety Check
    if page >= total_pages: page = max(0, total_pages - 1)
    context.user_data['dash_page'] = page
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    spots = user.landmarks[start:end]
    
    text = (
        f"👤 **{user.full_name}**\n"
        f"🌱 Farm Name: {user.farm_name}\n"
        f"📍 Coords: `{user.latitude:.4f}, {user.longitude:.4f}`\n"
        f"☀️ Morning Alert: {user.photo_time}\n"
        f"🌙 Evening Alert: {user.voice_time}\n"
        f"🪨 Landmarks: {total_spots}\n\n"
        f"**Manage Landmarks (Page {page + 1}/{max(1, total_pages)}):**"
    )
    
    kb = []
    for lm in spots:
        # UX UPDATE: Show Label (Env)
        btn_text = f"⚙️ {lm.label} ({lm.env})"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"edit_{lm.id}")])
        
    # Navigation Row
    nav_row = []
    if page > 0: 
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    if page < total_pages - 1: 
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data="page_next"))
    if nav_row: kb.append(nav_row)
    
    kb.append([InlineKeyboardButton("➕ Add New Spot", callback_data="add_spot")])
    kb.append([InlineKeyboardButton("⏰ Update Schedule", callback_data="dash_up_times")])
    kb.append([InlineKeyboardButton("❌ Close", callback_data="close_dash")])
    
    await msg_func(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return DASH_MAIN

# --- NAVIGATION HANDLER ---
async def handle_dash_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data

    if action == "dash_up_times":
        await query.answer()
        await query.edit_message_text("⏰ **Update Morning Alert Time**\nSend time in 24h format (e.g. 08:30):")
        return DASH_UP_PHOTO
    
    if action == "close_dash":
        await query.answer()
        await query.message.reply_text("✅ Dashboard closed.", reply_markup=MAIN_MENU_KBD)
        return ConversationHandler.END
        
    if action == "add_spot":
        await query.answer()
        await query.edit_message_text(
            "➕ **Adding New Spot**\n\n"
            "What is the name of this location?\n"
            "_(e.g., 'North Corner', 'Polyhouse 2')_"
        )
        return DASH_ADD_NAME
        
    if action.startswith("page_"):
        await query.answer()
        page = context.user_data.get('dash_page', 0)
        if action == "page_prev": page = max(0, page - 1)
        elif action == "page_next": page += 1
        context.user_data['dash_page'] = page
        return await view_dashboard(update, context)
        
    if action.startswith("edit_"):
        await query.answer()
        try:
            lm_id = int(action.split("_")[1])
            return await show_edit_menu(update, context, lm_id)
        except (IndexError, ValueError):
            await query.edit_message_text("❌ Error: Invalid ID.")
            return await view_dashboard(update, context)
        
    return DASH_MAIN

# --- EDIT MENU HELPER (The Anchor) ---
async def show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lm_id: int):
    """Refreshes the specific landmark edit menu."""
    user = db.get_user_profile(update.effective_user.id)
    landmark = next((l for l in user.landmarks if l.id == lm_id), None)
    
    if not landmark:
        # Fallback if deleted
        if update.callback_query:
            await update.callback_query.answer("Spot not found (maybe deleted?)")
        return await view_dashboard(update, context)

    context.user_data['edit_lm_id'] = lm_id
    
    text = (
        f"⚙️ **Editing: {landmark.label}**\n"
        f"🏡 Env: {landmark.env}\n"
        f"🪨 Med: {landmark.medium}"
    )
    
    kb = [
        [InlineKeyboardButton("✏️ Rename", callback_data="edit_rename")],
        [InlineKeyboardButton("🌱 Change Environment", callback_data="edit_env"), InlineKeyboardButton("🪨 Change Medium", callback_data="edit_med")],
        [InlineKeyboardButton("🗑️ Delete Spot", callback_data="edit_delete"), InlineKeyboardButton("🔙 Back to List", callback_data="edit_back")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
    return DASH_EDIT_MENU

# --- EDIT ACTIONS ---
async def handle_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    await query.answer()
    
    if action == "edit_back":
        return await view_dashboard(update, context)
        
    if action == "edit_delete":
        lm_id = context.user_data.get('edit_lm_id')
        user = db.get_user_profile(update.effective_user.id)
        
        # Safe Delete
        user.landmarks = [l for l in user.landmarks if l.id != lm_id]
        db.save_user_profile(user.to_dict())
        
        await query.edit_message_text("🗑️ **Spot deleted.**")
        return await view_dashboard(update, context)

    if action == "edit_rename":
        await query.edit_message_text("✍️ **Enter new name:**")
        return DASH_RENAME
        
    if action == "edit_env":
        kb = [[InlineKeyboardButton(e, callback_data=e)] for e in [db.ENV_FIELD, db.ENV_POLY, db.ENV_CEA]]
        await query.edit_message_text("🌱 **Select Environment:**", reply_markup=InlineKeyboardMarkup(kb))
        return DASH_ENV
        
    if action == "edit_med":
        kb = [[InlineKeyboardButton(m, callback_data=m)] for m in [db.MED_SOIL, db.MED_COCO, db.MED_MIX, db.MED_HYDRO]]
        await query.edit_message_text("🪨 **Select Medium:**", reply_markup=InlineKeyboardMarkup(kb))
        return DASH_MED
        
    return DASH_EDIT_MENU

async def save_up_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text
    new_time = parse_time(raw_text, is_evening=False)
    
    if not new_time:
        await update.message.reply_text("❌ **Invalid Format.** Try '08:30', '8am', or just '8'.")
        return DASH_UP_PHOTO
        
    db.update_user_schedule(user_id, p_time=new_time)
    await update.message.reply_text(f"✅ Morning alert set to {new_time}.\n\n**Update Evening Alert Time:**\n_(e.g. '6pm' or '18:30')_")
    return DASH_UP_VOICE

async def save_up_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text
    new_time = parse_time(raw_text, is_evening=True)
    
    if not new_time:
        await update.message.reply_text("❌ **Invalid Format.** Try '18:00', '6pm', or just '6'.")
        return DASH_UP_VOICE
        
    db.update_user_schedule(user_id, v_time=new_time)
    
    # Sync live JobQueue
    user = db.get_user_profile(user_id)
    from utils.scheduler import schedule_user_jobs
    schedule_user_jobs(context.application, user_id, user.photo_time, user.voice_time)
    
    await update.message.reply_text("✅ Schedule updated and synced.")
    return await view_dashboard(update, context)

# --- SAVE HANDLERS ---
async def save_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_profile(update.effective_user.id)
    lm_id = context.user_data.get('edit_lm_id')
    new_name = update.message.text
    
    for lm in user.landmarks:
        if lm.id == lm_id:
            lm.label = new_name
            break
            
    db.save_user_profile(user.to_dict())
    await update.message.reply_text(f"✅ Renamed to **{new_name}**", parse_mode='Markdown')
    # Return to Anchor
    return await show_edit_menu(update, context, lm_id)

async def save_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user_profile(update.effective_user.id)
    lm_id = context.user_data.get('edit_lm_id')
    
    for lm in user.landmarks:
        if lm.id == lm_id:
            lm.env = query.data
            break
    db.save_user_profile(user.to_dict())
    # Return to Anchor
    return await show_edit_menu(update, context, lm_id)

async def save_med(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user_profile(update.effective_user.id)
    lm_id = context.user_data.get('edit_lm_id')
    
    for lm in user.landmarks:
        if lm.id == lm_id:
            lm.medium = query.data
            break
    db.save_user_profile(user.to_dict())
    # Return to Anchor
    return await show_edit_menu(update, context, lm_id)

# --- ADD NEW SPOT FLOW ---
async def add_spot_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = "New Spot"
    if update.message and update.message.text:
        name = update.message.text
    context.user_data['new_spot_name'] = name
    
    kb = [[InlineKeyboardButton(e, callback_data=e)] for e in [db.ENV_FIELD, db.ENV_POLY, db.ENV_CEA]]
    msg_func = update.message.reply_text if update.message else update.callback_query.edit_message_text
    await msg_func(f"📍 Name: **{name}**\n\n🌱 **Select Environment:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return DASH_ADD_ENV

async def add_spot_get_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_spot_env'] = query.data
    
    kb = [[InlineKeyboardButton(m, callback_data=m)] for m in [db.MED_SOIL, db.MED_COCO, db.MED_MIX, db.MED_HYDRO]]
    await query.edit_message_text("🪨 **Select Medium:**", reply_markup=InlineKeyboardMarkup(kb))
    return DASH_ADD_MED

async def add_spot_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user_profile(update.effective_user.id)
    new_lm = {
        "label": context.user_data['new_spot_name'],
        "env": context.user_data['new_spot_env'],
        "medium": query.data
    }
    
    # Let DB handle ID generation (ID is None here)
    user.landmarks.append(db.Landmark(new_lm))
    db.save_user_profile(user.to_dict())
    
    await query.edit_message_text(f"✅ **Added: {new_lm['label']}**")
    return await view_dashboard(update, context)

# --- EXPORT HANDLER ---
dashboard_handler = ConversationHandler(
    entry_points=[
        CommandHandler('profile', view_dashboard), 
        MessageHandler(filters.Regex("^👤 Dashboard$"), view_dashboard),
        CallbackQueryHandler(handle_dash_nav, pattern="^(page_|edit_|add_spot|close_dash|dash_up_times)")
    ],
    states={
        DASH_MAIN: [CallbackQueryHandler(handle_dash_nav), MessageHandler(filters.TEXT, route_intent)],
        DASH_EDIT_MENU: [CallbackQueryHandler(handle_edit_action)],
        DASH_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_rename)],
        DASH_ENV: [CallbackQueryHandler(save_env)],
        DASH_MED: [CallbackQueryHandler(save_med)],
        DASH_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_spot_get_name)],
        DASH_ADD_ENV: [CallbackQueryHandler(add_spot_get_env)],
        DASH_ADD_MED: [CallbackQueryHandler(add_spot_final)],
        DASH_UP_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_up_photo)],
        DASH_UP_VOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_up_voice)],
    },
    fallbacks=[CommandHandler('cancel', global_cancel)],
    per_chat=True
)