import os
import sqlite3
import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
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

ASK_RANK, ASK_NAME

RANKS = ["REC", "PTE", "LCP", "CPL", "CFC", "3SG", "2SG", "1SG", "SSG", "MSG",
         "3WO", "2WO", "1WO", "MWO", "SWO", "2LT", "LTA", "CPT", "MAJ", "LTC", "SLTC", "COL"]

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

    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, rank, name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO users (telegram_id, rank, name, registered_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, rank, name, datetime.datetime.now().isoformat()))
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
        SELECT users.rank, users.name, status.state
        FROM users
        LEFT JOIN status ON users.telegram_id = status.telegram_id
    """)
    rows = c.fetchall()
    conn.close()
    return rows

# =============================
# HELPERS
# =============================

def is_admin(user_id):
    return user_id in ADMIN_IDS

async def require_registration(update, context):
    if not get_user(update.effective_user.id):
        await update.message.reply_text(
            "! You are not registered. \nUse /start to register first."
        )
        return False
    return True

# =============================
# REGISTRATION
# =============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if get_user(user_id):
        await update.message.reply_text(
            "Welcome back! You are already registered.\n"
            "Use /status to check your current state, or /off /leave /present to update."
        )
        return ConversationHandler.END
        
    # First-time user introduction
    welcome_text = (
        "👋 Welcome to the Bn HQ Parade Bot!\n\n"
        "This bot helps track the unit parade state and personnel availability.\n"
        "You can mark yourself OFF, on LEAVE, or PRESENT and view the current status.\n\n"
        "Commands you can use after registration:\n"
        "/off - mark yourself OFF\n"
        "/leave - mark yourself on LEAVE\n"
        "/present - mark yourself PRESENT\n"
        "/status - check your current status\n"
        "/help - view this help again\n\n"
        "Let's get you registered first!"
    )
    await update.message.reply_text(welcome_text)    

    keyboard = [[InlineKeyboardButton(r, callback_data=r)] for r in RANKS]
    await update.message.reply_text(
        "Please select your rank:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ASK_RANK

async def select_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["rank"] = query.data
    await query.edit_message_text("Please enter your name:")
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.upper()
    rank = context.user_data["rank"]

    save_user(user_id, rank, name)        # Save user info
    set_status(user_id, "PRESENT")        # Set status to PRESENT

    await update.message.reply_text(
        f"✅ Registration complete\n\n"
        f"Rank: {rank}\n"
        f"Name: {name}\n"
        f"Status: PRESENT\n\n"
        "You can now use /off, /leave, /present, or /status commands."
    )
    return ConversationHandler.END

# ======================================
# HELP COMMAND
# ======================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Bn HQ Parade Bot helps track personnel parade state.\n\n"
        "Commands:\n"
        "/off - mark yourself OFF\n"
        "/leave - mark yourself on LEAVE\n"
        "/present - mark yourself PRESENT\n"
        "/status - check your current status\n"
        "/parade - (Admin) show parade state\n"
        "/strength - (Admin) show unit strength"
    )
    await update.message.reply_text(help_text)


# ======================================
# USER COMMANDS
# ======================================

async def off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_registration(update, context):
        return
    today = datetime.date.today().isoformat()
    set_status(update.effective_user.id, "OFF", today, today)
    await update.message.reply_text("🟡 You are marked OFF for today.")

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_registration(update, context):
        return
    today = datetime.date.today().isoformat()
    set_status(update.effective_user.id, "LEAVE", today, None)
    await update.message.reply_text("🔵 You are marked on LEAVE.")

async def present(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_registration(update, context):
        return
    set_status(update.effective_user.id, "PRESENT")
    await update.message.reply_text("🟢 You are marked PRESENT.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_registration(update, context):
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT state FROM status WHERE telegram_id=?
    """, (update.effective_user.id,))
    row = c.fetchone()
    conn.close()

    current_state = row[0] if row else "PRESENT"
    await update.message.reply_text(f"📌 Your current status: {current_state}")

# ====================================
# ADMIN COMMANDS
# ====================================

async def parade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    users = get_all_users()

    present = []
    off = []
    leave = []

    for rank, name, state in users:
        entry = f"{rank} {name}"
        if state == "OFF":
            off.append(entry)
        elif state == "LEAVE":
            leave.append(entry)
        else:
            present.append(entry)

    text = (
        "📋 PARADE STATE\n\n"
        f"TOTAL: {len(users)}\n\n"
        f"PRESENT ({len(present)}):\n" + "\n".join(present) + "\n\n"
        f"OFF ({len(off)}):\n" + "\n".join(off) + "\n\n"
        f"LEAVE ({len(leave)}):\n" + "\n".join(leave)
    )
    await update.message.reply_text(text)

async def strength(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    users = get_all_users()
    rank_count = {}

    for rank, _, _ in users:
        rank_count[rank] = rank_count.get(rank, 0) + 1

    text = "📊 Bn HQ STRENGTH\n\n"
    for rank, count in sorted(rank_count.items()):
        text += f"{rank}: {count}\n"

    await update.message.reply_text(text)

# ================================================
# MAIN
# ================================================

def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_RANK: [CallbackQueryHandler(select_rank)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        },
        fallbacks=[]
    )

    app.add_handler(reg_handler)

    app.add_handler(CommandHandler("off", off))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("present", present))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("parade", parade))
    app.add_handler(CommandHandler("strength", strength))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
