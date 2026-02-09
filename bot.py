import os
import sqlite3
import datetime
import csv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# ====================================
# CONFIG
# ====================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")
    
ADMIN_IDS = [483448454]

DB_NAME = "parade.db" # SQLite database will be stored in Render container

(
    ASK_RANK, 
    ASK_NAME, 
    ASK_OFFS, 
    ASK_LEAVES, 
    ASK_LEAVE_START, 
    ASK_LEAVE_END,
    ASK_DUTY_DAY,
    ASK_DUTY_DATE
) = range(8)

RANKS = ["REC", "PTE", "LCP", "CPL", "CFC", 
         "3SG", "2SG", "1SG", "SSG", "MSG",
         "3WO", "2WO", "1WO", "MWO", "SWO", 
         "2LT", "LTA", "CPT", "MAJ", "LTC", "SLTC", "COL"]
         
DUTY_CREDIT = {"FRIDAY": 0.5, "SATURDAY": 1.5, "SUNDAY": 1.0}

# ====================================
# DATABASE
# ====================================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Users table with off/leave balances
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        rank TEXT,
        name TEXT,
        off_balance REAL DEFAULT 0,
        leave_balance INTEGER DEFAULT 0,
        registered_at TEXT
    )
    """)
    
    # Status table
    c.execute("""
    CREATE TABLE IF NOT EXISTS status (
        telegram_id INTEGER PRIMARY KEY,
        state TEXT,
        start_date TEXT,
        end_date TEXT,
        updated_at TEXT
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS duties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        duty_date TEXT,
        day_type TEXT,
        credited REAL,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, rank, name, off_balance, leave_balance):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO users
        (telegram_id, rank, name, off_balance, leave_balance, registered_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id, 
        rank, 
        name, 
        off_balance, 
        leave_quota, 
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def set_status(user_id, state, start_date=None, end_date=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO status
        (telegram_id, state, start_date, end_date, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        state,
        start_date,
        end_date,
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT users.rank, users.name, status.state
        FROM users
        LEFT JOIN status ON users.telegram_id = status.telegram_id
    """)
    rows = c.fetchall()
    conn.close()
    return rows

# =============================
# MENU
# =============================

def user_menu():
    return ReplyKeyboardMarkup(
        [
            ["🟢 Present", "🟡 Off", "🔵 Leave"],
            ["📌 My Status", "❓ Help"]
        ],
        resize_keyboard=True
    )
    
def admin_menu():
    return ReplyKeyboardMarkup(
    [
        ["🟢 Present", "🟡 Off", "🔵 Leave"],
        ["📌 My Status", "❓ Help"],
        ["📋 Parade State", "📊 Strength"],
        ["📤 Export PS CSV"]
    ],
    resize_keyboard=True
)

def is_admin(user_id):
    return user_id in ADMIN_IDS
    
async def require_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_user(update.effective_user.id):
        await update.message.reply_text("❗ You are not registered. Use /start first.")
        return False
    return True

# =============================
# REGISTRATION FLOW
# =============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if get_user(user_id):
        menu = admin_menu() if is_admin(user_id) else user_menu()
        await update.message.reply_text(
            "Welcome back! {rank} {name}",
            reply_markup=menu
        )
        return ConversationHandler.END
        
    welcome_text = (
        "👋 Welcome to the BN HQ Parade Bot!\n"
        "This bot tracks parade state & personnel availability.\n"
        "You will first register your details."
    )
    await update.message.reply_text(welcome_text)
    
    keyboard = [[InlineKeyboardButton(r, callback_data=r)] for r in RANKS]
    await update.message.reply_text(
        "Select your rank:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_RANK
    
async def select_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["rank"] = query.data
    await query.edit_message_text("Enter your name:")
    return ASK_NAME
    
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_date["name"] = update.message.text.upper()
    await update.message.reply_text("Enter your current OFF balance:")
    return ASK_OFFS
    
async def get_offs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["off_balance"] = float(update.message.text)
    await update.message.reply_text("Enter your current LEAVE balance:")
    return ASK_LEAVES
    
async def get_leaves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(
        user_id,
        context.user_data["rank"],
        context.user_data["name"],
        context.user_data["off_balance"],
        int(update.message.text)
    )
    set_status(user_id, "PRESENT")
    
    menu = admin_menu() if is_admin(user_id) else user_menu()
    await update.message.reply_text(
        f"✅ Registration complete,"
        reply_markup=menu
    )
    return ConversationHandler.END
    
# ===========================================
# BUTTON HANDLER
# ===========================================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    today = datetime.date.today().isoformat()
    
    if not get_user(user_id):
        await update.message.reply_text("Please register using /start.")
        return
        
    if text == "🟢 Present":
        set_status(user_id, "PRESENT")
        await update.message.reply_text("🟢 Marked PRESENT.")
        
    elif text == "🟡 Off":
        set_status(user_id, "OFF", today, today)
        await update.message.reply_text("🟡 Marked OFF.")
        
    elif text == "🔵 Leave":
        set_status(user_id, "LEAVE", today, None)
        await status(update, context)
        
    elif text == "📌 My Status":
        await status(update, context)
        
    elif text == "❓ Help":
        await help_command(update, context)
        
    elif is_admin(user_id) and text == "📋 Parade State":
        await parade(update, context)
        
    elif is_admin(user_id) and text == "📊 Strength":
        await strength(update, context)
        
    elif is_admin(user_id) and text == "📤 Export PS CSV":
        await export_csv(update, context)
        
# ============================================
# LEAVE DATE PICKER
# ============================================

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_registration(update, context):
        return ConversationHandler.END
    await update.message.reply_text("Enter LEAVE start date (YYYY-MM-DD):")
    return ASK_LEAVE_START

async def leave_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["leave_start"] = update.message.text
    await update.message.reply_text("Enter LEAVE end date(YYYY-MM-DD):")
    return ASK_LEAVE_END
    
async def leave_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    start = context.user_data["leave_start"]
    end = update.message.text
    
    set_status(
        user_id,
        "LEAVE",
        start,
        end
    )
    await update.message.reply_text("🔵 Leave recorded.")
    return ConversationHandler.END

# ============================================
# STATUS / HELP
# ============================================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT state FROM status WHERE telegram_id=?", (update.effective_user.id,))
    row = c.fetchone()
    conn.close()
    await update.message.reply_text(f"📌 Status: {row[0] if row else 'PRESENT'}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Use the menu buttons to update your status.\n"
        "Admins have parade & strength controls."
    )
    await update.message.reply_text(text)
# ============================================
# ADMIN COMMANDS
# ============================================
    
async def parade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    present, off, leave_list = [], [], []
    
    for rank, name, state in users:
        entry = f"{rank} {name}"
        if state == "OFF":
            off.append(entry)
        elif state == "LEAVE":
            leave_list.append(entry)
        else:
            present.append(entry)
            
    await update.message.reply_text(
        f"📋 PARADE STATE\n\n"
        f"PRESENT ({len(present)}):\n" + "\n".join(present) + "\n\n"
        f"OFF ({len(off)}):\n" + "\n".join(off) + "\n\n"
        f"LEAVE ({len(leave_list)}):\n" + "\n".join(leave_list)
    )
    
async def strength(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    count = {}
    for rank, _, _ in users:
        count[rank] = count.get(rank, 0) + 1
    await update.message.reply_text(
        "📊 STRENGTH\n\n" + "\n".join(f"{r}: {c}" for r, c in count.items()
    )

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    with open("parade.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Name", "Status"])
        writer.writerows(users)
    await update.message.reply_document(open("parade.csv", "rb"))
    
# ======================================
# DUTY ENTRY (FRI/SAT/SUN)
# ======================================

def get_upcoming_dates(target_weekday):
    today = datetime.date.today()
    dates = []
    for i in in range(1, 15):
        d = today + datetime.timedelta(days=i)
        if d.weekday() == target_weekday:
            dates.apped(d)
    return dates
    
async def duty_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_registration(update, context):
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(d, callback_data=d)] for d in ["FRIDAY", "SATURDAY", "SUNDAY"]]
    await update.message.reply_text("Select duty dates:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_DUTY_DAY
    
async def duty_pick_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["duty_day"] = query.data
    
    weekday_map = {"FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6}
    dates = get_upcoming_dates(weekday_map[query.data])
    
    keyboard = [[InlineKeyboardButton(d.isoformat(), callback_data=d.isoformat())] for d in dates]
    await query.edit_message_text("Select the date you did duty:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_DUTY_DATE
    
async def duty_pick_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    duty_date = query.data
    day = context.user_data["duty_day"]
    credit = DUTY_CREDIT[day]
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM duties WHERE telegram_id=? AND duty_date=?", (user_id, duty_date))
    if c.fetchone():
        await query.edit_message_text("⚠️ Duty already recorded for this date.")
        conn.close()
        return ConversationHandler.END
        
    c.execute("INSERT INTO duties (telegram_id, duty_date, day_type, credited, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, duty_date, day, credit, datetime.datetime.now().isoformat()))
              
    c.execute("UPDATE users SET off_balance = off_balance + ? WHERE telegram_id=?", (credit, user_id))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(f"✅ Duty recorded: {day} ({duty_date}) + {credit} OFF credited")
    return ConversationHandler.END
    
# ======================================
# MIDNIGHT AUTO RESET
# ======================================

async def midnight_reset(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today().isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("UPDATE status SET state='PRESENT' WHERE state='OFF'")
    
    c.execute("UPDATE status SET state='PRESENT' WHERE state='LEAVE' AND end_date < ?", (today,))
    
    conn.commit()
    conn.close()
    
    for admin in ADMIN_IDS:
        await context.bot.send_mesasage(
            chat_id=admin, 
            text="✅ Midnight parade reset complete."
        )

# ======================================
# MAIN
# ======================================

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Registration handler
    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_RANK: [CallbackQueryHandler(select_rank)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)]
            ASK_OFFS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_offs)],
            ASK_LEAVES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leaves)],
            ASK_LEAVE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_start)],
            ASK_LEAVE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_end)],]
            ASK_DUTY_DAY: [CallbackQueryHandler(duty_pick_day)],
            ASK_DUTY_DATE: [CallbackQueryHandler(duty_pick_date)],
        },
        fallbacks=[]
    ))
    
    app.add_handler(reg_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    
    app.job_queue.run_daily(
        midnight_reset,
        time=datetime.time(hour=0, minute=0)
    )
    
    print("Bot running...")
    app.run_polling()
    
if __name__ == "__main__":
    main()