import logging
import os
import psycopg2
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))

# --- Database Connection ---
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("PGHOST"),
            port=os.getenv("PGPORT"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            dbname=os.getenv("PGDATABASE"),
        )
        return conn
    except psycopg2.OperationalError as e:
        logging.error(f"Could not connect to database: {e}")
        return None

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- States for ConversationHandlers ---
GET_PERSON_NAME = 1
SELECT_PERSON_FOR_BANK, GET_BANK_NAME = range(2, 4)
SELECT_PERSON_FOR_ACCOUNT, SELECT_BANK_FOR_ACCOUNT, GET_ACCOUNT_NICKNAME, GET_ACCOUNT_NUM, GET_CARD_NUM, GET_IBAN, GET_CARD_IMAGE, ASK_IF_SPECIAL = range(4, 12)
GET_USER_ID_TO_GRANT, GET_USER_ID_TO_REVOKE = range(12, 14)

# ==============================================================================
# DATABASE HELPER FUNCTIONS (Unchanged, but vital)
# ==============================================================================
def init_db():
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, telegram_id BIGINT UNIQUE NOT NULL, is_admin BOOLEAN DEFAULT FALSE, access_granted BOOLEAN DEFAULT FALSE, full_name VARCHAR(255));""")
        cur.execute("""CREATE TABLE IF NOT EXISTS persons (id SERIAL PRIMARY KEY, name VARCHAR(255) UNIQUE NOT NULL);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS banks (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, person_id INTEGER REFERENCES persons(id) ON DELETE CASCADE);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, bank_id INTEGER REFERENCES banks(id) ON DELETE CASCADE, nickname VARCHAR(255) NOT NULL, account_number VARCHAR(50), card_number VARCHAR(20), iban VARCHAR(34), card_image_url TEXT, is_special BOOLEAN DEFAULT FALSE);""")
    conn.commit()
    conn.close()
    logger.info("Database initialized/checked successfully.")

def get_user(telegram_id):
    conn = get_db_connection();
    if not conn: return None
    with conn.cursor() as cur: cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,)); user = cur.fetchone()
    conn.close(); return user

def add_user(telegram_id, full_name):
    conn = get_db_connection();
    if not conn: return
    with conn.cursor() as cur:
        is_admin = (telegram_id == ADMIN_USER_ID); access_granted = is_admin
        cur.execute("INSERT INTO users (telegram_id, full_name, is_admin, access_granted) VALUES (%s, %s, %s, %s) ON CONFLICT (telegram_id) DO NOTHING", (telegram_id, full_name, is_admin, access_granted))
    conn.commit(); conn.close()

def grant_user_access(target_telegram_id):
    conn = get_db_connection();
    if not conn: return False
    with conn.cursor() as cur: cur.execute("UPDATE users SET access_granted = TRUE WHERE telegram_id = %s", (target_telegram_id,)); updated_rows = cur.rowcount
    conn.commit(); conn.close(); return updated_rows > 0

def revoke_user_access(target_telegram_id):
    conn = get_db_connection();
    if not conn: return False
    with conn.cursor() as cur:
        if int(target_telegram_id) == ADMIN_USER_ID: return False
        cur.execute("UPDATE users SET access_granted = FALSE WHERE telegram_id = %s", (target_telegram_id,)); updated_rows = cur.rowcount
    conn.commit(); conn.close(); return updated_rows > 0

def get_all_users():
    conn = get_db_connection();
    if not conn: return []
    with conn.cursor() as cur: cur.execute("SELECT telegram_id, full_name, access_granted FROM users ORDER BY id"); users = cur.fetchall()
    conn.close(); return users

# ==============================================================================
# MAIN MENU & CORE HANDLERS (REWORKED)
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    # FIX: Always fetch the latest user status from DB
    db_user = get_user(user.id)
    if not db_user:
        add_user(user.id, user.full_name)
        username = f"@{user.username}" if user.username else "ندارد"
        admin_message = (f"کاربر جدیدی به ربات پیوست:\n\n👤 **نام:** {user.full_name}\n🆔 **یوزرنیم:** {username}\n🔢 **شناسه عددی:** `{user.id}`\n\nبرای تایید دسترسی، از منوی مدیریت کاربران استفاده کنید.")
        await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_message, parse_mode='Markdown')
        await update.message.reply_text("سلام! درخواست دسترسی شما برای ادمین ارسال شد. لطفاً منتظر تایید بمانید.")
        return
        
    # FIX: Re-fetch user after potential addition to ensure we have the correct access status
    db_user = get_user(user.id)
    if db_user and db_user[3]: # db_user[3] is access_granted
        await show_main_menu(update, context)
    else:
        await update.message.reply_text("دسترسی شما هنوز توسط ادمین تایید نشده است.")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("مشاهده اطلاعات 🗂️", callback_data="main_view")],
        [InlineKeyboardButton("افزودن اطلاعات ➕", callback_data="main_add")],
        [InlineKeyboardButton("ویرایش اطلاعات ✏️", callback_data="main_edit")],
        [InlineKeyboardButton("مدیریت کاربرها 👥", callback_data="main_users")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "به ربات کارت‌نام خوش آمدید! لطفاً یک گزینه را انتخاب کنید:"
    
    # UI/UX FIX: If it's a callback (e.g., from a 'back' button), edit the message. Otherwise, send a new one.
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def edit_info_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]]
    await query.edit_message_text("بخش ویرایش اطلاعات در دست ساخت است.", reply_markup=InlineKeyboardMarkup(keyboard))

async def grant_access_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID: return
    try:
        target_id = int(context.args[0])
        if grant_user_access(target_id):
            await update.message.reply_text(f"✅ دسترسی برای کاربر `{target_id}` فعال شد.")
            await context.bot.send_message(chat_id=target_id, text="🎉 تبریک! دسترسی شما به ربات فعال شد. برای شروع /start را بزنید.")
        else: await update.message.reply_text(f"کاربری با شناسه {target_id} یافت نشد.")
    except (IndexError, ValueError): await update.message.reply_text("استفاده صحیح: /grant <user_id>")

# ==============================================================================
# NAVIGATION CALLBACK HANDLERS (NEW)
# ==============================================================================
async def navigate_to_add_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("👤 افزودن شخص جدید", callback_data="add_person_start")],
        [InlineKeyboardButton("🏦 افزودن بانک جدید", callback_data="add_bank_start")],
        [InlineKeyboardButton("💳 افزودن حساب/کارت جدید", callback_data="add_account_start")],
        [InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]
    ]
    await query.edit_message_text("چه اطلاعاتی را می‌خواهید اضافه کنید?", reply_markup=InlineKeyboardMarkup(keyboard))

async def navigate_to_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_USER_ID:
        await query.answer("شما ادمین نیستید.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton("اعطای دسترسی ➕", callback_data="manage_grant_start")],
        [InlineKeyboardButton("حذف دسترسی ➖", callback_data="manage_revoke_start")],
        [InlineKeyboardButton("لیست کاربران 📋", callback_data="manage_list_users")],
        [InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]
    ]
    await query.edit_message_text("به بخش مدیریت کاربران خوش آمدید.", reply_markup=InlineKeyboardMarkup(keyboard))

# ==============================================================================
# VIEW INFORMATION FLOW (With back buttons)
# ==============================================================================
async def show_persons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer()
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM persons ORDER BY name"); persons = cur.fetchall()
    conn.close()
    if not persons:
        keyboard = [[InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]]
        await query.edit_message_text("هنوز شخصی اضافه نشده است.", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"person_{p[0]}")] for p in persons]
    keyboard.append([InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")])
    await query.edit_message_text("لطفاً یک شخص را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_person_details(update: Update, context: ContextTypes.DEFAULT_TYPE, person_id: str) -> None:
    query = update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return
    keyboard = []
    
    with conn.cursor() as cur: cur.execute("SELECT acc.id, acc.nickname FROM accounts acc JOIN banks b ON acc.bank_id = b.id WHERE b.person_id = %s AND acc.is_special = TRUE ORDER BY acc.nickname", (person_id,)); special_accounts = cur.fetchall()
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM banks WHERE person_id = %s ORDER BY name", (person_id,)); banks = cur.fetchall()
    conn.close()

    message_text = ""
    if special_accounts:
        message_text += "🌟 **حساب‌های خاص**\n"; keyboard.extend([[InlineKeyboardButton(f"💳 {acc[1]}", callback_data=f"account_{acc[0]}")] for acc in special_accounts])
        if banks: keyboard.append([InlineKeyboardButton("──────────", callback_data="noop")])

    if banks: message_text += "🏦 **بانک‌ها**"; keyboard.extend([[InlineKeyboardButton(b[1], callback_data=f"bank_{b[0]}")] for b in banks])
    if not special_accounts and not banks: message_text = "هنوز هیچ حساب یا بانکی برای این شخص ثبت نشده است."

    keyboard.append([InlineKeyboardButton("◀️ برگشت به اشخاص", callback_data="main_view")])
    await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE, bank_id: str) -> None:
    query = update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT id, nickname FROM accounts WHERE bank_id = %s ORDER BY nickname", (bank_id,)); accounts = cur.fetchall()
        cur.execute("SELECT person_id FROM banks WHERE id = %s", (bank_id,)); person_id = cur.fetchone()[0]
    conn.close()
    keyboard = [[InlineKeyboardButton(f"{acc[1]}", callback_data=f"account_{acc[0]}")] for acc in accounts]
    keyboard.append([InlineKeyboardButton("◀️ برگشت", callback_data=f"person_{person_id}")])
    text = "حساب مورد نظر را انتخاب کنید:" if accounts else "هنوز حسابی برای این بانک ثبت نشده است."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_account_details(update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: str) -> None:
    query = update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return
    with conn.cursor() as cur: cur.execute("SELECT nickname, account_number, card_number, iban, card_image_url, bank_id FROM accounts WHERE id = %s", (account_id,)); account = cur.fetchone()
    conn.close()
    if not account: await query.edit_message_text("خطا: حساب یافت نشد."); return
    nickname, account_number, card_number, iban, card_image_url, bank_id = account
    details_text = f"**{nickname}**\n\n"
    if account_number: details_text += f"شماره حساب:\n`{account_number}`\n\n"
    if card_number: details_text += f"شماره کارت:\n`{card_number}`\n\n"
    if iban: details_text += f"شماره شبا (IBAN):\n`{iban}`\n"
    keyboard = [[InlineKeyboardButton("◀️ برگشت به لیست", callback_data=f"bank_{bank_id}")]]
    await query.edit_message_text(details_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    if card_image_url: await context.bot.send_photo(chat_id=update.effective_chat.id, photo=card_image_url)


# ==============================================================================
# USER MANAGEMENT FLOW (With back buttons)
# ==============================================================================
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer()
    all_users = get_all_users()
    if not all_users:
        await query.edit_message_text("هنوز کاربری در سیستم ثبت نشده است.")
        return
    user_list_text = "لیست تمام کاربران:\n\n"
    for user in all_users:
        telegram_id, full_name, access_granted = user
        status_icon = "✅" if access_granted else "❌"
        user_list_text += f"{status_icon} **{full_name}**\n       شناسه: `{telegram_id}`\n"
    keyboard = [[InlineKeyboardButton("◀️ برگشت", callback_data="main_users")]]
    await query.edit_message_text(user_list_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

# All other conversation flows (add person, add bank, add account, grant/revoke access) remain largely the same,
# but we need to ensure they handle `callback_query` correctly for starting messages.
# The following sections are mostly unchanged, except for small tweaks.

# ... [UNCHANGED ADD PERSON & ADD BANK CONVERSATIONS] ...
async def add_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    await query.message.reply_text("لطفاً نام کامل شخص جدید را وارد کنید. برای لغو /cancel را بزنید.")
    return GET_PERSON_NAME
async def get_person_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    person_name = update.message.text; conn = get_db_connection();
    if not conn: await update.message.reply_text("خطا در اتصال به دیتابیس."); return ConversationHandler.END
    try:
        with conn.cursor() as cur: cur.execute("INSERT INTO persons (name) VALUES (%s)", (person_name,)); conn.commit()
        await update.message.reply_text(f"✅ شخص «{person_name}» با موفقیت اضافه شد.")
    except psycopg2.IntegrityError: await update.message.reply_text(f"❌ خطایی رخ داد. احتمالا شخصی با نام «{person_name}» از قبل وجود دارد.")
    finally: conn.close()
    return ConversationHandler.END
async def add_bank_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer(); conn = get_db_connection()
    if not conn: await query.message.reply_text("خطا در اتصال به دیتابیس."); return ConversationHandler.END
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM persons ORDER BY name"); persons = cur.fetchall()
    conn.close()
    if not persons: await query.message.reply_text("ابتدا باید یک شخص اضافه کنید."); return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"select_person_{p[0]}")] for p in persons]
    await query.message.reply_text("این بانک برای کدام شخص است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_PERSON_FOR_BANK
async def select_person_for_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); context.user_data['person_id'] = query.data.split("_")[2]
    await query.message.reply_text("نام بانک را وارد کنید. برای لغو /cancel را بزنید."); return GET_BANK_NAME
async def get_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bank_name = update.message.text; person_id = context.user_data.get('person_id'); conn = get_db_connection()
    if not conn: await update.message.reply_text("خطا در اتصال به دیتابیس."); return ConversationHandler.END
    try:
        with conn.cursor() as cur: cur.execute("INSERT INTO banks (name, person_id) VALUES (%s, %s)", (bank_name, person_id)); conn.commit()
        await update.message.reply_text(f"✅ بانک «{bank_name}» با موفقیت اضافه شد.")
    except Exception as e: logger.error(f"Error adding bank: {e}"); await update.message.reply_text("❌ خطایی در ثبت بانک رخ داد.")
    finally: conn.close(); context.user_data.clear()
    return ConversationHandler.END
# --- [UNCHANGED GRANT/REVOKE USER CONVERSATIONS] ---
async def grant_access_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    await query.message.reply_text("شناسه عددی کاربر برای اعطای دسترسی را وارد کنید."); return GET_USER_ID_TO_GRANT
async def get_user_id_to_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        target_id = int(update.message.text)
        if grant_user_access(target_id):
            await update.message.reply_text(f"✅ دسترسی برای کاربر `{target_id}` فعال شد.")
            await context.bot.send_message(chat_id=target_id, text="🎉 دسترسی شما فعال شد. /start را بزنید.")
        else: await update.message.reply_text(f"کاربری با شناسه `{target_id}` یافت نشد.")
    except ValueError: await update.message.reply_text("شناسه نامعتبر است.")
    except BadRequest: await update.message.reply_text("خطا: کاربر باید ابتدا ربات را استارت زده باشد.")
    return ConversationHandler.END
async def revoke_access_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    await query.message.reply_text("شناسه عددی کاربر برای لغو دسترسی را وارد کنید."); return GET_USER_ID_TO_REVOKE
async def get_user_id_to_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        target_id = int(update.message.text)
        if target_id == ADMIN_USER_ID: await update.message.reply_text("❌ نمی‌توانید دسترسی ادمین را لغو کنید."); return ConversationHandler.END
        if revoke_user_access(target_id):
            await update.message.reply_text(f"✅ دسترسی کاربر `{target_id}` لغو شد.")
            await context.bot.send_message(chat_id=target_id, text="⚠️ دسترسی شما توسط ادمین لغو شد.")
        else: await update.message.reply_text(f"کاربری با شناسه `{target_id}` یافت نشد.")
    except ValueError: await update.message.reply_text("شناسه نامعتبر است.")
    return ConversationHandler.END

# --- Add Account Conversation (with minor adjustments for callback query start) ---
async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM persons"); persons = cur.fetchall()
    conn.close()
    if not persons: await query.message.reply_text("ابتدا باید یک شخص اضافه کنید."); return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"select_person_{p[0]}")] for p in persons]
    await query.message.reply_text("این حساب برای کدام شخص است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_PERSON_FOR_ACCOUNT

# The rest of the add_account flow is largely the same
# ... [UNCHANGED select_person_for_account, select_bank_for_account, etc.] ...
async def select_person_for_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); person_id = query.data.split("_")[2]; context.user_data['person_id'] = person_id; conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM banks WHERE person_id = %s", (person_id,)); banks = cur.fetchall()
    conn.close()
    if not banks: await query.message.edit_text("برای این شخص بانکی ثبت نشده. لطفا ابتدا یک بانک اضافه کنید."); return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(b[1], callback_data=f"select_bank_{b[0]}")] for b in banks]
    await query.message.edit_text("حساب مربوط به کدام بانک است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_BANK_FOR_ACCOUNT
async def select_bank_for_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); context.user_data['bank_id'] = query.data.split("_")[2]; context.user_data['account_data'] = {}
    await query.message.edit_text("یک نام برای این حساب انتخاب کنید (مثال: حساب اصلی، حقوق، ...).")
    return GET_ACCOUNT_NICKNAME
async def get_account_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['nickname'] = update.message.text
    await update.message.reply_text("شماره حساب را وارد کنید. (برای رد شدن: /skip)"); return GET_ACCOUNT_NUM
async def skip_account_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['account_number'] = None
    await update.message.reply_text("شماره حساب ثبت نشد. حالا شماره کارت را وارد کنید. (برای رد شدن: /skip)"); return GET_CARD_NUM
async def get_account_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['account_number'] = update.message.text
    await update.message.reply_text("شماره کارت ۱۶ رقمی را وارد کنید. (برای رد شدن: /skip)"); return GET_CARD_NUM
async def skip_card_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['card_number'] = None
    await update.message.reply_text("شماره کارت ثبت نشد. حالا شماره شبا را وارد کنید. (برای رد شدن: /skip)"); return GET_IBAN
async def get_card_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['card_number'] = update.message.text
    await update.message.reply_text("شماره شبا (IBAN) را بدون IR وارد کنید. (برای رد شدن: /skip)"); return GET_IBAN
async def skip_iban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['iban'] = None
    await update.message.reply_text("شماره شبا ثبت نشد. حالا عکس کارت را ارسال کنید. (برای رد شدن: /skip)"); return GET_CARD_IMAGE
async def get_iban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['iban'] = f"IR{update.message.text}"
    await update.message.reply_text("در صورت تمایل عکس کارت را ارسال کنید. (برای رد شدن: /skip)"); return GET_CARD_IMAGE
async def skip_card_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['account_data']['card_image_url'] = None
    await update.message.reply_text("عکسی ثبت نشد.")
    return await ask_if_special(update, context)
async def get_card_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['account_data']['card_image_url'] = photo_file.file_id
    return await ask_if_special(update, context)
async def ask_if_special(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("✅ بله", callback_data="make_special_yes"), InlineKeyboardButton(" خیر", callback_data="make_special_no")]]
    await update.message.reply_text("آیا این یک «حساب خاص» است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_IF_SPECIAL
async def handle_special_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    is_special = (query.data == "make_special_yes")
    context.user_data['account_data']['is_special'] = is_special
    special_text = "به عنوان حساب خاص علامت‌گذاری شد." if is_special else "به عنوان حساب عادی ثبت شد."
    await query.edit_message_text(f"اطلاعات ثبت شد. {special_text}")
    await save_account(update, context)
    return ConversationHandler.END

async def save_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_source = update.callback_query.message if update.callback_query else update.message
    bank_id = context.user_data.get('bank_id')
    data = context.user_data.get('account_data', {})
    
    # DEBUG: Log the data we are about to save
    logger.info(f"Attempting to save account. Bank ID: {bank_id}. Data: {data}")

    if not bank_id or 'nickname' not in data:
        logger.error("Missing critical data for saving account.")
        await message_source.reply_text("❌ خطای داخلی: اطلاعات ضروری برای ذخیره حساب یافت نشد.")
        return

    conn = get_db_connection()
    if not conn: await message_source.reply_text("خطا در اتصال به دیتابیس."); return
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO accounts (bank_id, nickname, account_number, card_number, iban, card_image_url, is_special) VALUES (%s, %s, %s, %s, %s, %s, %s)""", (bank_id, data.get('nickname'), data.get('account_number'), data.get('card_number'), data.get('iban'), data.get('card_image_url'), data.get('is_special', False)))
            conn.commit()
        await message_source.reply_text(f"✅ حساب «{data.get('nickname')}» با موفقیت ثبت شد.")
    except Exception as e:
        # FIX: Added detailed exception logging
        logger.error(f"Error saving account to DB: {e}", exc_info=True)
        await message_source.reply_text("❌ خطایی در ثبت حساب رخ داد. لطفاً لاگ‌ها را بررسی کنید.")
    finally:
        conn.close()
        context.user_data.clear()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("عملیات لغو شد."); return ConversationHandler.END

async def handle_generic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); data = query.data
    if data == "noop": return
    elif data.startswith("person_"): await show_person_details(update, context, data.split("_")[1])
    elif data.startswith("bank_"): await show_accounts(update, context, data.split("_")[1])
    elif data.startswith("account_"): await show_account_details(update, context, data.split("_")[1])

def main() -> None:
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handlers (unchanged logic, but now initiated from callbacks)
    add_person_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_person_start$")], states={GET_PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_person_name)]}, fallbacks=[CommandHandler("cancel", cancel)])
    add_bank_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_bank_start, pattern="^add_bank_start$")], states={SELECT_PERSON_FOR_BANK: [CallbackQueryHandler(select_person_for_bank, pattern="^select_person_")], GET_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bank_name)]}, fallbacks=[CommandHandler("cancel", cancel)])
    add_account_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_account_start, pattern="^add_account_start$")], states={SELECT_PERSON_FOR_ACCOUNT: [CallbackQueryHandler(select_person_for_account, pattern="^select_person_")], SELECT_BANK_FOR_ACCOUNT: [CallbackQueryHandler(select_bank_for_account, pattern="^select_bank_")], GET_ACCOUNT_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account_nickname)], GET_ACCOUNT_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account_num), CommandHandler("skip", skip_account_num)], GET_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_card_num), CommandHandler("skip", skip_card_num)], GET_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_iban), CommandHandler("skip", skip_iban)], GET_CARD_IMAGE: [MessageHandler(filters.PHOTO, get_card_image), CommandHandler("skip", skip_card_image)], ASK_IF_SPECIAL: [CallbackQueryHandler(handle_special_choice, pattern="^make_special_")]}, fallbacks=[CommandHandler("cancel", cancel)])
    grant_access_conv = ConversationHandler(entry_points=[CallbackQueryHandler(grant_access_start, pattern="^manage_grant_start$")], states={GET_USER_ID_TO_GRANT: [MessageHandler(filters.Regex(r'^\d+$'), get_user_id_to_grant)]}, fallbacks=[CommandHandler("cancel", cancel)])
    revoke_access_conv = ConversationHandler(entry_points=[CallbackQueryHandler(revoke_access_start, pattern="^manage_revoke_start$")], states={GET_USER_ID_TO_REVOKE: [MessageHandler(filters.Regex(r'^\d+$'), get_user_id_to_revoke)]}, fallbacks=[CommandHandler("cancel", cancel)])

    application.add_handler(add_person_conv)
    application.add_handler(add_bank_conv)
    application.add_handler(add_account_conv)
    application.add_handler(grant_access_conv)
    application.add_handler(revoke_access_conv)

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("grant", grant_access_command))

    # Main Menu Navigation Handlers (NEW)
    application.add_handler(CallbackQueryHandler(show_persons, pattern="^main_view$"))
    application.add_handler(CallbackQueryHandler(navigate_to_add_menu, pattern="^main_add$"))
    application.add_handler(CallbackQueryHandler(edit_info_placeholder, pattern="^main_edit$"))
    application.add_handler(CallbackQueryHandler(navigate_to_user_menu, pattern="^main_users$"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_main_menu$"))
    
    # User management specific callback
    application.add_handler(CallbackQueryHandler(list_users, pattern="^manage_list_users$"))
    
    # Generic callback handler for viewing data must be after specific ones
    application.add_handler(CallbackQueryHandler(handle_generic_callback))

    application.run_polling()

if __name__ == "__main__":
    main()
