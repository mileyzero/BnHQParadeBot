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

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

ADMIN_IDS = [483448454]

DB_NAME = "parade.db"

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
        leave_balance,
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
            "Welcome back!",
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
    # FIXED: context.user_date -> context.user_data
    context.user_data["name"] = update.message.text.upper()
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
        "✅ Registration complete!",
        reply_markup=menu
    )
    return ConversationHandler.END

# ======================================
# DUTY ENTRY HELPERS
# ======================================

def get_upcoming_dates(target_weekday):
    today = datetime.date.today()
    dates = []
    for i in range(1, 15):
        d = today + datetime.timedelta(days=i)
        if d.weekday() == target_weekday:
            dates.append(d)
    return dates

# ======================================
# MIDNIGHT RESET
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
        await context.bot.send_message(
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
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_OFFS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_offs)],
            ASK_LEAVES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leaves)],
            ASK_LEAVE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_start)],
            ASK_LEAVE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_end)],
            ASK_DUTY_DAY: [CallbackQueryHandler(duty_pick_day)],
            ASK_DUTY_DATE: [CallbackQueryHandler(duty_pick_date)],
        },
        fallbacks=[]
    )
    
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