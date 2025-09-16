import os
import logging
import psycopg2
from psycopg2 import pool
from urllib.parse import urlparse
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# ==============================================================================
# بخش ۱: تنظیمات اولیه و دیتابیس
# ==============================================================================

# --- راه‌اندازی اولیه ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

# --- لاگ‌گیری برای دیباگ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- مدیریت اتصال به دیتابیس ---
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
    logger.info("✅ اتصال به استخر دیتابیس PostgreSQL با موفقیت برقرار شد.")
except psycopg2.OperationalError as e:
    logger.error(f"❌ خطا در اتصال به دیتابیس: {e}")
    db_pool = None

def get_db_conn():
    if db_pool:
        return db_pool.getconn()
    return None

def put_db_conn(conn):
    if db_pool:
        db_pool.putconn(conn)

# --- توابع مدیریت دیتابیس ---

def create_tables():
    """جداول مورد نیاز را در صورت عدم وجود ایجاد می‌کند."""
    conn = get_db_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name VARCHAR(255) NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS persons (
                    person_id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS banks (
                    bank_id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id SERIAL PRIMARY KEY,
                    person_id INTEGER REFERENCES persons(person_id) ON DELETE CASCADE,
                    bank_id INTEGER REFERENCES banks(bank_id) ON DELETE CASCADE,
                    card_number VARCHAR(16) UNIQUE NOT NULL,
                    sheba VARCHAR(24) UNIQUE,
                    is_special BOOLEAN DEFAULT FALSE
                );
            """)
            conn.commit()
            logger.info("جداول با موفقیت بررسی و ایجاد شدند.")
    finally:
        put_db_conn(conn)

def add_user_if_not_exists(user_id, first_name):
    """یک کاربر جدید را در صورت عدم وجود اضافه می‌کند."""
    conn = get_db_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            if cur.fetchone():
                return False
            cur.execute("INSERT INTO users (user_id, first_name) VALUES (%s, %s)", (user_id, first_name))
            conn.commit()
            return True
    finally:
        put_db_conn(conn)

def get_all_users():
    conn = get_db_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, first_name FROM users ORDER BY created_at DESC")
            return cur.fetchall()
    finally:
        put_db_conn(conn)

def add_person(name):
    conn = get_db_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO persons (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_db_conn(conn)

def get_all_persons():
    conn = get_db_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT person_id, name FROM persons ORDER BY name")
            return cur.fetchall()
    finally:
        put_db_conn(conn)

def get_person_id_by_name(name):
    conn = get_db_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT person_id FROM persons WHERE name = %s", (name,))
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        put_db_conn(conn)

def add_bank(name):
    conn = get_db_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO banks (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_db_conn(conn)

def get_all_banks():
    conn = get_db_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bank_id, name FROM banks ORDER BY name")
            return cur.fetchall()
    finally:
        put_db_conn(conn)

def get_bank_id_by_name(name):
    conn = get_db_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bank_id FROM banks WHERE name = %s", (name,))
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        put_db_conn(conn)

def add_account(person_id, bank_id, card_number, sheba, is_special):
    conn = get_db_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (person_id, bank_id, card_number, sheba, is_special) VALUES (%s, %s, %s, %s, %s)",
                (person_id, bank_id, card_number, sheba, is_special)
            )
            conn.commit()
            return True
    finally:
        put_db_conn(conn)

def get_accounts_by_person(person_id):
    conn = get_db_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.account_id, b.name, a.card_number, a.sheba, a.is_special
                FROM accounts a
                JOIN banks b ON a.bank_id = b.bank_id
                WHERE a.person_id = %s
            """, (person_id,))
            return cur.fetchall()
    finally:
        put_db_conn(conn)

def get_all_accounts_summary():
    conn = get_db_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.account_id, b.name, a.card_number, p.name
                FROM accounts a
                JOIN banks b ON a.bank_id = b.bank_id
                JOIN persons p ON a.person_id = p.person_id
                ORDER BY p.name, b.name
            """)
            return cur.fetchall()
    finally:
        put_db_conn(conn)

def delete_account(account_id):
    conn = get_db_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts WHERE account_id = %s", (account_id,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_db_conn(conn)

# ==============================================================================
# بخش ۲: منطق ربات تلگرام
# ==============================================================================

# --- تعریف State ها برای مکالمات ---
(
    ADD_PERSON_NAME,
    ADD_BANK_NAME,
    ADD_ACCOUNT_CHOOSE_PERSON, ADD_ACCOUNT_CHOOSE_BANK, ADD_ACCOUNT_CARD_NUMBER, ADD_ACCOUNT_SHEBA, ADD_ACCOUNT_IS_SPECIAL,
    DELETE_CHOOSE_ACCOUNT, DELETE_CONFIRM,
    VIEW_INFO_CHOOSE_PERSON,
) = range(10)

# --- کیبوردها ---
main_menu_keyboard = [
    ["➕ افزودن شخص", "🏦 افزودن بانک"],
    ["📂 افزودن حساب جدید"],
    ["✏️ ویرایش حساب", "🗑 حذف حساب"],
    ["📋 مشاهده اطلاعات"],
    ["👤 مدیریت کاربران (ادمین)"],
]
main_kb = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)
back_kb = ReplyKeyboardMarkup([["🔙 بازگشت"]], resize_keyboard=True)
yes_no_kb = ReplyKeyboardMarkup([["✅ بله"], ["❌ خیر"]], resize_keyboard=True)

# --- توابع عمومی ربات ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if add_user_if_not_exists(user.id, user.first_name):
        logger.info(f"کاربر جدید ثبت‌نام کرد: {user.first_name} ({user.id})")
        await context.bot.send_message(
            ADMIN_ID, f"👤 کاربر جدید به ربات پیوست: {user.first_name} (ID: `{user.id}`)"
        )
    await update.message.reply_text(
        f"سلام {user.first_name}! به دفترچه بانکی دیجیتال خوش آمدی.", reply_markup=main_kb
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("عملیات لغو شد.", reply_markup=main_kb)
    return ConversationHandler.END

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("به منوی اصلی بازگشتی.", reply_markup=main_kb)
    return ConversationHandler.END

# --- افزودن شخص ---
async def add_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("نام شخص جدید را وارد کنید:", reply_markup=back_kb)
    return ADD_PERSON_NAME

async def add_person_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    person_name = update.message.text
    if add_person(person_name):
        await update.message.reply_text(f"✅ شخص «{person_name}» اضافه شد.", reply_markup=main_kb)
    else:
        await update.message.reply_text(f"❌ شخص «{person_name}» از قبل وجود دارد.", reply_markup=main_kb)
    return ConversationHandler.END

# --- افزودن بانک ---
async def add_bank_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("نام بانک جدید را وارد کنید:", reply_markup=back_kb)
    return ADD_BANK_NAME

async def add_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bank_name = update.message.text
    if add_bank(bank_name):
        await update.message.reply_text(f"✅ بانک «{bank_name}» اضافه شد.", reply_markup=main_kb)
    else:
        await update.message.reply_text(f"❌ بانک «{bank_name}» از قبل وجود دارد.", reply_markup=main_kb)
    return ConversationHandler.END

# --- افزودن حساب (مکالمه چند مرحله‌ای) ---
async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    persons = get_all_persons()
    if not persons:
        await update.message.reply_text("❌ ابتدا باید حداقل یک شخص را اضافه کنید.", reply_markup=main_kb)
        return ConversationHandler.END
    
    keyboard = [[p[1]] for p in persons] + [["🔙 بازگشت"]]
    await update.message.reply_text("حساب برای کدام شخص است؟", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return ADD_ACCOUNT_CHOOSE_PERSON

async def add_account_choose_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    person_name = update.message.text
    person_id = get_person_id_by_name(person_name)
    if not person_id:
        await update.message.reply_text("❌ شخص انتخاب شده معتبر نیست.")
        return ADD_ACCOUNT_CHOOSE_PERSON
    
    context.user_data['person_id'] = person_id
    banks = get_all_banks()
    if not banks:
        await update.message.reply_text("❌ ابتدا باید حداقل یک بانک را اضافه کنید.", reply_markup=main_kb)
        return ConversationHandler.END
        
    keyboard = [[b[1]] for b in banks] + [["🔙 بازگشت"]]
    await update.message.reply_text("کدام بانک؟", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return ADD_ACCOUNT_CHOOSE_BANK

async def add_account_choose_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bank_name = update.message.text
    bank_id = get_bank_id_by_name(bank_name)
    if not bank_id:
        await update.message.reply_text("❌ بانک انتخاب شده معتبر نیست.")
        return ADD_ACCOUNT_CHOOSE_BANK
        
    context.user_data['bank_id'] = bank_id
    await update.message.reply_text("شماره کارت (۱۶ رقمی) را وارد کنید:", reply_markup=back_kb)
    return ADD_ACCOUNT_CARD_NUMBER

async def add_account_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    card_number = update.message.text.strip()
    if not (card_number.isdigit() and len(card_number) == 16):
        await update.message.reply_text("❌ شماره کارت باید ۱۶ رقم عددی باشد.")
        return ADD_ACCOUNT_CARD_NUMBER

    context.user_data['card_number'] = card_number
    await update.message.reply_text("شماره شبا (۲۴ رقم، بدون IR) را وارد کنید:", reply_markup=back_kb)
    return ADD_ACCOUNT_SHEBA

async def add_account_sheba(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    sheba = update.message.text.strip()
    if not (sheba.isdigit() and len(sheba) == 24):
        await update.message.reply_text("❌ شماره شبا باید ۲۴ رقم عددی باشد.")
        return ADD_ACCOUNT_SHEBA

    context.user_data['sheba'] = sheba
    await update.message.reply_text("آیا این حساب برای «مصارف خاص» است؟", reply_markup=yes_no_kb)
    return ADD_ACCOUNT_IS_SPECIAL

async def add_account_is_special(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    is_special = True if update.message.text == "✅ بله" else False
    
    add_account(
        person_id=context.user_data['person_id'],
        bank_id=context.user_data['bank_id'],
        card_number=context.user_data['card_number'],
        sheba=context.user_data['sheba'],
        is_special=is_special
    )
    
    await update.message.reply_text("✅ حساب با موفقیت ثبت شد!", reply_markup=main_kb)
    context.user_data.clear()
    return ConversationHandler.END

# --- مشاهده اطلاعات ---
async def view_info_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    persons = get_all_persons()
    if not persons:
        await update.message.reply_text("❌ هیچ شخصی برای نمایش اطلاعات وجود ندارد.", reply_markup=main_kb)
        return ConversationHandler.END

    keyboard = [[p[1]] for p in persons] + [["🔙 بازگشت"]]
    await update.message.reply_text("اطلاعات حساب‌های کدام شخص را می‌خواهید؟", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return VIEW_INFO_CHOOSE_PERSON

async def view_info_choose_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    person_name = update.message.text
    person_id = get_person_id_by_name(person_name)
    if not person_id:
        await update.message.reply_text("❌ شخص یافت نشد.")
        return VIEW_INFO_CHOOSE_PERSON

    accounts = get_accounts_by_person(person_id)
    if not accounts:
        await update.message.reply_text(f"❌ هیچ حسابی برای «{person_name}» ثبت نشده است.", reply_markup=main_kb)
        return ConversationHandler.END

    response_message = f"📂 *اطلاعات حساب‌های {person_name}*:\n\n"
    accounts.sort(key=lambda x: x[4], reverse=True) # مرتب‌سازی بر اساس خاص بودن

    for acc in accounts:
        bank_name, card_number, sheba, is_special = acc[1], acc[2], acc[3], acc[4]
        special_tag = "⭐ (خاص)" if is_special else ""
        # Escape characters for MarkdownV2
        card_number_md = card_number.replace('-', '\\-')
        sheba_md = sheba.replace('-', '\\-')
        
        response_message += (
            f"🏦 *{bank_name}* {special_tag}\n"
            f"💳 شماره کارت: `{card_number_md}`\n"
            f"🧾 شبا: `IR{sheba_md}`\n"
            "--------------------\n"
        )

    await update.message.reply_text(response_message, reply_markup=main_kb, parse_mode='MarkdownV2')
    return ConversationHandler.END

# --- حذف حساب ---
async def delete_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    accounts = get_all_accounts_summary()
    if not accounts:
        await update.message.reply_text("❌ هیچ حسابی برای حذف وجود ندارد.", reply_markup=main_kb)
        return ConversationHandler.END
    
    keyboard = [[f"{acc[3]} - {acc[1]} - {acc[2][-4:]}"] for acc in accounts] + [["🔙 بازگشت"]]
    context.user_data['accounts_list'] = accounts
    
    await update.message.reply_text("کدام حساب را می‌خواهید حذف کنید؟", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return DELETE_CHOOSE_ACCOUNT

async def delete_account_choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text
    chosen_account = None
    for acc in context.user_data['accounts_list']:
        if selection == f"{acc[3]} - {acc[1]} - {acc[2][-4:]}":
            chosen_account = acc
            break
            
    if not chosen_account:
        await update.message.reply_text("❌ انتخاب نامعتبر است.")
        return DELETE_CHOOSE_ACCOUNT

    context.user_data['account_to_delete_id'] = chosen_account[0]
    await update.message.reply_text(
        f"آیا از حذف حساب بانک {chosen_account[1]} ({chosen_account[3]}) به شماره کارت منتهی به {chosen_account[2][-4:]} مطمئن هستید؟",
        reply_markup=yes_no_kb
    )
    return DELETE_CONFIRM

async def delete_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "✅ بله":
        account_id = context.user_data['account_to_delete_id']
        if delete_account(account_id):
            await update.message.reply_text("✅ حساب با موفقیت حذف شد.", reply_markup=main_kb)
        else:
            await update.message.reply_text("❌ خطایی در حذف حساب رخ داد.", reply_markup=main_kb)
    else:
        await update.message.reply_text("عملیات حذف لغو شد.", reply_markup=main_kb)
        
    context.user_data.clear()
    return ConversationHandler.END

# --- مدیریت کاربران (فقط ادمین) ---
async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ شما دسترسی ادمین ندارید.", reply_markup=main_kb)
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("هیچ کاربری ثبت‌نام نکرده است.", reply_markup=main_kb)
        return
        
    message = "👥 *لیست کاربران ربات*:\n\n"
    for user in users:
        message += f"• نام: {user[1]}\n  ID: `{user[0]}`\n"
        
    await update.message.reply_text(message, reply_markup=main_kb, parse_mode='MarkdownV2')

async def not_implemented(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("این بخش هنوز پیاده‌سازی نشده است!", reply_markup=main_kb)

# ==============================================================================
# بخش ۳: اجرای ربات
# ==============================================================================
def main() -> None:
    if not db_pool:
        logger.critical("ربات به دلیل عدم اتصال به دیتابیس، اجرا نمی‌شود.")
        return
        
    app = ApplicationBuilder().token(TOKEN).build()

    # --- تعریف Conversation Handlers ---
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ افزودن شخص$"), add_person_start),
            MessageHandler(filters.Regex("^🏦 افزودن بانک$"), add_bank_start),
            MessageHandler(filters.Regex("^📂 افزودن حساب جدید$"), add_account_start),
            MessageHandler(filters.Regex("^📋 مشاهده اطلاعات$"), view_info_start),
            MessageHandler(filters.Regex("^🗑 حذف حساب$"), delete_account_start),
        ],
        states={
            ADD_PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), add_person_name)],
            ADD_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), add_bank_name)],
            ADD_ACCOUNT_CHOOSE_PERSON: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), add_account_choose_person)],
            ADD_ACCOUNT_CHOOSE_BANK: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), add_account_choose_bank)],
            ADD_ACCOUNT_CARD_NUMBER: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), add_account_card_number)],
            ADD_ACCOUNT_SHEBA: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), add_account_sheba)],
            ADD_ACCOUNT_IS_SPECIAL: [MessageHandler(filters.Regex("^(✅ بله|❌ خیر)$"), add_account_is_special)],
            VIEW_INFO_CHOOSE_PERSON: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), view_info_choose_person)],
            DELETE_CHOOSE_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.Regex("^🔙 بازگشت$"), delete_account_choose)],
            DELETE_CONFIRM: [MessageHandler(filters.Regex("^(✅ بله|❌ خیر)$"), delete_account_confirm)],
        },
        fallbacks=[MessageHandler(filters.Regex("^🔙 بازگشت$"), back), CommandHandler("cancel", cancel)],
        conversation_timeout=300 # 5 دقیقه
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Regex("^👤 مدیریت کاربران \(ادمین\)$"), manage_users))
    app.add_handler(MessageHandler(filters.Regex("^✏️ ویرایش حساب$"), not_implemented))

    app.run_polling()

if __name__ == "__main__":
    create_tables()
    main()
