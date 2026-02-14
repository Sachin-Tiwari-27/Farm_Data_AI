import os
import datetime
import math
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from handlers.router import route_intent

# --- STATES ---
VIEW_HISTORY, BROWSE_DATES = range(2)
ITEMS_PER_PAGE = 6 

async def view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user_profile(user_id)
    if not user:
        if update.message:
            await update.message.reply_text(
                "⚠️ **Registration Required**\n\n"
                "I don't see your farm profile yet.\n"
                "Please tap /start to set up your farm.",
                parse_mode='Markdown'
            )
        return ConversationHandler.END

    # Entry point cleaning
    context.user_data.clear()

    if update.message: msg_func = update.message.reply_text
    else: 
        await update.callback_query.answer()
        msg_func = update.callback_query.edit_message_text
    
    kb = [
        [InlineKeyboardButton("📅 Today", callback_data="hist_today"), InlineKeyboardButton("⏮ Yesterday", callback_data="hist_yesterday")],
        [InlineKeyboardButton("🗓 Last 7 Days", callback_data="browse_7"), InlineKeyboardButton("📆 Last Month", callback_data="browse_30")]
    ]
    await msg_func("📊 **History & Reports**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

# --- PERIOD LOGIC ---

async def route_history_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data in ['hist_today', 'hist_yesterday']:
        return await show_single_day_summary(update, context, data)
        
    if data.startswith('browse_'):
        days = int(data.split('_')[1])
        context.user_data['hist_days'] = days
        context.user_data['hist_page'] = 0
        return await show_date_grid(update, context)
    
    return VIEW_HISTORY

async def show_single_day_summary(update, context, data_key):
    query = update.callback_query
    user_id = query.from_user.id
    today = datetime.datetime.now().date()
    
    if 'today' in data_key: 
        target = today
        title = "Today"
    else: 
        target = today - datetime.timedelta(days=1)
        title = "Yesterday"
        
    d_str = target.strftime("%Y-%m-%d")
    entries = db.get_entries_for_date(user_id, d_str)
    
    # Build List
    lines = []
    adhoc_count = 0
    evening_done = False
    
    for e in entries:
        if e.landmark_id == 99: adhoc_count += 1; continue
        if e.landmark_id == 0: evening_done = True; continue
        
        icon = "🟢" if e.status == "Healthy" else "🔴" if e.status == "Issue" else "🟠"
        lines.append(f"{icon} **{e.landmark_name}**: {e.status}")
        
    # Check Morning Status (Source of Truth)
    pending = db.get_pending_landmark_ids(user_id)
    am_status = "✅ Done" if not pending else f"⚠️ {len(pending)} Pending"
    if 'yesterday' in data_key: am_status = "n/a" # Only relevant for today
    
    summary = (f"📊 **{title}**\n"
               f"☀️ Morning: {am_status}\n"
               f"🌙 Evening: {'✅ Done' if evening_done else '❌ Pending'}\n"
               f"━━━━━━━━━━━━\n" + ("\n".join(lines) if lines else "_No routine logs._"))
               
    if adhoc_count: summary += f"\n\n📝 Ad-Hoc Notes: {adhoc_count}"
    
    kb = [
        [InlineKeyboardButton("📸 View Details", callback_data=f"view_date_{d_str}")],
        [InlineKeyboardButton("◀️ Back", callback_data="back_main")]
    ]
    await query.edit_message_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

# --- DATE GRID ---

async def show_date_grid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    days = context.user_data.get('hist_days', 7)
    page = context.user_data.get('hist_page', 0)
    
    end_date = datetime.datetime.now().date()
    start_date = end_date - datetime.timedelta(days=days)
    
    data_map = db.get_entries_by_date_range(user_id, start_date, end_date)
    available_dates = sorted(data_map.keys(), reverse=True)
    
    if not available_dates:
        await query.edit_message_text("📭 No logs in this period.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_main")]]))
        return VIEW_HISTORY

    total_pages = math.ceil(len(available_dates) / ITEMS_PER_PAGE)
    if page >= total_pages: page = 0
    
    start = page * ITEMS_PER_PAGE
    subset = available_dates[start : start+ITEMS_PER_PAGE]
    
    kb = []
    row = []
    for d_str in subset:
        d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d")
        lbl = d_obj.strftime("%b %d")
        row.append(InlineKeyboardButton(lbl, callback_data=f"view_date_{d_str}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"hpage_{page-1}"))
    if total_pages > 1: nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton("➡️", callback_data=f"hpage_{page+1}"))
    if nav: kb.append(nav)
    
    kb.append([InlineKeyboardButton("◀️ Back Menu", callback_data="back_main")])
    
    await query.edit_message_text(f"🗓 **Select Date** (Last {days} days)", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return BROWSE_DATES

async def handle_grid_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_main": return await view_history(update, context)
    if data.startswith("hpage_"):
        context.user_data['hist_page'] = int(data.split('_')[1])
        return await show_date_grid(update, context)
    
    if data.startswith("view_date_"):
        return await show_date_details(update, context)
        
    return BROWSE_DATES

# --- DETAIL VIEW ---
async def show_date_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    date_str = query.data.replace("view_date_", "")
    user_id = update.effective_user.id
    entries = db.get_entries_for_date(user_id, date_str)
    
    if not entries:
        await query.message.reply_text("No logs found for this date.")
        return VIEW_HISTORY

    for e in entries:
        # Improved media detection for SQLite keys
        msg = (
            f"📅 **{e.timestamp.strftime('%H:%M')} - {e.category.upper()}**\n"
            f"📍 Spot: {e.landmark_name}\n"
            f"🩺 Status: {e.status}\n"
            f"📝 Note: {e.transcription if e.transcription else 'No voice note.'}\n"
        )
        await query.message.reply_text(msg, parse_mode='Markdown')
        
        media = []
        if e.files:
            for k, v in e.files.items():
                # Catch 'wide', 'close', 'soil', AND any key containing 'photo'
                is_photo = any(x in k for x in ['wide', 'close', 'soil', 'photo'])
                if is_photo and os.path.exists(v):
                    media.append(InputMediaPhoto(open(v, 'rb')))
        
        if media:
            await query.message.reply_media_group(media)
    
    kb = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="back_main")]]
    await query.message.reply_text("End of Log.", reply_markup=InlineKeyboardMarkup(kb))
    return VIEW_HISTORY

# --- EXPORT ---
history_handler = ConversationHandler(
    entry_points=[
        CommandHandler('history', view_history),
        MessageHandler(filters.Regex("^📊 View History$"), view_history),
        CallbackQueryHandler(route_history_action, pattern="^(hist_|browse_)")
    ],
    states={
        VIEW_HISTORY: [
            CallbackQueryHandler(view_history, pattern="^back_main$"),
            CallbackQueryHandler(route_history_action, pattern="^(hist_|browse_)"),
            CallbackQueryHandler(show_date_details, pattern="^view_date_")
        ],
        BROWSE_DATES: [
            CallbackQueryHandler(handle_grid_nav, pattern="^(hpage_|back_main|view_date_)")
        ]
    },
    fallbacks=[
        CommandHandler('cancel', view_history),
        # SILENT KILLER SWITCH
        MessageHandler(filters.TEXT, route_intent)
    ],
    
)