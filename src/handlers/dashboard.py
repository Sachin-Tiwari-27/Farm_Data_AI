import logging
import math
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from handlers.router import route_intent

logger = logging.getLogger(__name__)

# --- STATES ---
DASH_MAIN, DASH_EDIT_MENU, DASH_RENAME, DASH_ENV, DASH_MED, DASH_ADD_ENV, DASH_ADD_MED = range(7)
ITEMS_PER_PAGE = 5

# --- ENTRY POINT ---
async def view_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the Farm Profile and List of Landmarks with Pagination."""
    user = db.get_user_profile(update.effective_user.id)
    if not user:
        await update.message.reply_text("⚠️ User not found. Type /start to register.")
        return ConversationHandler.END

    # Reset Edit ID when entering main view
    context.user_data['edit_lm_id'] = None

    # Handle Pagination
    page = context.user_data.get('dash_page', 0)
    
    # Check for Callback (Next/Prev)
    if update.callback_query:
        query = update.callback_query
        # Don't answer yet, usually done in handler, but okay here
        if query.data.startswith("page_"):
            page = int(query.data.split("_")[1])
            context.user_data['dash_page'] = page
    
    # Calculate Slices
    total_items = len(user.landmarks)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    if page >= total_pages: page = 0 # Safety reset
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_items = user.landmarks[start_idx:end_idx]

    # Farm Summary
    msg = (f"👤 **{user.full_name}**\n"
           f"🚜 **{user.farm_name}**\n"
           f"⏰ Morning: {user.photo_time} | Evening: {user.voice_time}\n"
           f"────────────────────\n"
           f"📍 **Landmarks ({len(user.landmarks)}):**\n")

    # Dynamic Buttons
    kb = []
    for lm in current_items:
        # Label: "Spot 1: Tomato (Poly/Soil)"
        lbl = f"{lm.label} ({lm.env}/{lm.medium})"
        kb.append([InlineKeyboardButton(lbl, callback_data=f"edit_{lm.id}")])
    
    # Pagination Controls
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(f"Page {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    if nav_row: kb.append(nav_row)

    # Manage Buttons
    kb.append([InlineKeyboardButton("➕ Add New Spot", callback_data="add_spot")])
    kb.append([InlineKeyboardButton("❌ Close Dashboard", callback_data="close_dash")])

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    return DASH_MAIN

# --- NAVIGATION HANDLER (Main Menu) ---

async def handle_dash_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Clicks in DASH_MAIN (Pagination, Edit, Add, Close)."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "close_dash":
        await query.delete_message()
        return ConversationHandler.END
        
    if data == "add_spot":
        return await start_add_spot(update, context)
        
    if data.startswith("page_"):
        # Loop back to view_dashboard to render new page
        return await view_dashboard(update, context)
        
    if data.startswith("edit_"):
        lm_id = int(data.split('_')[1])
        context.user_data['edit_lm_id'] = lm_id
        return await open_edit_menu(update, context)
        
    return DASH_MAIN

# --- EDIT MENU ---

async def open_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays options for a single landmark."""
    if update.callback_query:
        query = update.callback_query
        # await query.answer() # Already answered in upstream usually
        user_id = query.from_user.id
        msg_func = query.edit_message_text
    else:
        # Coming from rename (text message)
        user_id = update.effective_user.id
        msg_func = update.message.reply_text

    lm_id = context.user_data.get('edit_lm_id')
    lm = db.get_landmark_by_id(user_id, lm_id)
    
    if not lm:
        await msg_func("❌ Error: Landmark not found. Returning to list.")
        return await view_dashboard(update, context)

    msg = (f"📍 **Editing: {lm.label}**\n"
           f"━━━━━━━━━━━━━━\n"
           f"🏠 Environment: **{lm.env}**\n"
           f"🌱 Medium: **{lm.medium}**")
    
    kb = [
        [InlineKeyboardButton("🏷 Rename", callback_data="act_rename"), InlineKeyboardButton("🗑 Delete", callback_data="act_delete")],
        [InlineKeyboardButton("🏠 Change Env", callback_data="act_env"), InlineKeyboardButton("🌱 Change Medium", callback_data="act_med")],
        [InlineKeyboardButton("◀️ Back to List", callback_data="back_main")]
    ]
    
    await msg_func(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return DASH_EDIT_MENU

async def handle_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    
    if action == "back_main":
        return await view_dashboard(update, context)
    
    lm_id = context.user_data['edit_lm_id']
    user_id = query.from_user.id
    
    if action == "act_delete":
        user = db.get_user_profile(user_id)
        # Filter out
        user.landmarks = [l for l in user.landmarks if l.id != lm_id]
        _save_user_landmarks(user)
        
        await query.edit_message_text(f"🗑 **Spot deleted.**")
        return await view_dashboard(update, context)
        
    if action == "act_rename":
        await query.edit_message_text(f"⌨️ **Type the new name for this spot:**")
        return DASH_RENAME

    if action == "act_env":
        kb = [
            [InlineKeyboardButton("Open Field", callback_data=db.ENV_FIELD)],
            [InlineKeyboardButton("Polyhouse", callback_data=db.ENV_POLY)],
            [InlineKeyboardButton("CEA", callback_data=db.ENV_CEA)],
            [InlineKeyboardButton("◀️ Back", callback_data="back_edit")]
        ]
        await query.edit_message_text("🏠 Select new environment:", reply_markup=InlineKeyboardMarkup(kb))
        return DASH_ENV

    if action == "act_med":
        kb = [
            [InlineKeyboardButton("Soil", callback_data=db.MED_SOIL)],
            [InlineKeyboardButton("Cocopeat", callback_data=db.MED_COCO)],
            [InlineKeyboardButton("Hydroponic", callback_data=db.MED_HYDRO)],
            [InlineKeyboardButton("Mixed", callback_data=db.MED_MIX)],
            [InlineKeyboardButton("◀️ Back", callback_data="back_edit")]
        ]
        await query.edit_message_text("🌱 Select new medium:", reply_markup=InlineKeyboardMarkup(kb))
        return DASH_MED
        
    return DASH_EDIT_MENU

# --- SAVERS (Return to Edit Menu) ---

async def save_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text
    lm_id = context.user_data['edit_lm_id']
    user_id = update.effective_user.id
    
    _update_landmark_field(user_id, lm_id, 'label', new_name)
    await update.message.reply_text(f"✅ Renamed to **{new_name}**", parse_mode='Markdown')
    
    # Return to Edit Menu for this spot
    return await open_edit_menu(update, context)

async def save_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data
    
    if val == "back_edit": return await open_edit_menu(update, context)
    
    lm_id = context.user_data['edit_lm_id']
    user_id = query.from_user.id
    
    _update_landmark_field(user_id, lm_id, 'env', val)
    return await open_edit_menu(update, context)

async def save_med(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data
    
    if val == "back_edit": return await open_edit_menu(update, context)
    
    lm_id = context.user_data['edit_lm_id']
    user_id = query.from_user.id
    
    _update_landmark_field(user_id, lm_id, 'medium', val)
    return await open_edit_menu(update, context)

# --- HELPERS ---

def _save_user_landmarks(user):
    save_data = {
        'id': user.id, 'name': user.full_name, 'farm': user.farm_name,
        'lat': user.latitude, 'lon': user.longitude,
        'p_time': user.photo_time, 'v_time': user.voice_time,
        'l_count': len(user.landmarks),
        'landmarks': [l.to_dict() for l in user.landmarks]
    }
    db.save_user_profile(save_data)

def _update_landmark_field(user_id, lm_id, field, value):
    user = db.get_user_profile(user_id)
    for lm in user.landmarks:
        if lm.id == lm_id:
            setattr(lm, field, value)
            break
    _save_user_landmarks(user)

# --- ADD NEW SPOT ---

async def start_add_spot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Open Field", callback_data=db.ENV_FIELD)],
        [InlineKeyboardButton("Polyhouse", callback_data=db.ENV_POLY)],
        [InlineKeyboardButton("CEA", callback_data=db.ENV_CEA)]
    ]
    await update.callback_query.edit_message_text("➕ **New Spot**\n\n1️⃣ Select Environment:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return DASH_ADD_ENV

async def add_spot_get_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_spot_env'] = query.data
    
    kb = [
        [InlineKeyboardButton("Soil", callback_data=db.MED_SOIL)],
        [InlineKeyboardButton("Cocopeat", callback_data=db.MED_COCO)],
        [InlineKeyboardButton("Hydroponic", callback_data=db.MED_HYDRO)]
    ]
    await query.edit_message_text("2️⃣ Select Medium:", reply_markup=InlineKeyboardMarkup(kb))
    return DASH_ADD_MED

async def add_spot_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    med = query.data
    env = context.user_data['new_spot_env']
    user_id = query.from_user.id
    
    user = db.get_user_profile(user_id)
    new_id = 1
    if user.landmarks:
        new_id = max(l.id for l in user.landmarks) + 1
        
    new_lm = {"id": new_id, "label": f"Spot {new_id}", "env": env, "medium": med}
    
    # Save
    current_list = [l.to_dict() for l in user.landmarks]
    current_list.append(new_lm)
    
    user.landmarks = [db.Landmark(l) for l in current_list]
    _save_user_landmarks(user)
    
    await query.edit_message_text("✅ **Spot Added!**\nUse 'Rename' to give it a custom name.")
    return await view_dashboard(update, context)

# --- EXPORT ---
dashboard_handler = ConversationHandler(
    entry_points=[
        CommandHandler('profile', view_dashboard), 
        MessageHandler(filters.Regex("^👤 Dashboard$"), view_dashboard),
        # NEW: Allow internal interactions to restart/start the dashboard
        CallbackQueryHandler(handle_dash_nav, pattern="^(page_|edit_|add_spot|close_dash)")
    ],
    states={
        DASH_MAIN: [CallbackQueryHandler(handle_dash_nav)],
        DASH_EDIT_MENU: [CallbackQueryHandler(handle_edit_action)],
        DASH_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_rename)],
        DASH_ENV: [CallbackQueryHandler(save_env)],
        DASH_MED: [CallbackQueryHandler(save_med)],
        DASH_ADD_ENV: [CallbackQueryHandler(add_spot_get_env)],
        DASH_ADD_MED: [CallbackQueryHandler(add_spot_finish)]
    },
    fallbacks=[
        CommandHandler('cancel', view_dashboard),
        MessageHandler(filters.TEXT & ~filters.COMMAND, route_intent)
    ]
)