import os
import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import database as db
from handlers.router import route_intent

# --- STATES ---
VIEW_HISTORY = 0

# --- ENTRY POINT ---
async def view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the Time Period Selection Menu."""
    if update.message:
        msg_func = update.message.reply_text
    else:
        await update.callback_query.answer()
        msg_func = update.callback_query.edit_message_text
    
    kb = [
        [InlineKeyboardButton("📅 Today", callback_data="hist_today"), InlineKeyboardButton("⏮ Yesterday", callback_data="hist_yesterday")],
        [InlineKeyboardButton("🗓 Last 7 Days", callback_data="hist_week"), InlineKeyboardButton("📆 Last Month", callback_data="hist_month")]
    ]
    await msg_func("📊 **History & Reports**\nSelect a period:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return VIEW_HISTORY

# --- PERIOD LOGIC ---
async def show_history_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    period = query.data.replace('hist_', '')
    
    today = datetime.datetime.now().date()
    
    if period == 'today':
        start_date = today
        end_date = today
        title = "Today"
    elif period == 'yesterday':
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
        title = "Yesterday"
    elif period == 'week':
        start_date = today - datetime.timedelta(days=7)
        end_date = today
        title = "Last 7 Days"
    elif period == 'month':
        start_date = today - datetime.timedelta(days=30)
        end_date = today
        title = "Last 30 Days"
        
    data = db.get_entries_by_date_range(user_id, start_date, end_date)
    
    if not data:
        await query.edit_message_text(f"📭 **{title}**\nNo logs found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_to_history")]]), parse_mode='Markdown')
        return VIEW_HISTORY

    if period in ['today', 'yesterday']:
        date_key = start_date.strftime("%Y-%m-%d")
        entries = data.get(date_key, {}).get('entries', [])
        await show_single_day_summary(query, entries, title, date_key)
    else:
        await show_multi_day_stats(query, data, title)
        
    return VIEW_HISTORY

async def show_single_day_summary(query, entries, title, date_str):
    if not entries:
        await query.edit_message_text("No entries.")
        return

    # Build the List
    lines = []
    adhoc_count = 0
    evening_done = False
    
    for e in entries:
        if e['landmark_id'] == 99:
            adhoc_count += 1
            continue
        if e['landmark_id'] == 0:
            evening_done = True
            continue
            
        # Routine Spots
        icon = "🟢" if e['status'] == "Healthy" else "🔴" if e['status'] == "Issue" else "🟠"
        name = e.get('landmark_name', f"Spot {e['landmark_id']}")
        lines.append(f"{icon} **{name}**: {e['status']}")

    # Footer Logic
    footer = []
    if evening_done: footer.append("🌙 Evening Summary: ✅ Done")
    if adhoc_count: footer.append(f"📝 Ad-Hoc Notes: {adhoc_count}")
    
    body = "\n".join(lines) if lines else "_No routine checks yet._"
    foot_txt = "\n".join(footer)
    
    summary_text = (f"📊 **Overview: {title}**\n━━━━━━━━━━━━━━\n"
                    f"{body}\n\n{foot_txt}")

    kb = [
        [InlineKeyboardButton(f"📸 View Photos & Notes", callback_data=f"view_date_{date_str}")],
        [InlineKeyboardButton("◀️ Back", callback_data="back_to_history")]
    ]
    await query.edit_message_text(summary_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def show_multi_day_stats(query, data, title):
    total_logs = 0
    issues = 0
    for date_str, day_data in data.items():
        for e in day_data['entries']:
            total_logs += 1
            if e.get('status') == 'Issue': issues += 1
                
    msg = (f"🗓 **Report: {title}**\n"
           f"━━━━━━━━━━━━━━\n"
           f"📥 Total Logs: {total_logs}\n"
           f"⚠️ Issues Flagged: {issues}\n"
           f"✅ Health Rate: {int(((total_logs-issues)/total_logs)*100) if total_logs else 0}%\n\n"
           f"_(Tap 'Today' or 'Yesterday' for details)_")
           
    kb = [[InlineKeyboardButton("◀️ Back", callback_data="back_to_history")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def show_date_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    date_str = query.data.replace('view_date_', '')
    entries = db.get_entries_for_date(user_id, date_str)
    
    summary = f"📊 **Detailed Logs** ({date_str})\n" + "━"*15 + "\n"
    for e in entries:
        t = e.timestamp.strftime('%H:%M')
        lm_name = e.landmark_name
        
        if e.landmark_id == 0: summary += f"🌙 Evening Summary ({t})\n"
        elif e.landmark_id == 99: summary += f"⚠️ Ad-Hoc ({t})\n"
        else: summary += f"{'🟢' if e.status=='Healthy' else '🔴' if e.status=='Issue' else '🟠'} {lm_name}: {e.status}\n"
        
        if e.transcription:
            txt = e.transcription if len(e.transcription) < 100 else e.transcription[:100] + "..."
            summary += f"   ╚ 📝 \"{txt}\"\n"
    
    await query.edit_message_text(summary, parse_mode='Markdown')
    
    for e in entries:
        media = []
        if e.img_wide and os.path.exists(e.img_wide): media.append(InputMediaPhoto(open(e.img_wide, 'rb'), caption=f"{e.landmark_name} (Wide)"))
        if e.img_close and os.path.exists(e.img_close): media.append(InputMediaPhoto(open(e.img_close, 'rb'), caption=f"{e.landmark_name} (Close)"))
        if media: await query.message.reply_media_group(media)
        if e.voice_path and os.path.exists(e.voice_path):
            await query.message.reply_voice(open(e.voice_path, 'rb'), caption=f"🎙 {e.landmark_name}")

    kb = [[InlineKeyboardButton("◀️ Back", callback_data="back_to_history")]]
    await query.message.reply_text("End of report.", reply_markup=InlineKeyboardMarkup(kb))
    return VIEW_HISTORY

# --- EXPORT ---
history_handler = ConversationHandler(
    entry_points=[
        CommandHandler('history', view_history),
        MessageHandler(filters.Regex("^📊 View History$"), view_history),
        CallbackQueryHandler(show_history_period, pattern="^hist_")
    ],
    states={
        VIEW_HISTORY: [
            CallbackQueryHandler(view_history, pattern="^back_to_history$"),
            CallbackQueryHandler(show_history_period, pattern="^hist_"),
            CallbackQueryHandler(show_date_details, pattern="^view_date_"),
            MessageHandler(filters.Regex("^📊 View History$"), view_history)
        ]
    },
    fallbacks=[CommandHandler('cancel', view_history), MessageHandler(filters.TEXT & ~filters.COMMAND, route_intent)]
)