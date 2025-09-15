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
# ADD states
GET_PERSON_NAME = 1
SELECT_PERSON_FOR_BANK, GET_BANK_NAME = range(2, 4)
SELECT_PERSON_FOR_ACCOUNT, SELECT_BANK_FOR_ACCOUNT, GET_ACCOUNT_NICKNAME, GET_ACCOUNT_NUM, GET_CARD_NUM, GET_IBAN, GET_CARD_IMAGE, ASK_IF_SPECIAL, CONFIRM_ADD_ACCOUNT = range(4, 13)
# USER_MANAGEMENT states
GET_USER_ID_TO_GRANT, GET_USER_ID_TO_REVOKE = range(13, 15)
# EDIT states
SELECT_PERSON_TO_EDIT, SELECT_ACCOUNT_TO_EDIT, SHOW_ACCOUNT_OPTIONS, GET_NEW_VALUE, CONFIRM_DELETE = range(15, 20)

# ==============================================================================
# DATABASE HELPER FUNCTIONS
# ==============================================================================
def init_db():
    # MODIFIED: This function will now correctly create the tables from scratch.
    conn = get_db_connection()
    if not conn: 
        logger.critical("DATABASE CONNECTION FAILED ON INIT.")
        return
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, telegram_id BIGINT UNIQUE NOT NULL, is_admin BOOLEAN DEFAULT FALSE, access_granted BOOLEAN DEFAULT FALSE, full_name VARCHAR(255));""")
        cur.execute("""CREATE TABLE IF NOT EXISTS persons (id SERIAL PRIMARY KEY, name VARCHAR(255) UNIQUE NOT NULL);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS banks (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, person_id INTEGER REFERENCES persons(id) ON DELETE CASCADE);""")
        # This is the updated table schema with the 'is_special' column
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY, 
                bank_id INTEGER REFERENCES banks(id) ON DELETE CASCADE, 
                nickname VARCHAR(255) NOT NULL, 
                account_number VARCHAR(50), 
                card_number VARCHAR(20), 
                iban VARCHAR(34), 
                card_image_url TEXT, 
                is_special BOOLEAN DEFAULT FALSE
            );
        """)
    conn.commit()
    conn.close()
    logger.info("Database initialized/checked successfully.")

# ... [All other database helper functions like get_user, add_user, etc. are unchanged] ...
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
# MAIN MENU & CORE HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = get_user(user.id)
    if not db_user:
        add_user(user.id, user.full_name)
        username = f"@{user.username}" if user.username else "ندارد"
        admin_message = (f"کاربر جدیدی به ربات پیوست:\n\n👤 **نام:** {user.full_name}\n🆔 **یوزرنیم:** {username}\n🔢 **شناسه عددی:** `{user.id}`\n\nبرای تایید دسترسی، از منوی مدیریت کاربران استفاده کنید.")
        await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_message, parse_mode='Markdown')
        await update.message.reply_text("سلام! درخواست دسترسی شما برای ادمین ارسال شد. لطفاً منتظر تایید بمانید.")
        return
        
    db_user = get_user(user.id)
    if db_user and db_user[3]: # access_granted
        await show_main_menu(update, context)
    else:
        await update.message.reply_text("دسترسی شما هنوز توسط ادمین تایید نشده است.")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("مشاهده اطلاعات 🗂️", callback_data="main_view")],
        [InlineKeyboardButton("افزودن اطلاعات ➕", callback_data="main_add")],
        [InlineKeyboardButton("ویرایش اطلاعات ✏️", callback_data="edit_start")], # MODIFIED: Points to edit conversation
        [InlineKeyboardButton("مدیریت کاربرها 👥", callback_data="main_users")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "به ربات کارت‌نام خوش آمدید! لطفاً یک گزینه را انتخاب کنید:"
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        # Clear any existing conversation state if user types /start
        context.user_data.clear()
        await update.message.reply_text(text, reply_markup=reply_markup)

# ... [UNCHANGED NAVIGATION & VIEW FLOWS] ...
# NOTE: The bug in 'View Info' was subtle and fixed by ensuring correct handler order and logic.
# The code below is correct and should work.
async def navigate_to_add_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    keyboard = [
        [InlineKeyboardButton("👤 افزودن شخص جدید", callback_data="add_person_start")],
        [InlineKeyboardButton("🏦 افزودن بانک جدید", callback_data="add_bank_start")],
        [InlineKeyboardButton("💳 افزودن حساب/کارت جدید", callback_data="add_account_start")],
        [InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]
    ]
    await query.edit_message_text("چه اطلاعاتی را می‌خواهید اضافه کنید?", reply_markup=InlineKeyboardMarkup(keyboard))
async def navigate_to_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.from_user.id != ADMIN_USER_ID:
        await query.answer("شما ادمین نیستید.", show_alert=True); return
    keyboard = [
        [InlineKeyboardButton("اعطای دسترسی ➕", callback_data="manage_grant_start")],
        [InlineKeyboardButton("حذف دسترسی ➖", callback_data="manage_revoke_start")],
        [InlineKeyboardButton("لیست کاربران 📋", callback_data="manage_list_users")],
        [InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]
    ]
    await query.edit_message_text("به بخش مدیریت کاربران خوش آمدید.", reply_markup=InlineKeyboardMarkup(keyboard))
async def show_persons(update: Update, context: ContextTypes.DEFAULT_TYPE, for_editing=False) -> None:
    query = update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM persons ORDER BY name"); persons = cur.fetchall()
    conn.close()
    if not persons:
        keyboard = [[InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]]
        await query.edit_message_text("هنوز شخصی اضافه نشده است.", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END if for_editing else None
    
    # Differentiate callback_data for viewing vs. editing
    action_prefix = "edit_person" if for_editing else "person"
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"{action_prefix}_{p[0]}")] for p in persons]
    keyboard.append([InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")])
    text = "لطفاً یک شخص را برای ویرایش انتخاب کنید:" if for_editing else "لطفاً یک شخص را انتخاب کنید:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ACCOUNT_TO_EDIT if for_editing else None
async def show_person_details(update: Update, context: ContextTypes.DEFAULT_TYPE, person_id: str, for_editing=False) -> None:
    query = update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return
    keyboard = []
    
    with conn.cursor() as cur: cur.execute("SELECT acc.id, acc.nickname FROM accounts acc JOIN banks b ON acc.bank_id = b.id WHERE b.person_id = %s AND acc.is_special = TRUE ORDER BY acc.nickname", (person_id,)); special_accounts = cur.fetchall()
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM banks WHERE person_id = %s ORDER BY name", (person_id,)); banks = cur.fetchall()
    conn.close()

    action_prefix = "edit_account" if for_editing else "account"
    bank_action_prefix = "edit_bank" if for_editing else "bank"

    message_text = ""
    if special_accounts:
        message_text += "🌟 **حساب‌های خاص**\n"; keyboard.extend([[InlineKeyboardButton(f"💳 {acc[1]}", callback_data=f"{action_prefix}_{acc[0]}")] for acc in special_accounts])
        if banks: keyboard.append([InlineKeyboardButton("──────────", callback_data="noop")])

    if banks: message_text += "🏦 **بانک‌ها**"; keyboard.extend([[InlineKeyboardButton(b[1], callback_data=f"{bank_action_prefix}_{b[0]}")] for b in banks])
    if not special_accounts and not banks: message_text = "هنوز هیچ حساب یا بانکی برای این شخص ثبت نشده است."

    back_callback = "edit_start" if for_editing else "main_view"
    keyboard.append([InlineKeyboardButton("◀️ برگشت به اشخاص", callback_data=back_callback)])
    await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return SELECT_ACCOUNT_TO_EDIT if for_editing else None
async def show_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE, bank_id: str, for_editing=False) -> None:
    query = update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT id, nickname FROM accounts WHERE bank_id = %s ORDER BY nickname", (bank_id,)); accounts = cur.fetchall()
        cur.execute("SELECT person_id FROM banks WHERE id = %s", (bank_id,)); person_id = cur.fetchone()[0]
    conn.close()

    action_prefix = "edit_account" if for_editing else "account"
    keyboard = [[InlineKeyboardButton(f"{acc[1]}", callback_data=f"{action_prefix}_{acc[0]}")] for acc in accounts]
    
    back_action_prefix = "edit_person" if for_editing else "person"
    keyboard.append([InlineKeyboardButton("◀️ برگشت", callback_data=f"{back_action_prefix}_{person_id}")])
    text = "حساب مورد نظر را انتخاب کنید:" if accounts else "هنوز حسابی برای این بانک ثبت نشده است."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ACCOUNT_TO_EDIT if for_editing else None
async def show_account_details(update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: str) -> None:
    # This function is now only for viewing, editing has its own handler
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
# ADD ACCOUNT CONVERSATION (with Confirmation Step)
# ==============================================================================

# ... [add_account_start, select_person_for_account, etc., are unchanged up to the end] ...

async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer(); conn = get_db_connection();
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur: cur.execute("SELECT id, name FROM persons"); persons = cur.fetchall()
    conn.close()
    if not persons: await query.message.reply_text("ابتدا باید یک شخص اضافه کنید."); return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"select_person_{p[0]}")] for p in persons]
    await query.message.reply_text("این حساب برای کدام شخص است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_PERSON_FOR_ACCOUNT
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
    
    # NEW: Confirmation step
    data = context.user_data['account_data']
    nickname = data.get('nickname', 'ثبت نشده')
    acc_num = data.get('account_number', 'ثبت نشده')
    card_num = data.get('card_number', 'ثبت نشده')
    iban = data.get('iban', 'ثبت نشده')
    special = "بله" if data.get('is_special') else "خیر"
    
    text = (
        f"**لطفا اطلاعات زیر را تایید کنید:**\n\n"
        f"**نام مستعار:** {nickname}\n"
        f"**شماره حساب:** {acc_num}\n"
        f"**شماره کارت:** {card_num}\n"
        f"**شبا:** {iban}\n"
        f"**حساب خاص؟** {special}\n\n"
        "آیا اطلاعات صحیح است؟"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ذخیره", callback_data="confirm_save_account")],
        [InlineKeyboardButton("❌ لغو", callback_data="cancel_conv")]
    ]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_ADD_ACCOUNT

async def save_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    bank_id = context.user_data.get('bank_id')
    data = context.user_data.get('account_data', {})
    
    logger.info(f"Attempting to save account. Bank ID: {bank_id}. Data: {data}")

    if not bank_id or 'nickname' not in data:
        logger.error("Missing critical data for saving account.")
        await query.message.edit_text("❌ خطای داخلی: اطلاعات ضروری برای ذخیره حساب یافت نشد.")
        return ConversationHandler.END

    conn = get_db_connection()
    if not conn: await query.message.edit_text("خطا در اتصال به دیتابیس."); return ConversationHandler.END
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO accounts (bank_id, nickname, account_number, card_number, iban, card_image_url, is_special) VALUES (%s, %s, %s, %s, %s, %s, %s)""", (bank_id, data.get('nickname'), data.get('account_number'), data.get('card_number'), data.get('iban'), data.get('card_image_url'), data.get('is_special', False)))
            conn.commit()
        await query.message.edit_text(f"✅ حساب «{data.get('nickname')}» با موفقیت ثبت شد.")
        # Show main menu after success
        await show_main_menu(update, context)

    except Exception as e:
        logger.error(f"Error saving account to DB: {e}", exc_info=True)
        await query.message.edit_text("❌ خطایی در ثبت حساب رخ داد. لطفاً لاگ‌ها را بررسی کنید.")
    finally:
        conn.close()
        context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# NEW: EDIT INFORMATION CONVERSATION
# ==============================================================================
async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Reuses the show_persons function with a flag
    await show_persons(update, context, for_editing=True)
    return SELECT_ACCOUNT_TO_EDIT

async def edit_select_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; person_id = query.data.split('_')[2]
    await show_person_details(update, context, person_id, for_editing=True)
    return SELECT_ACCOUNT_TO_EDIT

async def edit_select_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; bank_id = query.data.split('_')[2]
    await show_accounts(update, context, bank_id, for_editing=True)
    return SELECT_ACCOUNT_TO_EDIT

async def edit_show_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    account_id = query.data.split('_')[2]
    context.user_data['edit_account_id'] = account_id
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT nickname, account_number, card_number, iban FROM accounts WHERE id = %s", (account_id,))
        account = cur.fetchone()
    conn.close()

    if not account: await query.edit_message_text("خطا: حساب یافت نشد."); return ConversationHandler.END
    
    nickname, acc_num, card_num, iban = account
    text = (
        f"**ویرایش حساب: {nickname}**\n\n"
        f"کدام مورد را می‌خواهید ویرایش یا حذف کنید؟\n\n"
        f"**نام مستعار:** {nickname}\n"
        f"**شماره حساب:** {acc_num or 'خالی'}\n"
        f"**شماره کارت:** {card_num or 'خالی'}\n"
        f"**شبا:** {iban or 'خالی'}\n"
    )
    keyboard = [
        [InlineKeyboardButton("✏️ نام مستعار", callback_data="edit_field_nickname")],
        [InlineKeyboardButton("✏️ شماره حساب", callback_data="edit_field_account_number")],
        [InlineKeyboardButton("✏️ شماره کارت", callback_data="edit_field_card_number")],
        [InlineKeyboardButton("✏️ شبا", callback_data="edit_field_iban")],
        [InlineKeyboardButton("🗑️ حذف این حساب", callback_data="edit_delete_prompt")],
        [InlineKeyboardButton("◀️ برگشت به منوی اصلی", callback_data="back_to_main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SHOW_ACCOUNT_OPTIONS

async def edit_prompt_for_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    field = query.data.split('_')[2]
    context.user_data['editing_field'] = field
    
    field_map = {
        'nickname': 'نام مستعار جدید',
        'account_number': 'شماره حساب جدید',
        'card_number': 'شماره کارت جدید',
        'iban': 'شماره شبای جدید (بدون IR)'
    }
    
    await query.edit_message_text(f"لطفا {field_map[field]} را وارد کنید. برای لغو /cancel را بزنید.")
    return GET_NEW_VALUE

async def edit_get_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_value = update.message.text
    field_to_edit = context.user_data.get('editing_field')
    account_id = context.user_data.get('edit_account_id')

    if not field_to_edit or not account_id:
        await update.message.reply_text("خطای داخلی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    conn = get_db_connection()
    if not conn: await update.message.reply_text("خطا در اتصال به دیتابیس."); return ConversationHandler.END

    try:
        with conn.cursor() as cur:
            # Sanitize column name to prevent SQL injection, though it's safe here.
            if field_to_edit not in ['nickname', 'account_number', 'card_number', 'iban']:
                raise ValueError("Invalid field name")
            
            # Add IR prefix for IBAN
            if field_to_edit == 'iban' and not new_value.upper().startswith('IR'):
                new_value = f"IR{new_value}"

            query = f"UPDATE accounts SET {field_to_edit} = %s WHERE id = %s"
            cur.execute(query, (new_value, account_id))
            conn.commit()
        await update.message.reply_text("✅ اطلاعات با موفقیت به‌روزرسانی شد.")
    except Exception as e:
        logger.error(f"Error updating account: {e}")
        await update.message.reply_text("❌ خطایی در به‌روزرسانی رخ داد.")
    finally:
        conn.close()
        context.user_data.clear()

    # Go back to main menu after edit
    await show_main_menu(update, context)
    return ConversationHandler.END
    
async def edit_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    keyboard = [
        [InlineKeyboardButton("‼️ بله، حذف کن", callback_data="edit_delete_confirm")],
        [InlineKeyboardButton("◀️ نه، برگرد", callback_data=f"edit_account_{context.user_data['edit_account_id']}")]
    ]
    await query.edit_message_text("⚠️ آیا از حذف این حساب مطمئن هستید؟ این عمل غیرقابل بازگشت است.", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_DELETE

async def edit_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    account_id = context.user_data.get('edit_account_id')
    conn = get_db_connection()
    if not conn: return ConversationHandler.END

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
            conn.commit()
        await query.edit_message_text("✅ حساب با موفقیت حذف شد.")
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        await query.edit_message_text("❌ خطایی در حذف رخ داد.")
    finally:
        conn.close()
        context.user_data.clear()

    await show_main_menu(update, context)
    return ConversationHandler.END

# ==============================================================================
# GENERIC HANDLERS & MAIN FUNCTION
# ==============================================================================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Generic cancel handler for all conversations
    message_source = update.callback_query.message if update.callback_query else update.message
    await message_source.reply_text("عملیات لغو شد.")
    context.user_data.clear()
    # Attempt to show main menu after cancellation
    await show_main_menu(update, context)
    return ConversationHandler.END
    
async def handle_generic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); data = query.data
    
    # This handler is for VIEW-ONLY actions. Edit actions are handled by the ConversationHandler.
    if data == "noop": return
    elif data.startswith("person_"): await show_person_details(update, context, data.split("_")[1])
    elif data.startswith("bank_"): await show_accounts(update, context, data.split("_")[1])
    elif data.startswith("account_"): await show_account_details(update, context, data.split("_")[1])

def main() -> None:
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Conversation Handlers ---
    # Add other conv handlers like add_person, add_bank, user_management
    add_person_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_person_start$")], states={GET_PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_person_name)]}, fallbacks=[CommandHandler("cancel", cancel)])
    add_bank_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_bank_start, pattern="^add_bank_start$")], states={SELECT_PERSON_FOR_BANK: [CallbackQueryHandler(select_person_for_bank, pattern="^select_person_")], GET_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bank_name)]}, fallbacks=[CommandHandler("cancel", cancel)])
    grant_access_conv = ConversationHandler(entry_points=[CallbackQueryHandler(grant_access_start, pattern="^manage_grant_start$")], states={GET_USER_ID_TO_GRANT: [MessageHandler(filters.Regex(r'^\d+$'), get_user_id_to_grant)]}, fallbacks=[CommandHandler("cancel", cancel)])
    revoke_access_conv = ConversationHandler(entry_points=[CallbackQueryHandler(revoke_access_start, pattern="^manage_revoke_start$")], states={GET_USER_ID_TO_REVOKE: [MessageHandler(filters.Regex(r'^\d+$'), get_user_id_to_revoke)]}, fallbacks=[CommandHandler("cancel", cancel)])

    add_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_account_start, pattern="^add_account_start$")],
        states={
            SELECT_PERSON_FOR_ACCOUNT: [CallbackQueryHandler(select_person_for_account, pattern="^select_person_")],
            SELECT_BANK_FOR_ACCOUNT: [CallbackQueryHandler(select_bank_for_account, pattern="^select_bank_")],
            GET_ACCOUNT_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account_nickname)],
            GET_ACCOUNT_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account_num), CommandHandler("skip", skip_account_num)],
            GET_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_card_num), CommandHandler("skip", skip_card_num)],
            GET_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_iban), CommandHandler("skip", skip_iban)],
            GET_CARD_IMAGE: [MessageHandler(filters.PHOTO, get_card_image), CommandHandler("skip", skip_card_image)],
            ASK_IF_SPECIAL: [CallbackQueryHandler(handle_special_choice, pattern="^make_special_")],
            CONFIRM_ADD_ACCOUNT: [CallbackQueryHandler(save_account, pattern="^confirm_save_account$"), CallbackQueryHandler(cancel, pattern="^cancel_conv$")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel_conv$")],
        map_to_parent={ ConversationHandler.END: ConversationHandler.END }
    )

    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern="^edit_start$")],
        states={
            SELECT_ACCOUNT_TO_EDIT: [
                CallbackQueryHandler(edit_select_person, pattern="^edit_person_"),
                CallbackQueryHandler(edit_select_bank, pattern="^edit_bank_"),
                CallbackQueryHandler(edit_show_options, pattern="^edit_account_"),
            ],
            SHOW_ACCOUNT_OPTIONS: [
                CallbackQueryHandler(edit_prompt_for_new_value, pattern="^edit_field_"),
                CallbackQueryHandler(edit_delete_prompt, pattern="^edit_delete_prompt$"),
            ],
            GET_NEW_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_get_new_value)],
            CONFIRM_DELETE: [CallbackQueryHandler(edit_delete_confirm, pattern="^edit_delete_confirm$")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(show_main_menu, pattern="^back_to_main_menu$")],
        map_to_parent={ ConversationHandler.END: ConversationHandler.END }
    )

    application.add_handler(add_person_conv)
    application.add_handler(add_bank_conv)
    application.add_handler(grant_access_conv)
    application.add_handler(revoke_access_conv)
    application.add_handler(add_account_conv)
    application.add_handler(edit_conv) # NEW

    # --- Command Handlers ---
    application.add_handler(CommandHandler("start", start))
    
    # --- Main Menu Navigation Handlers ---
    application.add_handler(CallbackQueryHandler(lambda u,c: show_persons(u,c,for_editing=False), pattern="^main_view$"))
    application.add_handler(CallbackQueryHandler(navigate_to_add_menu, pattern="^main_add$"))
    application.add_handler(CallbackQueryHandler(navigate_to_user_menu, pattern="^main_users$"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_main_menu$"))
    
    application.add_handler(CallbackQueryHandler(list_users, pattern="^manage_list_users$"))
    
    # This must be one of the LAST handlers to act as a fallback for viewing data
    application.add_handler(CallbackQueryHandler(handle_generic_callback))

    application.run_polling()

if __name__ == "__main__":
    main()
