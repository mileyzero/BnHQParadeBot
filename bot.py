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

ASK_RANK, ASK_NAME = range(2)

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
        ["🔄 Reset PS", "📤 Export PS CSV"]
    ],
    resize_keyboard=True
)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# =============================
# REGISTRATION
# =============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if get_user(user_id):
        menu = admin_menu() if is_admin(user_id) else user_menu()
        await update.message.reply_text(
            "Welcome back! Choose an option below 👇",
            reply_markup=menu
        )
        return ConversationHandler.END
        
    await update.message.reply_text(
        "👋 Welcome to the BN HQ Parade Bot!\n\n"
        "This bot tracks parade state and personnel availability.\n"
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
    
    save_user(user_id, rank, name)
    set_status(user_id, "PRESENT")
    
    menu = admin_menu() if is_admin(user_id) else user_menu()
    
    await update.message.reply_text(
        f"✅ Registration complete\n\n{rank} {name}\nStatus: PRESENT",
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
        await update.message.reply_text("Please register with /start first.")
        return
        
    if text == "🟢 Present":
        set_status(user_id, "PRESENT")
        await update.message.reply_text("🟢 Marked PRESENT.")
        
    elif text == "🟡 Off":
        set_status(user_id, "OFF", today, today)
        await update.message.reply_text("🟡 Marked OFF.")
        
    elif text == "🔵 Leave":
        set_status(user_id, "LEAVE", today, None)
        await update.message.reply_text("🔵 Marked LEAVE.")
        
    elif text = "📌 My Status":
        await status(update, context)
        
    elif text = "❓ Help":
        await help_command(update, context)
        
    elif is_admin(user_id) and text == "📋 Parade State":
        await parade(update, context)
        
    elif is_admin(user_id) and text == "📊 Strength":
        await strength(update, context)
        
    elif is_admin(user_id) and text == "🔄 Reset PS":
        await reset_db(update, context)
        
    elif is_admin(user_id) and text == "📤 Export PS CSV":
        await export_csv(update, context)
        
# ============================================
# COMMANDS (BACKUP)
# ============================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use the buttons below to update your status.\n"
        "Admins have additional controls."
    )
    
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT state FROM status WHERE telegram_id=?", (update.effective_user.id,))
    row = c.fetchone()
    conn.close()
    await update.message.reply_text(f"📌 Status: {row[0] if row else 'PRESENT'}")
    
async def parade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    present, off, leave = [], [], []
    
    for rank, name, state in users:
        entry = f"{rank} {name}"
        if state == "OFF":
            off.append(entry)
        elif state == "LEAVE":
            leave.append(entry)
        else:
            present.append(entry)
            
    await update.message.reply_text(
        f"📋 PARADE STATE\n\n"
        f"PRESENT ({len(present)}):\n" + "\n".join(present) + "\n\n"
        f"OFF ({len(off}):\n" + "\n".join(off) + "\n\n"
        f"LEAVE ({len(leave)}):\n" + "\n".join(leave)
    )
    
async def strength(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    count = {}
    for rank, _, _ in users:
        count[rank] = count.get(rank, 0) + 1
    text = "📊 STRENGTH\n\n" + "\n".join(f"{r}: {c}" for r, c in count.items())
    await update.message.reply_text(text)

async def reset_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
        os.remove(DB_NAME)
        init_db()
        await update.message.reply_text("🔄 Parade Reset.")
        
async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    with open("parade.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Name", "Status"])
        writer.writerows(users)
    await update.message.reply_document(open("parade.csv", "rb"))
    
# ======================================
# MAIN
# ======================================

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_RANK: [CallbackQueryHandler(select_rank)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)]
        },
        fallbacks=[]
    ))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    app.add_handler(CommandHandler("help", help_command))
    
    print("Bot running...")
    app.run_polling()
    
if __name__ == "__main__":
    main()
