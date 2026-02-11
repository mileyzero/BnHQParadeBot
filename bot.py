import os
import asyncio
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

ASK_RANK, ASK_NAME, ASK_OFFS, ASK_LEAVES, LEAVE_START, LEAVE_END = range(6)

RANKS = [
    "REC", "PTE", "LCP", "CPL", "CFC",
    "3SG", "2SG", "1SG", "SSG", "MSG",
    "3WO", "2WO", "1WO", "MWO", "SWO",
    "2LT", "LTA", "CPT", "MAJ", "LTC", "SLTC", "COL"
]

# ====================================
# DATABASE
# ====================================

DB_NAME = "parade.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

# ====================================
# USERS TABLE
# ====================================
# Create table with only essential columns first

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        rank TEXT,
        name TEXT,
        registered_at TEXT
    )
    """)

    # Ensure 'off_counter' column exists
    c.execute("PRAGMA table_info(users)")
    existing_columns = [col[1] for col in c.fetchall()]
    
    if "off_counter" not in existing_columns:
        c.execute("ALTER TABLE users ADD COLUMN off_counter REAL DEFAULT 0")
    if "leave_counter" not in existing_columns:
        c.execute("ALTER TABLE users ADD COLUMN leave_counter INTEGER DEFAULT 0")

    # =====================================
    # STATUS TABLE
    # =====================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS status (
        telegram_id INTEGER PRIMARY KEY,
        state TEXT,
        start_date TEXT,
        end_date TEXT,
        updated_at TEXT
    )
    """)

    # =========================================
    # LEAVES TABLE
    # =========================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS leaves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        start_date TEXT,
        end_date TEXT,
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


def save_user(user_id, rank, name, off_counter=0.0, leave_counter=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO users
        (telegram_id, rank, name, registered_at, off_counter, leave_counter)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, rank, name, datetime.datetime.now().isoformat(), off_counter, leave_counter))
    conn.commit()
    conn.close()

def set_status(user_id, state, start_date=None, end_date=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO status
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
        SELECT users.rank, users.name, users.off_counter, users.leave_counter, status.state
        FROM users
        LEFT JOIN status ON users.telegram_id = status.telegram_id
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def add_leave(user_id, start_date, end_date):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leaves (telegram_id, start_date, end_date, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, start_date, end_date, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    # increment leave counter
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET leave_counter = leave_counter + 1 WHERE telegram_id=?", (user_id,))
    conn.commit()
    conn.close()


def increment_off(user_id, date):
    # Friday 0.5, Saturday 1.5, Sunday 1
    weekday = date.weekday()
    add = 0
    if weekday == 4:  # Friday
        add = 0.5
    elif weekday == 5:  # Saturday
        add = 1.5
    elif weekday == 6:  # Sunday
        add = 1
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET off_counter = off_counter + ? WHERE telegram_id=?", (add, user_id))
    conn.commit()
    conn.close()


# ====================================
# MENUS
# ====================================

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
            ["🔄 Reset Parade", "📤 Export CSV"]
        ],
        resize_keyboard=True
    )


def is_admin(user_id):
    return user_id in ADMIN_IDS


# ====================================
# REGISTRATION
# ====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if get_user(user_id):
        menu = admin_menu() if is_admin(user_id) else user_menu()
        await update.message.reply_text("Welcome back! 👇", reply_markup=menu)
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Welcome to the Bn HQ Parade Bot!\n"
        "Track your offs, leaves, and parade state.\n"
        "Let's register you first."
    )

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
    user_id = update.effective_user.id
    name = update.message.text.upper()
    rank = context.user_data["rank"]

    # Ask user how many offs they have
    await update.message.reply_text("Enter how many OFFs you already have (e.g., 0, 1.5):")
    context.user_data["reg_name"] = name
    context.user_data["reg_rank"] = rank
    return ASK_OFFS


async def get_offs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        offs = float(update.message.text)
    except:
        await update.message.reply_text("Please enter a valid number for OFFs.")
        return ASK_OFFS
    context.user_data["offs"] = offs
    await update.message.reply_text("Enter how many LEAVEs you already have (e.g., 0,1,2):")
    return ASK_LEAVES


async def get_leaves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        leaves = int(update.message.text)
    except:
        await update.message.reply_text("Please enter a valid number for LEAVEs.")
        return ASK_LEAVES

    name = context.user_data["reg_name"]
    rank = context.user_data["reg_rank"]
    offs = context.user_data["offs"]

    save_user(user_id, rank, name, offs, leaves)
    set_status(user_id, "PRESENT")

    menu = admin_menu() if is_admin(user_id) else user_menu()
    
    await update.message.reply_text(
        f"✅ Registration complete!\n{rank} {name}\nStatus: PRESENT\nOFFs: {offs}, LEAVEs: {leaves}",
        reply_markup=menu
    )
    return ConversationHandler.END


# ====================================
# BUTTON HANDLER
# ====================================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    today = datetime.date.today()

    if not get_user(user_id):
        await update.message.reply_text("Please register with /start first.")
        return

    if text == "🟢 Present":
        set_status(user_id, "PRESENT")
        await update.message.reply_text("🟢 Marked PRESENT.")

    elif text == "🟡 Off":
        set_status(user_id, "OFF", today.isoformat(), today.isoformat())
        increment_off(user_id, today)
        await update.message.reply_text("🟡 Marked OFF. Counter updated based on day.")

    elif text == "📌 My Status":
        await status(update, context)

    elif text == "❓ Help":
        await help_command(update, context)

    elif is_admin(user_id) and text == "📋 Parade State":
        await parade(update, context)

    elif is_admin(user_id) and text == "📊 Strength":
        await strength(update, context)

    elif is_admin(user_id) and text == "🔄 Reset Parade":
        await reset_db(update, context)

    elif is_admin(user_id) and text == "📤 Export CSV":
        await export_csv(update, context)

    return ConversationHandler.END


# ====================================
# LEAVE HANDLER
# ====================================

async def start_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter start date of leave (YYYY-MM-DD):")
    return LEAVE_START
    
async def leave_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = update.message.text.strip()
    
    try:
        datetime.datetime.strptime(start, "%Y-%m-%d")
    except:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return LEAVE_START
        
    context.user_data["leave_start"] = start
    await update.message.reply_text("Enter end date of leave (YYYY-MM-DD):")
    return LEAVE_END

async def leave_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    end = update.message.text.strip()
    start = context.user_data.get("leave_start")
    
    if not start:
        await update.message.reply_text("Something went wrong. Please press 🔵 Leave again.")
        return ConversationHandler.END
        
    try:
        start_date = datetime.datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.datetime.strptime(end, "%Y-%m-%d")
    except:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return LEAVE_END
        
    if end_date < start_date:
        await update.message.reply_text("End date cannot be before start date.")
        return LEAVE_END
    
    # Save leave record
    add_leave(user_id, start, end)
    
    # Update current status
    set_status(user_id, "LEAVE", start, end)
    
    menu = admin_menu() if is_admin(user_id) else user_menu()
    
    await update.message.reply_text(
        f"🔵 Leave applied:\n{start} to {end}",
        reply_markup=menu()
    )
    
    context.user_data.pop("leave_start", None)
    
    return ConversationHandler.END
    


# ====================================
# COMMANDS
# ====================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use buttons to mark Present, Off, or Leave.\nAdmins have extra commands."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT state FROM status WHERE telegram_id=?", (update.effective_user.id,))
    row = c.fetchone()
    conn.close()
    await update.message.reply_text(f"📌 Status: {row[0] if row else 'PRESENT'}")


async def parade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT users.rank, users.name, users.off_counter, users.leave_counter, status.state
        FROM users
        LEFT JOIN status ON users.telegram_id = status.telegram_id
    """)
    users = c.fetchall()

    text = "📋 PARADE STATE\n\n"
    for rank, name, off_counter, leave_counter, state in users:
        leave_text = f"LEAVEs: {leave_counter}"
        if state == "OFF":
            text += f"🟡 {rank} {name} - OFFs: {off_counter}\n"
        elif state == "LEAVE":
            text += f"🔵 {rank} {name} - {leave_text}\n"
        else:
            text += f"🟢 {rank} {name}\n"
    await update.message.reply_text(text)


async def strength(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    count = {}
    for rank, _, _, _, _ in users:
        count[rank] = count.get(rank, 0) + 1
    text = "📊 STRENGTH\n\n" + "\n".join(f"{r}: {c}" for r, c in count.items())
    await update.message.reply_text(text)


async def reset_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    os.remove(DB_NAME)
    init_db()
    await update.message.reply_text("🔄 Parade reset.")


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    with open("parade.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Name", "OFFs", "LEAVEs", "Status"])
        writer.writerows(users)
    await update.message.reply_document(open("parade.csv", "rb"))


# ====================================
# MAIN
# ====================================

from flask import Flask, request

app_flask = Flask(__name__)

def main():
    init_db()
    
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_RANK: [CallbackQueryHandler(select_rank)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_OFFS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_offs)],
            ASK_LEAVES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leaves)],
        },
        fallbacks=[]
    )

    leave_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🔵 Leave$"), start_leave)
        ],
        states={
            LEAVE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_start)],
            LEAVE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_end)],
        },
        fallbacks=[],
    )
    
    bot_app.add_handler(conv)
    bot_app.add_handler(leave_conv)
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    bot_app.add_handler(CommandHandler("help", help_command))
    
    # =======================================
    # FLASK ROUTES
    # =======================================
    
    # Set webhook
    webhook_url = f"{RENDER_URL}/{BOT_TOKEN}"
    bot_app.bot.set_webhook(webhook_url)
    print(f"Webhook set to {webhook_url}")
    
    # Uptime pinger
    @app_flask.get("/")
    def health():
        return "Bot is running"
        
    # Webhook route for Telegram
    @app_flask.post(f"/{BOT_TOKEN}")
    def webhook():
        data = request.get_json(force=True)
        update = Update.de_json(data, bot_app.bot)
        # Run async bot handler
        asyncio.run(bot_app.process_update(update))
        return "ok"
    
    # Run Flask app
    PORT = int(os.environ.get("PORT", 10000))
    print(f"Bot running with webhook on port {PORT}...")
    app_flask.run(host="0.0.0.0", port=PORT)
    
if __name__ == "__main__":
    main()
