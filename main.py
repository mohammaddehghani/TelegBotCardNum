# -*- coding: utf-8 -*-
import os
import logging
import psycopg2
from psycopg2 import sql
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# --- Configuration ---
# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Keyboard Buttons (for consistency and easy changes) ---
# Main Menu
BTN_VIEW = "📋 مشاهده اطلاعات"
BTN_EDIT = "✏️ ویرایش"
BTN_ADMIN = "🛡️ ادمین"
# Admin Menu
BTN_ADMIN_VIEW_USERS = "👥 مشاهده کاربران"
BTN_ADMIN_ADD_USER = "➕ افزودن کاربر"
BTN_ADMIN_DELETE_USER = "➖ حذف کاربر"
# General
BTN_BACK = "🔙 بازگشت"
BTN_CANCEL = "❌ لغو عملیات"
BTN_SKIP = "▶️ رد کردن"
BTN_CONFIRM_DELETE = "🗑️ بله، حذف کن"
# Adding new items
BTN_ADD_PERSON = "➕ افزودن شخص جدید"
BTN_ADD_BANK = "➕ افزودن بانک جدید"
BTN_ADD_ACCOUNT = "➕ افزودن حساب جدید"
# Edit menus
BTN_EDIT_PERSON_NAME = "📝 تغییر نام شخص"
BTN_DELETE_PERSON = "🗑️ حذف این شخص"
BTN_EDIT_ACCOUNT_INFO = "🔄 تغییر اطلاعات حساب"
BTN_DELETE_ACCOUNT = "🗑️ حذف این حساب"
# Account fields
FIELD_CARD_NUMBER = "شماره کارت"
FIELD_IBAN = "شماره شبا"
FIELD_ACCOUNT_NUMBER = "شماره حساب"
FIELD_CARD_IMAGE = "تصویر کارت"


# --- Conversation Handler States ---
(
    # Admin Conversation
    ADMIN_MENU,
    ADMIN_GET_USER_ID_TO_ADD,
    ADMIN_SELECT_USER_TO_DELETE,
    ADMIN_CONFIRM_DELETE_USER,

    # Main Edit Conversation
    SELECT_PERSON,
    PERSON_MENU,
    GET_NEW_PERSON_NAME,
    CONFIRM_DELETE_PERSON,

    SELECT_BANK,
    
    SELECT_ACCOUNT,
    ACCOUNT_MENU,
    CONFIRM_DELETE_ACCOUNT,

    ADD_PERSON_NAME,
    ADD_BANK_NAME,
    
    # Add/Edit Account Sub-Conversation
    ADD_ACCOUNT_NUMBER,
    ADD_CARD_NUMBER,
    ADD_IBAN,
    ADD_CARD_IMAGE,

    EDIT_ACCOUNT_SELECT_FIELD,
    EDIT_ACCOUNT_GET_NEW_VALUE,

) = range(20)


# --- Database Section ---
def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        return None

def create_tables():
    """Creates the necessary tables in the database if they don't exist."""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT NOT NULL,
            added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS persons (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS banks (
            id SERIAL PRIMARY KEY,
            person_id INTEGER REFERENCES persons(id) ON DELETE CASCADE,
            name TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id SERIAL PRIMARY KEY,
            bank_id INTEGER REFERENCES banks(id) ON DELETE CASCADE,
            account_number TEXT,
            card_number TEXT,
            iban TEXT,
            card_image_file_id TEXT
        )
        """,
    )
    conn = None
    try:
        conn = get_db_connection()
        if conn is None: return
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
        conn.commit()
        logger.info("Tables checked/created successfully.")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
    finally:
        if conn is not None:
            conn.close()

# --- Database Helper Functions ---
def execute_query(query, params=None, fetch=None):
    """A generic function to execute database queries."""
    conn = None
    try:
        conn = get_db_connection()
        if conn is None: return None
        with conn.cursor() as cur:
            cur.execute(query, params)
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            else:
                result = None
            conn.commit()
            return result
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB Error: {error}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn is not None:
            conn.close()

# --- User Management Functions ---
def is_user_authorized(user_id):
    if user_id == ADMIN_ID:
        return True
    user = execute_query("SELECT 1 FROM users WHERE user_id = %s", (user_id,), fetch="one")
    return user is not None

def get_authorized_users():
    return execute_query("SELECT user_id, full_name FROM users", fetch="all")

def add_user(user_id, full_name):
    execute_query("INSERT INTO users (user_id, full_name) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING", (user_id, full_name))

def remove_user(user_id):
    execute_query("DELETE FROM users WHERE user_id = %s", (user_id,))

# --- Data Management Functions ---
def get_persons():
    return execute_query("SELECT id, name FROM persons ORDER BY name", fetch="all")

def get_person_name(person_id):
    result = execute_query("SELECT name FROM persons WHERE id = %s", (person_id,), fetch="one")
    return result[0] if result else None
    
def add_person(name):
    execute_query("INSERT INTO persons (name) VALUES (%s)", (name,))

def edit_person_name(person_id, new_name):
    execute_query("UPDATE persons SET name = %s WHERE id = %s", (new_name, person_id))

def delete_person(person_id):
    execute_query("DELETE FROM persons WHERE id = %s", (person_id,))

def get_banks(person_id):
    return execute_query("SELECT id, name FROM banks WHERE person_id = %s ORDER BY name", (person_id,), fetch="all")

def get_bank_name(bank_id):
    result = execute_query("SELECT name FROM banks WHERE id = %s", (bank_id,), fetch="one")
    return result[0] if result else None

def add_bank(person_id, name):
    execute_query("INSERT INTO banks (person_id, name) VALUES (%s, %s)", (person_id, name))

def get_accounts(bank_id):
    return execute_query("SELECT id, account_number, card_number FROM accounts WHERE bank_id = %s ORDER BY id", (bank_id,), fetch="all")
    
def get_account_details(account_id):
    return execute_query("SELECT account_number, card_number, iban, card_image_file_id FROM accounts WHERE id = %s", (account_id,), fetch="one")

def add_account(bank_id, data):
    query = """
    INSERT INTO accounts (bank_id, account_number, card_number, iban, card_image_file_id)
    VALUES (%s, %s, %s, %s, %s)
    """
    params = (
        bank_id,
        data.get('account_number'),
        data.get('card_number'),
        data.get('iban'),
        data.get('card_image_file_id')
    )
    execute_query(query, params)

def delete_account(account_id):
    execute_query("DELETE FROM accounts WHERE id = %s", (account_id,))

def update_account_field(account_id, field, value):
    # This is safer than f-strings to prevent SQL injection
    query = sql.SQL("UPDATE accounts SET {field} = %s WHERE id = %s").format(
        field=sql.Identifier(field)
    )
    execute_query(query, (value, account_id))

# --- Helper Functions ---
def build_keyboard(buttons, n_cols=2, header_buttons=None, footer_buttons=None):
    """Builds a reply keyboard from a list of buttons."""
    menu = [buttons[i : i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return ReplyKeyboardMarkup(menu, resize_keyboard=True)

def format_mono(text):
    """Formats text as monospace for Telegram."""
    if not text: return ""
    return f"`{text}`"

async def unauthorized_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a message to unauthorized users."""
    user_id = update.effective_user.id
    await update.message.reply_text(
        "شما دسترسی لازم برای استفاده از این ربات را ندارید.\n"
        f"لطفاً شناسه کاربری خود را برای ادمین ارسال کنید:\n"
        f"{format_mono(user_id)}"
    )

# --- Main Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the bot and shows the main menu if authorized."""
    user = update.effective_user
    if not is_user_authorized(user.id):
        await unauthorized_user(update, context)
        return ConversationHandler.END

    keyboard = build_keyboard(
        buttons=[BTN_EDIT, BTN_ADMIN if user.id == ADMIN_ID else None],
        n_cols=2 if user.id == ADMIN_ID else 1,
        header_buttons=[BTN_VIEW]
    )
    # Filter out None button if user is not admin
    if user.id != ADMIN_ID:
        keyboard.keyboard = [[btn] for sublist in keyboard.keyboard for btn in sublist if btn is not None]


    await update.message.reply_text(
        "سلام! به ربات مدیریت حساب خوش آمدید. لطفاً یک گزینه را انتخاب کنید:",
        reply_markup=keyboard,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "عملیات لغو شد.", reply_markup=ReplyKeyboardRemove()
    )
    return await start(update, context)


# --- Generic Handlers for View/Edit Flows ---
async def show_persons_list(update: Update, context: ContextTypes.DEFAULT_TYPE, next_state: int):
    """Displays a list of persons for selection."""
    persons = get_persons()
    if not persons:
        await update.message.reply_text(
            "هنوز هیچ شخصی ثبت نشده است. لطفاً از منوی ویرایش یک شخص اضافه کنید.",
            reply_markup=ReplyKeyboardRemove()
        )
        return await start(update, context)

    context.user_data['persons_list'] = {p[1]: p[0] for p in persons}
    buttons = [p[1] for p in persons]
    
    # Add an "add" button if in edit mode
    footer_buttons = []
    if next_state == PERSON_MENU: # This implies edit mode
        footer_buttons.append(BTN_ADD_PERSON)
    footer_buttons.append(BTN_BACK)

    keyboard = build_keyboard(buttons, n_cols=2, footer_buttons=footer_buttons)
    await update.message.reply_text("لطفاً یک شخص را انتخاب کنید:", reply_markup=keyboard)
    return next_state


async def show_banks_list(update: Update, context: ContextTypes.DEFAULT_TYPE, next_state: int):
    """Displays a list of banks for a selected person."""
    person_name = update.message.text
    person_id = context.user_data.get('persons_list', {}).get(person_name)

    if not person_id:
        await update.message.reply_text("شخص نامعتبر است. لطفاً دوباره تلاش کنید.")
        return SELECT_PERSON
        
    context.user_data['selected_person_id'] = person_id
    context.user_data['selected_person_name'] = person_name
    
    banks = get_banks(person_id)
    if not banks and next_state != SELECT_ACCOUNT: # If in view mode and no banks
        await update.message.reply_text(f"هیچ بانکی برای {person_name} ثبت نشده است.")
        return await show_persons_list(update, context, next_state=SELECT_BANK)

    context.user_data['banks_list'] = {b[1]: b[0] for b in banks}
    buttons = [b[1] for b in banks]
    
    footer_buttons = []
    if next_state == SELECT_ACCOUNT: # This implies edit mode
        footer_buttons.append(BTN_ADD_BANK)
    footer_buttons.append(BTN_BACK)

    keyboard = build_keyboard(buttons, n_cols=2, footer_buttons=footer_buttons)
    await update.message.reply_text(f"بانک مورد نظر برای شخص «{person_name}» را انتخاب کنید:", reply_markup=keyboard)
    return next_state


async def show_accounts_list(update: Update, context: ContextTypes.DEFAULT_TYPE, next_state: int):
    """Displays accounts for a selected bank."""
    bank_name = update.message.text
    bank_id = context.user_data.get('banks_list', {}).get(bank_name)
    
    if not bank_id:
        await update.message.reply_text("بانک نامعتبر است. لطفاً دوباره تلاش کنید.")
        return SELECT_BANK

    context.user_data['selected_bank_id'] = bank_id
    context.user_data['selected_bank_name'] = bank_name

    accounts = get_accounts(bank_id)
    
    # In view mode, if no accounts, just say so.
    if not accounts and next_state is None:
        await update.message.reply_text(f"هیچ حسابی برای بانک «{bank_name}» ثبت نشده است.")
        # Go back to bank selection for this person
        person_name = context.user_data['selected_person_name']
        update.message.text = person_name
        return await show_banks_list(update, context, next_state=SELECT_ACCOUNT) # A bit of a hack to go back

    # Prepare for both view and edit
    context.user_data['accounts_list'] = {}
    buttons = []
    for acc in accounts:
        # Create a display name for the button
        acc_id, acc_num, card_num = acc
        label = acc_num or card_num or f"حساب ID: {acc_id}"
        buttons.append(label)
        context.user_data['accounts_list'][label] = acc_id
    
    footer_buttons = []
    # If in edit mode, show the "Add Account" button
    if next_state is not None:
        footer_buttons.append(BTN_ADD_ACCOUNT)
    footer_buttons.append(BTN_BACK)

    keyboard = build_keyboard(buttons, n_cols=1, footer_buttons=footer_buttons)
    person_name = context.user_data.get('selected_person_name', '')
    await update.message.reply_text(
        f"حساب مورد نظر برای «{person_name} - {bank_name}» را انتخاب کنید:", 
        reply_markup=keyboard
    )
    
    return next_state if next_state is not None else ConversationHandler.END

# --- View Flow Handlers ---
async def view_flow_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for the view information flow."""
    return await show_persons_list(update, context, next_state=SELECT_BANK)

async def view_flow_banks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await show_banks_list(update, context, next_state=SELECT_ACCOUNT)

async def view_flow_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await show_accounts_list(update, context, next_state=None)

async def view_flow_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the final account details."""
    account_label = update.message.text
    account_id = context.user_data.get('accounts_list', {}).get(account_label)

    if not account_id:
        await update.message.reply_text("حساب نامعتبر است. لطفاً دوباره تلاش کنید.")
        return SELECT_ACCOUNT

    details = get_account_details(account_id)
    if not details:
        await update.message.reply_text("خطا در دریافت اطلاعات حساب.")
        return ConversationHandler.END

    acc_num, card_num, iban, img_id = details
    
    person_name = context.user_data.get('selected_person_name', 'N/A')
    bank_name = context.user_data.get('selected_bank_name', 'N/A')

    message = (
        f"<b>اطلاعات حساب برای:</b>\n"
        f"👤 شخص: {person_name}\n"
        f"🏦 بانک: {bank_name}\n"
        f"------------------------------\n"
        f"💳 شماره کارت:\n{format_mono(card_num) if card_num else 'ثبت نشده'}\n\n"
        f"#️⃣ شماره حساب:\n{format_mono(acc_num) if acc_num else 'ثبت نشده'}\n\n"
        f"🏛️ شماره شبا (IBAN):\n{format_mono(iban) if iban else 'ثبت نشده'}"
    )

    await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    if img_id:
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img_id, caption="🖼️ تصویر کارت")
        except Exception as e:
            logger.error(f"Could not send photo with file_id {img_id}: {e}")
            await update.message.reply_text("⚠️ تصویر کارت یافت نشد (ممکن است از سرور حذف شده باشد).")

    # Clean up and show main menu again
    context.user_data.clear()
    return await start(update, context)


# --- Edit Flow Handlers ---
async def edit_flow_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for the edit information flow."""
    return await show_persons_list(update, context, next_state=PERSON_MENU)

async def person_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the menu for managing a person or selecting one of their banks."""
    person_name = update.message.text
    # Handle adding a new person
    if person_name == BTN_ADD_PERSON:
        await update.message.reply_text("لطفاً نام شخص جدید را وارد کنید:", reply_markup=build_keyboard([], footer_buttons=[BTN_CANCEL]))
        return ADD_PERSON_NAME

    person_id = context.user_data.get('persons_list', {}).get(person_name)
    if not person_id:
        await update.message.reply_text("شخص نامعتبر. لطفاً از لیست انتخاب کنید.")
        return await show_persons_list(update, context, next_state=PERSON_MENU)

    context.user_data['selected_person_id'] = person_id
    context.user_data['selected_person_name'] = person_name

    banks = get_banks(person_id)
    context.user_data['banks_list'] = {b[1]: b[0] for b in banks}
    bank_buttons = [b[1] for b in banks]

    keyboard = build_keyboard(
        bank_buttons,
        n_cols=2,
        header_buttons=[BTN_EDIT_PERSON_NAME, BTN_DELETE_PERSON],
        footer_buttons=[BTN_ADD_BANK, BTN_BACK]
    )
    await update.message.reply_text(f"مدیریت شخص «{person_name}»:\nمی‌توانید نام او را تغییر دهید، او را حذف کنید، یا یکی از بانک‌هایش را برای ویرایش انتخاب کنید.", reply_markup=keyboard)
    return SELECT_BANK

async def add_person_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a new person to the database."""
    new_name = update.message.text.strip()
    if not new_name or len(new_name) > 50:
        await update.message.reply_text("نام نامعتبر است. لطفاً دوباره تلاش کنید.")
        return ADD_PERSON_NAME
    
    add_person(new_name)
    await update.message.reply_text(f"✅ شخص «{new_name}» با موفقیت اضافه شد.")
    # Go back to the person list
    return await show_persons_list(update, context, next_state=PERSON_MENU)

async def handle_person_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles actions like 'edit name' or 'delete' for a person."""
    action = update.message.text
    person_name = context.user_data['selected_person_name']

    if action == BTN_EDIT_PERSON_NAME:
        await update.message.reply_text(f"لطفاً نام جدید برای «{person_name}» را وارد کنید:", reply_markup=build_keyboard([], footer_buttons=[BTN_CANCEL]))
        return GET_NEW_PERSON_NAME
    
    elif action == BTN_DELETE_PERSON:
        keyboard = build_keyboard([BTN_CONFIRM_DELETE, BTN_BACK], n_cols=2)
        await update.message.reply_text(f"⚠️ آیا از حذف شخص «{person_name}» و تمام اطلاعات بانکی او مطمئن هستید؟ این عمل غیرقابل بازگشت است.", reply_markup=keyboard)
        return CONFIRM_DELETE_PERSON

async def get_new_person_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and saves the new name for a person."""
    new_name = update.message.text.strip()
    person_id = context.user_data['selected_person_id']
    old_name = context.user_data['selected_person_name']

    if not new_name or len(new_name) > 50:
        await update.message.reply_text("نام نامعتبر است. لطفاً دوباره تلاش کنید.")
        return GET_NEW_PERSON_NAME
        
    edit_person_name(person_id, new_name)
    await update.message.reply_text(f"✅ نام شخص از «{old_name}» به «{new_name}» تغییر یافت.")
    
    # Go back to the person list to see the change
    return await show_persons_list(update, context, next_state=PERSON_MENU)

async def confirm_delete_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the selected person after confirmation."""
    person_id = context.user_data['selected_person_id']
    person_name = context.user_data['selected_person_name']
    
    delete_person(person_id)
    await update.message.reply_text(f"🗑️ شخص «{person_name}» با موفقیت حذف شد.")
    
    # Go back to person list
    return await show_persons_list(update, context, next_state=PERSON_MENU)

async def handle_bank_selection_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles selecting a bank in edit mode or adding a new bank."""
    selection = update.message.text
    
    if selection == BTN_ADD_BANK:
        await update.message.reply_text("لطفاً نام بانک جدید را وارد کنید:", reply_markup=build_keyboard([], footer_buttons=[BTN_CANCEL]))
        return ADD_BANK_NAME

    return await show_accounts_list(update, context, next_state=ACCOUNT_MENU)

async def add_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a new bank for the selected person."""
    bank_name = update.message.text.strip()
    person_id = context.user_data['selected_person_id']
    person_name = context.user_data['selected_person_name']

    if not bank_name or len(bank_name) > 50:
        await update.message.reply_text("نام بانک نامعتبر است. لطفاً دوباره تلاش کنید.")
        return ADD_BANK_NAME

    add_bank(person_id, bank_name)
    await update.message.reply_text(f"✅ بانک «{bank_name}» برای «{person_name}» با موفقیت اضافه شد.")
    
    # Refresh the person menu to show the new bank
    update.message.text = person_name
    return await person_menu(update, context)

async def account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the menu for managing a selected account."""
    selection = update.message.text
    
    if selection == BTN_ADD_ACCOUNT:
        context.user_data['new_account_data'] = {}
        await update.message.reply_text(
            "شروع فرآیند افزودن حساب جدید...\n"
            "لطفاً شماره حساب را وارد کنید:",
            reply_markup=build_keyboard([BTN_SKIP], footer_buttons=[BTN_CANCEL])
        )
        return ADD_ACCOUNT_NUMBER

    account_label = selection
    account_id = context.user_data.get('accounts_list', {}).get(account_label)
    if not account_id:
        await update.message.reply_text("حساب نامعتبر. لطفاً از لیست انتخاب کنید.")
        return SELECT_ACCOUNT

    context.user_data['selected_account_id'] = account_id
    context.user_data['selected_account_label'] = account_label
    
    keyboard = build_keyboard([BTN_EDIT_ACCOUNT_INFO, BTN_DELETE_ACCOUNT], n_cols=2, footer_buttons=[BTN_BACK])
    await update.message.reply_text(f"مدیریت حساب «{account_label}». لطفاً یک گزینه را انتخاب کنید:", reply_markup=keyboard)
    return ACCOUNT_MENU

async def handle_account_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles 'edit info' or 'delete' for an account."""
    action = update.message.text
    account_label = context.user_data['selected_account_label']
    
    if action == BTN_EDIT_ACCOUNT_INFO:
        buttons = [FIELD_CARD_NUMBER, FIELD_IBAN, FIELD_ACCOUNT_NUMBER, FIELD_CARD_IMAGE]
        keyboard = build_keyboard(buttons, n_cols=2, footer_buttons=[BTN_BACK])
        await update.message.reply_text("کدام فیلد را می‌خواهید تغییر دهید؟", reply_markup=keyboard)
        return EDIT_ACCOUNT_SELECT_FIELD
    
    elif action == BTN_DELETE_ACCOUNT:
        keyboard = build_keyboard([BTN_CONFIRM_DELETE, BTN_BACK], n_cols=2)
        await update.message.reply_text(f"⚠️ آیا از حذف حساب «{account_label}» مطمئن هستید؟", reply_markup=keyboard)
        return CONFIRM_DELETE_ACCOUNT

async def confirm_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the selected account after confirmation."""
    account_id = context.user_data['selected_account_id']
    account_label = context.user_data['selected_account_label']
    
    delete_account(account_id)
    await update.message.reply_text(f"🗑️ حساب «{account_label}» با موفقیت حذف شد.")
    
    # Go back to the bank's account list
    bank_name = context.user_data['selected_bank_name']
    update.message.text = bank_name
    return await show_accounts_list(update, context, next_state=ACCOUNT_MENU)


# --- Add/Edit Account Sub-Conversation ---
async def add_account_get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != BTN_SKIP:
        context.user_data['new_account_data']['account_number'] = update.message.text
    await update.message.reply_text("لطفاً شماره کارت ۱۶ رقمی را وارد کنید:", reply_markup=build_keyboard([BTN_SKIP], footer_buttons=[BTN_CANCEL]))
    return ADD_CARD_NUMBER
    
async def add_account_get_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != BTN_SKIP:
        context.user_data['new_account_data']['card_number'] = update.message.text
    await update.message.reply_text("لطفاً شماره شبا (IBAN) را بدون IR وارد کنید:", reply_markup=build_keyboard([BTN_SKIP], footer_buttons=[BTN_CANCEL]))
    return ADD_IBAN

async def add_account_get_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != BTN_SKIP:
        # Prepend IR if not present
        iban = update.message.text.upper().replace(" ", "")
        if not iban.startswith("IR"):
            iban = "IR" + iban
        context.user_data['new_account_data']['iban'] = iban
    await update.message.reply_text("در صورت تمایل، تصویر کارت را ارسال کنید:", reply_markup=build_keyboard([BTN_SKIP], footer_buttons=[BTN_CANCEL]))
    return ADD_CARD_IMAGE

async def add_account_get_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    if file_id:
        context.user_data['new_account_data']['card_image_file_id'] = file_id
    
    # Save the new account
    bank_id = context.user_data['selected_bank_id']
    add_account(bank_id, context.user_data['new_account_data'])
    
    await update.message.reply_text("✅ حساب جدید با موفقیت اضافه شد.")
    
    # Go back to the account list for that bank
    context.user_data.pop('new_account_data', None)
    bank_name = context.user_data['selected_bank_name']
    update.message.text = bank_name
    return await show_accounts_list(update, context, next_state=ACCOUNT_MENU)

async def edit_account_select_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for the new value of the selected field."""
    field_map = {
        FIELD_CARD_NUMBER: 'card_number',
        FIELD_IBAN: 'iban',
        FIELD_ACCOUNT_NUMBER: 'account_number',
        FIELD_CARD_IMAGE: 'card_image_file_id',
    }
    field_fa = update.message.text
    field_en = field_map.get(field_fa)
    
    if not field_en:
        await update.message.reply_text("فیلد نامعتبر است. لطفاً از دکمه‌ها استفاده کنید.")
        return EDIT_ACCOUNT_SELECT_FIELD
    
    context.user_data['field_to_edit'] = field_en
    context.user_data['field_to_edit_fa'] = field_fa

    prompt = f"لطفاً مقدار جدید برای «{field_fa}» را وارد کنید."
    if field_en == 'card_image_file_id':
        prompt = f"لطفاً تصویر جدید برای «{field_fa}» را ارسال کنید."

    # Add a "remove" button for optional fields
    await update.message.reply_text(
        prompt, 
        reply_markup=build_keyboard(["🗑️ حذف این فیلد"], footer_buttons=[BTN_CANCEL])
    )
    return EDIT_ACCOUNT_GET_NEW_VALUE

async def edit_account_get_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Updates the selected field with the new value."""
    account_id = context.user_data['selected_account_id']
    field_en = context.user_data['field_to_edit']
    field_fa = context.user_data['field_to_edit_fa']
    new_value = None

    if update.message.text == "🗑️ حذف این فیلد":
        new_value = None
    elif field_en == 'card_image_file_id':
        if update.message.photo:
            new_value = update.message.photo[-1].file_id
        else:
            await update.message.reply_text("لطفاً یک تصویر ارسال کنید.")
            return EDIT_ACCOUNT_GET_NEW_VALUE
    else:
        new_value = update.message.text.strip()
    
    update_account_field(account_id, field_en, new_value)
    
    await update.message.reply_text(f"✅ فیلد «{field_fa}» با موفقیت به‌روزرسانی شد.")
    
    # Go back to the bank's account list to see changes
    bank_name = context.user_data['selected_bank_name']
    update.message.text = bank_name
    return await show_accounts_list(update, context, next_state=ACCOUNT_MENU)


# --- Admin Conversation Handlers ---
async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the admin menu."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این بخش مخصوص ادمین است.")
        return ConversationHandler.END

    keyboard = build_keyboard(
        [BTN_ADMIN_VIEW_USERS, BTN_ADMIN_ADD_USER, BTN_ADMIN_DELETE_USER],
        n_cols=1,
        footer_buttons=[BTN_BACK]
    )
    await update.message.reply_text("🛡️ پنل ادمین. لطفاً یک گزینه را انتخاب کنید:", reply_markup=keyboard)
    return ADMIN_MENU

async def admin_show_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays all authorized users."""
    users = get_authorized_users()
    if not users:
        await update.message.reply_text("هیچ کاربر مجازی ثبت نشده است.")
        return ADMIN_MENU
    
    message = "👥 لیست کاربران مجاز:\n"
    for user_id, full_name in users:
        message += f"\n- نام: {full_name}\n  شناسه: {format_mono(user_id)}\n"
        
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    return ADMIN_MENU

async def admin_prompt_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for the user ID to add."""
    await update.message.reply_text("لطفاً شناسه کاربری (User ID) عددی کاربر مورد نظر را وارد کنید:", reply_markup=build_keyboard([], footer_buttons=[BTN_CANCEL]))
    return ADMIN_GET_USER_ID_TO_ADD

async def admin_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a new user by their ID."""
    try:
        user_id_to_add = int(update.message.text)
    except (ValueError, TypeError):
        await update.message.reply_text("شناسه کاربری باید یک عدد باشد. لطفاً دوباره تلاش کنید.")
        return ADMIN_GET_USER_ID_TO_ADD

    # We need to get the user's name. This is tricky without them interacting.
    # We will fetch it when they next use /start
    add_user(user_id_to_add, f"User_{user_id_to_add}") # Placeholder name
    await update.message.reply_text(f"✅ کاربر با شناسه {format_mono(user_id_to_add)} به لیست مجاز اضافه شد.", parse_mode=ParseMode.HTML)

    # Notify the user they got access
    try:
        await context.bot.send_message(
            chat_id=user_id_to_add,
            text="🎉 دسترسی شما به ربات فعال شد! برای شروع /start را بزنید."
        )
    except Exception as e:
        logger.error(f"Could not notify user {user_id_to_add}: {e}")
        await update.message.reply_text("⚠️ نتوانستم به کاربر اطلاع دهم (ممکن است ربات را بلاک کرده باشد).")
        
    return await admin_entry(update, context) # Go back to admin menu

async def admin_select_user_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of users to choose from for deletion."""
    users = get_authorized_users()
    if not users:
        await update.message.reply_text("هیچ کاربری برای حذف وجود ندارد.")
        return ADMIN_MENU

    context.user_data['users_for_deletion'] = {f"{name} ({uid})": uid for uid, name in users}
    buttons = list(context.user_data['users_for_deletion'].keys())
    
    keyboard = build_keyboard(buttons, n_cols=1, footer_buttons=[BTN_BACK])
    await update.message.reply_text("لطفاً کاربری که می‌خواهید حذف کنید را انتخاب نمایید:", reply_markup=keyboard)
    return ADMIN_SELECT_USER_TO_DELETE

async def admin_confirm_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for confirmation before deleting a user."""
    selection = update.message.text
    user_id_to_delete = context.user_data.get('users_for_deletion', {}).get(selection)
    
    if not user_id_to_delete:
        await update.message.reply_text("انتخاب نامعتبر است. لطفاً از لیست استفاده کنید.")
        return ADMIN_SELECT_USER_TO_DELETE
        
    context.user_data['user_id_to_delete'] = user_id_to_delete
    keyboard = build_keyboard([BTN_CONFIRM_DELETE, BTN_BACK], n_cols=2)
    await update.message.reply_text(f"⚠️ آیا از حذف دسترسی کاربر «{selection}» مطمئن هستید؟", reply_markup=keyboard)
    return ADMIN_CONFIRM_DELETE_USER

async def admin_delete_user_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Performs the user deletion."""
    user_id_to_delete = context.user_data['user_id_to_delete']
    remove_user(user_id_to_delete)
    await update.message.reply_text(f"🗑️ کاربر با شناسه {format_mono(user_id_to_delete)} با موفقیت حذف شد.", parse_mode=ParseMode.HTML)
    context.user_data.clear()
    return await admin_entry(update, context)


def main() -> None:
    """Run the bot."""
    # First, ensure tables exist
    create_tables()

    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for the admin panel
    admin_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADMIN}$"), admin_entry)],
        states={
            ADMIN_MENU: [
                MessageHandler(filters.Regex(f"^{BTN_ADMIN_VIEW_USERS}$"), admin_show_users),
                MessageHandler(filters.Regex(f"^{BTN_ADMIN_ADD_USER}$"), admin_prompt_user_id),
                MessageHandler(filters.Regex(f"^{BTN_ADMIN_DELETE_USER}$"), admin_select_user_to_delete),
                MessageHandler(filters.Regex(f"^{BTN_BACK}$"), start),
            ],
            ADMIN_GET_USER_ID_TO_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user)],
            ADMIN_SELECT_USER_TO_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_confirm_delete_user)],
            ADMIN_CONFIRM_DELETE_USER: [
                MessageHandler(filters.Regex(f"^{BTN_CONFIRM_DELETE}$"), admin_delete_user_confirmed),
                MessageHandler(filters.Regex(f"^{BTN_BACK}$"), admin_select_user_to_delete)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    # A simple conversation for the view flow to manage state
    view_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_VIEW}$"), view_flow_entry)],
        states={
            SELECT_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, view_flow_banks)],
            SELECT_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, view_flow_accounts)],
            ConversationHandler.TIMEOUT: [], # No state, just need to catch the final selection
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, view_flow_details),
            CommandHandler("start", start),
        ],
        conversation_timeout=600
    )
    
    # The main conversation for adding/editing data
    edit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_EDIT}$"), edit_flow_entry)],
        states={
            PERSON_MENU: [
                MessageHandler(filters.Regex(f"^{BTN_ADD_PERSON}$") | (filters.TEXT & ~filters.COMMAND & ~filters.Regex(f"^{BTN_BACK}$")), person_menu),
            ],
            ADD_PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_person_name)],
            GET_NEW_PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_person_name)],
            CONFIRM_DELETE_PERSON: [
                MessageHandler(filters.Regex(f"^{BTN_CONFIRM_DELETE}$"), confirm_delete_person),
                MessageHandler(filters.Regex(f"^{BTN_BACK}$"), lambda u,c: person_menu(u, c)) # Hack to go back
            ],
            SELECT_BANK: [
                MessageHandler(filters.Regex(f"^{BTN_EDIT_PERSON_NAME}$") | filters.Regex(f"^{BTN_DELETE_PERSON}$"), handle_person_action),
                MessageHandler(filters.Regex(f"^{BTN_ADD_BANK}$") | (filters.TEXT & ~filters.COMMAND & ~filters.Regex(f"^{BTN_BACK}$")), handle_bank_selection_edit),
            ],
            ADD_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bank_name)],
            ACCOUNT_MENU: [
                MessageHandler(filters.Regex(f"^{BTN_EDIT_ACCOUNT_INFO}$") | filters.Regex(f"^{BTN_DELETE_ACCOUNT}$"), handle_account_action),
                MessageHandler(filters.Regex(f"^{BTN_ADD_ACCOUNT}$") | (filters.TEXT & ~filters.COMMAND & ~filters.Regex(f"^{BTN_BACK}$")), account_menu)
            ],
            CONFIRM_DELETE_ACCOUNT: [
                MessageHandler(filters.Regex(f"^{BTN_CONFIRM_DELETE}$"), confirm_delete_account),
            ],
            # Add/Edit account sub-flow
            ADD_ACCOUNT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_get_number)],
            ADD_CARD_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_get_card)],
            ADD_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_get_iban)],
            ADD_CARD_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Regex(f"^{BTN_SKIP}$"), add_account_get_image)
            ],
            EDIT_ACCOUNT_SELECT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_account_select_field)],
            EDIT_ACCOUNT_GET_NEW_VALUE: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, edit_account_get_new_value)],

            # Back buttons
            SELECT_ACCOUNT: [ # from account_menu back
                MessageHandler(filters.Regex(f"^{BTN_BACK}$"), lambda u,c: person_menu(u.message.text, c)) # Needs context fix
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    
    # A master handler to route to the correct conversation
    # We must also handle back buttons here to change conversations
    main_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            0: [admin_conv, view_conv, edit_conv]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # Using a dispatcher group to avoid conflicts, but a simpler setup might work too.
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(admin_conv)
    application.add_handler(view_conv)
    application.add_handler(edit_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start)) # Default handler

    # Run the bot until the user presses Ctrl-C
    application.run_polling()


if __name__ == "__main__":
    # Validate environment variables before starting
    if not all([BOT_TOKEN, DATABASE_URL, ADMIN_ID]):
        logger.error("FATAL: One or more environment variables (BOT_TOKEN, DATABASE_URL, ADMIN_ID) are missing.")
    else:
        main()
