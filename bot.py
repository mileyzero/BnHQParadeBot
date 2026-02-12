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

ASK_RANK, ASK_NAME, ASK_OFFS, ASK_LEAVES, LEAVE_START, LEAVE_END, OFF_TYPE, ASK_OFF_DATE = range(8)

RANKS = [
    "REC", "PTE", "LCP", "CPL", "CFC",
    "3SG", "2SG", "1SG", "SSG", "MSG",
    "3WO", "2WO", "1WO", "MWO", "SWO",
    "2LT", "LTA", "CPT", "MAJ", "LTC", "SLTC", "COL"
]

# ====================================
# DATABASE
# ====================================

def init_db():
    print("Running init_db()...")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # users table with off/leave counters
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        rank TEXT,
        name TEXT,
        registered_at TEXT
    )
    """)
    
    # Add leave_counter if missing 
    try:
        c.execute("ALTER TABLE users ADD COLUMN leave_counter INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Column already exists
        
    # Add off_counter if missing
    try:
        c.execute("ALTER TABLE users ADD COLUMN off_counter REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Column already exists

    # status table
    c.execute("""
    CREATE TABLE IF NOT EXISTS status (
        telegram_id INTEGER PRIMARY KEY,
        state TEXT,
        start_date TEXT,
        end_date TEXT,
        updated_at TEXT
    )
    """)
    
    # Add off_type if missing
    try:
        c.execute("ALTER TABLE status ADD COLUMN off_type TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    
    # leaves table
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

def set_status(user_id, state, start_date=None, end_date=None, off_type=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO status
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        state,
        start_date,
        end_date,
        datetime.datetime.now().isoformat(),
        off_type
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

def add_leave(user_id, start_date, end_date, leave_days):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leaves (telegram_id, start_date, end_date, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, start_date, end_date, datetime.datetime.now().isoformat()))
    conn.commit()
    
    # Deduct leave days from user's leave_counter
    c.execute("UPDATE users SET leave_counter = leave_counter - ? WHERE telegram_id=?", (leave_days, user_id))
    conn.commit()
    conn.close()

def increment_off(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET off_counter = off_counter + ? WHERE telegram_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    
# =====================================   
# HELPER FUNCTIONS
# =====================================

def get_today_status_display(user_id):
    conn = sqlite3.connect("parade.db")
    c = conn.cursor()
    
    today = datetime.date.today().strftime("%Y-%m-%d")
    
    c.execute("""
        SELECT state, start_date, end_date, off_type
        FROM status
        WHERE telegram_id=?
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    
    for state, start_date, end_date, off_type in rows:
        if start_date and end_date:
            if start_date <= today <= end_date:
                if state == "OFF":
                    if off_type == "AM":
                        return "🟡 AM OFF"
                    elif off_type == "PM":
                        return "🟡 PM OFF"
                    else:
                        return ""
                        
                elif state == "LEAVE":
                    return "🔵 LEAVE"
    return "🟢 PRESENT"

# ====================================
# DATE CONFLICT CHECKER
# ====================================

def check_date_conflict(user_id, new_start: datetime.date, new_end: datetime.date) -> str:
    """
    Check if the proposed date range conflicts with existing OFFs or LEAVEs.
    Returns a message string if there's a conflict, or None if no conflict.
    """
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Check existing leaves
    c.execute("SELECT start_date, end_date FROM leaves WHERE telegram_id=?", (user_id,))
    leaves = c.fetchall()
    for leave_start, leave_end in leaves:
        leave_start_dt = datetime.datetime.strptime(leave_start, "%Y-%m-%d").date()
        leave_end_dt = datetime.datetime.strptime(leave_end, "%Y-%m-%d").date()
        # If new range overlaps LEAVE
        if new_start <= leave_end_dt and new_end >= leave_start_dt:
            conn.close()
            return f"❌ Conflict with LEAVE from {leave_start} to {leave_end}."
    
    # Check existing offs
    c.execute("SELECT start_date, end_date FROM status WHERE telegram_id=? AND state='OFF'", (user_id,))
    offs = c.fetchall()
    for off_start, off_end in offs:
        off_start_dt = datetime.datetime.strptime(off_start, "%Y-%m-%d").date()
        off_end_dt = datetime.datetime.strptime(off_end, "%Y-%m-%d").date()
        # If new range overlaps OFF
        if new_start <= off_end_dt and new_end >= off_start_dt:
            conn.close()
            return f"❌ Conflict with OFF on {off_start}."
    
    conn.close()
    return None
    

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

def off_options_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("AM OFF (0.5)", callback_data="AM")],
        [InlineKeyboardButton("PM OFF (0.5)", callback_data="PM")],
        [InlineKeyboardButton("FULL DAY OFF (1)", callback_data="FULL")]
    ])

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

    save_user(update.effective_user.id, rank, name, offs, leaves)
    set_status(update.effective_user.id, "PRESENT")

    menu = admin_menu() if is_admin(user_id) else user_menu()
    
    await update.message.reply_text(
        f"✅ Registration complete!\n{rank} {name}\nStatus: PRESENT\nOFFs: {offs}, LEAVEs: {leaves}",
        reply_markup=menu
    )
    return ConversationHandler.END

# ====================================
# OFF HANDLER
# ====================================

async def off_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Select OFF type:",
        reply_markup=off_options_keyboard()
    )
    return OFF_TYPE
    
async def off_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data["off_type"] = query.data
    
    await query.edit_message_text(
        "Enter OFF date (YYYY-MM-DD):"
    )
    
    return ASK_OFF_DATE

async def off_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    date_text = update.message.text.strip()
    
    try:
        off_date = datetime.datetime.strptime(date_text, "%Y-%m-%d").date()
    except:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return ASK_OFF_DATE
        
    today = datetime.date.today()
    
    # ❌ Prevent past dates
    if off_date < today:
        await update.message.reply_text("❌ You cannot select a past date.")
        return ASK_OFF_DATE
        
    off_type = context.user_data.get("off_type")
    
    off_map = {
        "AM" : 0.5,
        "PM" : 0.5,
        "FULL" : 1.0
    }
    
    off_amount = off_map.get(off_type, 0)
    
    # Check remaining OFF balance
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT off_counter FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    remaining_off = row[0] if row else 0
    
    if off_amount > remaining_off:
        conn.close()
        await update.message.reply_text(
            f"❌ You only have {remaining_off} OFF remaining."
        )
        return ConversationHandler.END
        
    # Check conflicts using helper
    conflict_msg = check_date_conflict(user_id, off_date, off_date)
    if conflict_msg:
        await update.message.reply_text(conflict_msg + " Please choose another OFF date.")
        return ASK_OFF_DATE
        
    # Deduct OFF
    c.execute(
        "UPDATE users SET off_counter = off_counter - ? WHERE telegram_id=?",
        (off_amount, user_id)
    )
    conn.commit()
    conn.close()
    
    # Update status
    set_status(user_id, "OFF", date_text, date_text, off_type=off_type)
    
    menu = admin_menu() if is_admin(user_id) else user_menu()
    
    # Display message with type
    off_display = {
        "AM": "AM OFF",
        "PM" : "PM OFF",
        "FULL" : "FULL DAY"
    }.get(off_type, "FULL DAY")
    
    await update.message.reply_text(
        f"🟡 OFF applied on {date_text}\n"
        f"Type: {off_type}\n"
        f"Remaining OFFs: {remaining_off - off_amount}",
        reply_markup=menu
    )
    
    context.user_data.pop("off_type", None)
    
    return ConversationHandler.END
    
# ====================================
# LEAVE HANDLER
# ====================================

async def start_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT leave_counter FROM users WHERE telegram_id=?", (user_id,))
    leaves = c.fetchone()[0]
    conn.close()
    if leaves <= 0:
        await update.message.reply_text("❌ You have no remaining leaves.")
        return ConversationHandler.END
    
    await update.message.reply_text("Enter start date of leave (YYYY-MM-DD):")
    return LEAVE_START
    
async def leave_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = update.message.text.strip()
    
    try:
        start_date = datetime.datetime.strptime(start, "%Y-%m-%d").date()
    except:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return LEAVE_START
        
    today = datetime.date.today()
    
    if start_date < today:
        await update.message.reply_text("❌ You cannot select a past date. Please choose today or a future date.")
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
        start_date = datetime.datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(end, "%Y-%m-%d").date()
    except:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return LEAVE_END
        
    today = datetime.date.today()
    if end_date < today:
        await update.message.reply_text("❌ End date cannot be in the past. Choose today or later.")
        return LEAVE_END
        
    if end_date < start_date:
        await update.message.reply_text("End date cannot be before start date.")
        return LEAVE_END
    
    # Check for conflicts with OFF dates or existing leaves
    conflict_msg = check_date_conflict(user_id, start_date, end_date)
    if conflict_msg:
        await update.message.reply_text(conflict_msg + " Please choose different leave dates.")
        return LEAVE_START
    
    # Count weekdays only
    leave_days = sum(
        1
        for i in range((end_date - start_date).days + 1)
        if (start_date + datetime.timedelta(days=i)).weekday() < 5
    )
    
    # Check if user has enough leaves
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT leave_counter FROM users WHERE telegram_id=?", (user_id,))
    remaining_leaves = c.fetchone()[0]
    conn.close()
    
    if leave_days > remaining_leaves:
        await update.message.reply_text(f"❌ You only have {remaining_leaves} LEAVEs remaining. Cannot apply {leave_days} days.")
        return ConversationHandler.END
        
    # Save leave record and update status
    add_leave(user_id, start, end, leave_days)
    set_status(user_id, "LEAVE", start, end)
    
    menu = admin_menu() if is_admin(user_id) else user_menu()
    await update.message.reply_text(f"🔵 Leave applied: {start} to {end} ({leave_days} days)", reply_markup=menu)
    
    context.user_data.pop("leave_start", None)
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
        await update.message.reply_text("Select OFF type:", reply_markup=off_options_keyboard())

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
# COMMANDS
# ====================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use buttons to mark Present, Off, or Leave.\nAdmins have extra commands."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = datetime.date.today()
    
    # Open DB
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get current status
    c.execute("SELECT state, start_date, end_date FROM status WHERE telegram_id=?", (user_id,))
    status_row = c.fetchone()
    
    # Get OFFs and LEAVEs
    c.execute("SELECT off_counter, leave_counter FROM users WHERE telegram_id=?", (user_id,))
    counters = c.fetchone()
    conn.close()
    
    off_counter = counters[0] if counters else 0
    leave_counter = counters[1] if counters else 0
    
    # Default status text
    if status_row:
        state, start_date, end_date = status_row
        status_text = state
    else:
        state, start_date, end_date = "PRESENT", None, None
        status_text = "PRESENT"
        
    # --- OFFs taken ---
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT start_date, end_date, off_type FROM status WHERE telegram_id=? AND state='OFF'", (user_id,))
    offs_taken = c.fetchall()
    
    off_text = ""
    for off_start, off_end, off_type_db in offs_taken:
        off_dt_start = datetime.datetime.strptime(off_start, "%Y-%m-%d").date()
        off_dt_end = datetime.datetime.strptime(off_end, "%Y-%m-%d").date()
        if off_dt_end >= today: # Show current/future OFF
            if off_type_db == "AM":
                off_type_display = "(AM OFF)"
            elif off_type_db == "PM":
                off_type_display = "(PM OFF)"
            else:
                off_type_display = "(FULL DAY)"
                
            if off_dt_start == off_dt_end:
                off_text += f"\n🟡 Off Taken: {off_dt_start.strftime('%d %b')} {off_type_display}"
            else:
                off_text += f"\n🟡 Off Taken: {off_dt_start.strftime('%d %b')} - {off_dt_end.strftime('%d %b')} {off_type_display}"
                
    # --- LEAVEs taken ---
    c.execute("SELECT start_date, end_date FROM leaves WHERE telegram_id=?", (user_id,))
    leaves_taken = c.fetchall()
    
    leave_text = ""
    for leave_start, leave_end in leaves_taken:
        leave_dt_start = datetime.datetime.strptime(leave_start, "%Y-%m-%d").date()
        leave_dt_end = datetime.datetime.strptime(leave_end, "%Y-%m-%d").date()
        
        if leave_dt_end >= today:
            if leave_dt_start == leave_dt_end:
                leave_text += f"\n🔵 Leave Taken: {leave_dt_start.strftime('%d %b')}"
            else:
                leave_text += f"\n🔵 Leaves Taken: {leave_dt_start.strftime('%d %b')} - {leave_dt_end.strftime('%d %b')}"
    
    conn.close()
    
    # Daily summary
    daily_summary = ""
    if state == "OFF" and start_date and end_date:
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        if start_dt <= today <= end_dt:
            daily_summary = "🟡 You are OFF today."
    elif state == "LEAVE" and start_date and end_date:
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        if start_dt <= today <= end_dt and today.weekday() < 5: # Weekdays only
            daily_summary = "🔵 You are on LEAVE today."
    
    # Full status message
    text = (
        f"📌 Status: {status_text}\n"
        f"🟡 Remaining OFFs: {off_counter}\n"
        f"🔵 Remaining LEAVEs: {leave_counter}"
    )
    if off_text:
        text += f"{off_text}"
    if leave_text:
        text += f"{leave_text}"
    if daily_summary:
        text += f"\n{daily_summary}"
        
    await update.message.reply_text(text)

async def parade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect("parade.db")
    c = conn.cursor()
    
    c.execute("SELECT rank, name FROM users WHERE telegram_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        await update.message.reply_text("You are not registered.")
        return
    
    rank, name = user
    availability = get_today_status_display(user_id)
    
    text = (
        f"📋 PARADE STATE\n\n"
        f"Rank: {rank}\n"
        f"Name: {name}\n"
        f"Availability Today: {availability}"
    )
    
    await update.message.reply_text(text)


async def strength(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("parade.db")
    c = conn.cursor()
    
    c.execute("SELECT telegram_id, rank, name FROM users")
    users = c.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("No users registered.")
        return
        
    text = "📊 Bn HQ UNIT STRENGTH\n\n"
    
    for telegram_id, rank, name in users:
        availability = get_today_status_display(telegram_id)
        text += f"{rank} {name} — {availability}\n"
        
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
    
    off_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🟡 Off$"), off_selection)],
        states={
            OFF_TYPE: [CallbackQueryHandler(off_type_selected, pattern="^(AM|PM|FULL)$")],
            ASK_OFF_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, off_date_input)],
        },
        fallbacks=[],
    )
    
    bot_app.add_handler(conv)
    bot_app.add_handler(leave_conv)
    bot_app.add_handler(off_conv)
    
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("status", status))
    
    bot_app.initialize()
    bot_app.run_polling()
    
if __name__ == "__main__":
    main()