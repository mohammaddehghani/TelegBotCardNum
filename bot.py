import logging
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
import os

# --- Load Env ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
PGHOST = os.getenv("PGHOST")
PGPORT = os.getenv("PGPORT")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")

# --- Logging ---
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

def get_conn():
    return psycopg2.connect(
        host=PGHOST, port=PGPORT, database=PGDATABASE,
        user=PGUSER, password=PGPASSWORD
    )

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        full_name TEXT,
        is_admin BOOLEAN DEFAULT FALSE,
        access_granted BOOLEAN DEFAULT FALSE
    );
    CREATE TABLE IF NOT EXISTS persons (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS banks (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        person_id INTEGER REFERENCES persons(id)
    );
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        bank_id INTEGER REFERENCES banks(id),
        account_number TEXT,
        card_number TEXT,
        iban TEXT,
        card_image_url TEXT
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

def ensure_user(update: Update):
    conn = get_conn()
    cur = conn.cursor()
    tid = update.effective_user.id
    name = update.effective_user.full_name
    cur.execute("SELECT id FROM users WHERE telegram_id = %s", (tid,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (telegram_id, full_name, is_admin) VALUES (%s, %s, %s)",
            (tid, name, tid == ADMIN_ID)
        )
        conn.commit()
    cur.close()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    conn = get_conn()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT is_admin, access_granted FROM users WHERE telegram_id = %s", (update.effective_user.id,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user["is_admin"]:
        keyboard = [
            [InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users")],
            [InlineKeyboardButton("📁 دفترچه حساب‌ها", callback_data="book_main")]
        ]
        await update.message.reply_text("سلام ادمین 👑", reply_markup=InlineKeyboardMarkup(keyboard))
    elif user["access_granted"]:
        await update.message.reply_text("👤 لطفاً یک شخص را انتخاب کنید ...")
    else:
        await update.message.reply_text("❌ شما دسترسی ندارید")
        await update.message.reply_text(
            f"یونیک آی‌دی شما:\n`{update.effective_user.id}`\nاین کد را به {ADMIN_USERNAME} بدهید.",
            parse_mode="Markdown"
        )

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "admin_users":
        conn = get_conn()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT full_name, telegram_id, access_granted FROM users ORDER BY id ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        text = ""
        for r in rows:
            status = "✅ فعال" if r["access_granted"] else "❌ غیرفعال"
            text += f"{r['full_name'] or '---'} - `{r['telegram_id']}` - {status}\n"
        kb = [
            [InlineKeyboardButton("➕ افزودن", callback_data="grant_access")],
            [InlineKeyboardButton("➖ حذف", callback_data="revoke_access")]
        ]
        await q.message.reply_text(text or "هیچ کاربری نیست", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin_menu, pattern="^admin_users$"))
    app.run_polling()

if __name__ == "__main__":
    main()
