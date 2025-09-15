import logging
import os
import psycopg2
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

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
# Add Person States
GET_PERSON_NAME = 1
# Add Bank States
SELECT_PERSON_FOR_BANK, GET_BANK_NAME = range(2, 4)
# Add Account States
SELECT_PERSON_FOR_ACCOUNT, SELECT_BANK_FOR_ACCOUNT, GET_ACCOUNT_NUM, GET_CARD_NUM, GET_IBAN, GET_CARD_IMAGE = range(4, 10)

# ==============================================================================
# DATABASE HELPER FUNCTIONS
# ==============================================================================
def init_db():
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                access_granted BOOLEAN DEFAULT FALSE,
                full_name VARCHAR(255)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS persons (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS banks (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                person_id INTEGER REFERENCES persons(id) ON DELETE CASCADE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                bank_id INTEGER REFERENCES banks(id) ON DELETE CASCADE,
                account_number VARCHAR(50),
                card_number VARCHAR(20),
                iban VARCHAR(34),
                card_image_url TEXT
            );
        """)
    conn.commit()
    conn.close()
    logger.info("Database initialized/checked successfully.")

def get_user(telegram_id):
    conn = get_db_connection()
    if not conn: return None
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cur.fetchone()
    conn.close()
    return user

def add_user(telegram_id, full_name):
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        is_admin = (telegram_id == ADMIN_USER_ID)
        access_granted = is_admin
        cur.execute(
            "INSERT INTO users (telegram_id, full_name, is_admin, access_granted) VALUES (%s, %s, %s, %s) ON CONFLICT (telegram_id) DO NOTHING",
            (telegram_id, full_name, is_admin, access_granted)
        )
    conn.commit()
    conn.close()

def grant_user_access(target_telegram_id):
    conn = get_db_connection()
    if not conn: return False
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET access_granted = TRUE WHERE telegram_id = %s", (target_telegram_id,))
        updated_rows = cur.rowcount
    conn.commit()
    conn.close()
    return updated_rows > 0

# ==============================================================================
# CORE BOT LOGIC & HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    user = update.effective_user
    db_user = get_user(user.id)

    if not db_user:
        add_user(user.id, user.full_name)
        db_user = get_user(user.id)
        if user.id != ADMIN_USER_ID:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"کاربر جدیدی با نام {user.full_name} و شناسه `{user.id}` درخواست دسترسی دارد.\nبرای تایید، از دستور `/grant {user.id}` استفاده کنید.",
            )
            await update.message.reply_text("سلام! درخواست دسترسی شما برای ادمین ارسال شد. لطفاً منتظر تایید بمانید.")
            return

    if db_user and db_user[3]:  # access_granted is at index 3
        keyboard = [
            [InlineKeyboardButton("🗂️ مشاهده اطلاعات", callback_data="view_info_start")],
            [InlineKeyboardButton("👤 افزودن شخص جدید", callback_data="add_person_start")],
            [InlineKeyboardButton("🏦 افزودن بانک جدید", callback_data="add_bank_start")],
            [InlineKeyboardButton("💳 افزودن حساب/کارت جدید", callback_data="add_account_start")],
            [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("به ربات کارت‌نام خوش آمدید! لطفاً یک گزینه را انتخاب کنید:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("دسترسی شما هنوز توسط ادمین تایید نشده است. لطفاً صبور باشید.")

async def grant_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to grant access to a user."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    try:
        target_id = int(context.args[0])
        if grant_user_access(target_id):
            await update.message.reply_text(f"✅ دسترسی برای کاربر با شناسه {target_id} فعال شد.")
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 تبریک! دسترسی شما به ربات فعال شد. برای شروع /start را بزنید."
            )
        else:
            await update.message.reply_text(f"کاربری با شناسه {target_id} یافت نشد.")
    except (IndexError, ValueError):
        await update.message.reply_text("استفاده صحیح: /grant <user_id>")

# --- Generic cancel command for conversations ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "عملیات لغو شد.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# ==============================================================================
# VIEW INFORMATION FLOW (Existing Logic)
# ==============================================================================
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Router for all callback queries."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "view_info_start":
        await show_persons(update, context)
    elif data.startswith("person_"):
        person_id = data.split("_")[1]
        await show_banks(update, context, person_id)
    elif data.startswith("bank_"):
        bank_id = data.split("_")[1]
        await show_accounts(update, context, bank_id)
    elif data.startswith("account_"):
        account_id = data.split("_")[1]
        await show_account_details(update, context, account_id)
    elif data.startswith("back_to_persons"):
        await show_persons(update, context)
    elif data.startswith("back_to_banks_"):
        person_id = data.split("_")[3]
        await show_banks(update, context, person_id)
    elif data.startswith("back_to_accounts_"):
        bank_id = data.split("_")[3]
        await show_accounts(update, context, bank_id)
    elif data == "help":
        await query.message.reply_text("این ربات برای مدیریت اطلاعات بانکی شما طراحی شده است.")


async def show_persons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM persons ORDER BY name")
        persons = cur.fetchall()
    conn.close()

    keyboard = []
    if persons:
        for person in persons:
            keyboard.append([InlineKeyboardButton(person[1], callback_data=f"person_{person[0]}")])
    else:
        await update.callback_query.message.edit_text("هنوز شخصی اضافه نشده است.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.edit_text("لطفاً یک شخص را انتخاب کنید:", reply_markup=reply_markup)


async def show_banks(update: Update, context: ContextTypes.DEFAULT_TYPE, person_id: str) -> None:
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM banks WHERE person_id = %s ORDER BY name", (person_id,))
        banks = cur.fetchall()
    conn.close()

    keyboard = []
    if banks:
        for bank in banks:
            keyboard.append([InlineKeyboardButton(bank[1], callback_data=f"bank_{bank[0]}")])
    
    keyboard.append([InlineKeyboardButton("◀️ برگشت به اشخاص", callback_data="back_to_persons")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not banks:
        await update.callback_query.message.edit_text(
            "هنوز بانکی برای این شخص ثبت نشده است.",
            reply_markup=reply_markup
        )
        return
        
    await update.callback_query.message.edit_text("بانک مورد نظر را انتخاب کنید:", reply_markup=reply_markup)


async def show_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE, bank_id: str) -> None:
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT id, card_number, account_number FROM accounts WHERE bank_id = %s", (bank_id,))
        accounts = cur.fetchall()
        cur.execute("SELECT person_id FROM banks WHERE id = %s", (bank_id,))
        person_id = cur.fetchone()[0]
    conn.close()

    keyboard = []
    if accounts:
        for acc in accounts:
            label = acc[1] if acc[1] else acc[2] # Show card number or account number
            keyboard.append([InlineKeyboardButton(f"حساب/کارت: {label}", callback_data=f"account_{acc[0]}")])
    
    keyboard.append([InlineKeyboardButton("◀️ برگشت به بانک‌ها", callback_data=f"back_to_banks_{person_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not accounts:
        await update.callback_query.message.edit_text(
            "هنوز حسابی برای این بانک ثبت نشده است.",
            reply_markup=reply_markup
        )
        return

    await update.callback_query.message.edit_text("حساب مورد نظر را انتخاب کنید:", reply_markup=reply_markup)


async def show_account_details(update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: str) -> None:
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT account_number, card_number, iban, card_image_url, bank_id FROM accounts WHERE id = %s", (account_id,))
        account = cur.fetchone()
    conn.close()
    
    if not account:
        await update.callback_query.message.edit_text("خطا: حساب یافت نشد.")
        return
        
    account_number, card_number, iban, card_image_url, bank_id = account
    
    details_text = "جزئیات حساب:\n\n"
    if account_number:
        details_text += f"شماره حساب:\n`{account_number}`\n\n"
    if card_number:
        details_text += f"شماره کارت:\n`{card_number}`\n\n"
    if iban:
        details_text += f"شماره شبا (IBAN):\n`{iban}`\n"
        
    keyboard = [[InlineKeyboardButton("◀️ برگشت به حساب‌ها", callback_data=f"back_to_accounts_{bank_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.message.edit_text(details_text, parse_mode='Markdown', reply_markup=reply_markup)

    if card_image_url:
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=card_image_url)


# ==============================================================================
# ADD PERSON CONVERSATION
# ==============================================================================
async def add_person_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a person."""
    await update.callback_query.message.reply_text("لطفاً نام کامل شخص جدید را وارد کنید. برای لغو /cancel را بزنید.")
    return GET_PERSON_NAME

async def get_person_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the person's name."""
    person_name = update.message.text
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("خطا در اتصال به دیتابیس.")
        return ConversationHandler.END
        
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO persons (name) VALUES (%s)", (person_name,))
        conn.commit()
        await update.message.reply_text(f"✅ شخص «{person_name}» با موفقیت اضافه شد.")
    except psycopg2.IntegrityError:
        await update.message.reply_text(f"❌ خطایی رخ داد. احتمالا شخصی با نام «{person_name}» از قبل وجود دارد.")
    finally:
        conn.close()
        
    return ConversationHandler.END


# ==============================================================================
# ADD BANK CONVERSATION
# ==============================================================================
async def add_bank_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a bank by showing persons list."""
    conn = get_db_connection()
    if not conn: 
        await update.callback_query.message.reply_text("خطا در اتصال به دیتابیس.")
        return ConversationHandler.END

    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM persons ORDER BY name")
        persons = cur.fetchall()
    conn.close()

    if not persons:
        await update.callback_query.message.reply_text("ابتدا باید یک شخص اضافه کنید. از منوی اصلی اقدام کنید.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"select_person_{p[0]}")] for p in persons]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text(
        "این بانک برای کدام شخص است؟",
        reply_markup=reply_markup
    )
    return SELECT_PERSON_FOR_BANK

async def select_person_for_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the selected person and asks for the bank name."""
    query = update.callback_query
    await query.answer()
    person_id = query.data.split("_")[2]
    context.user_data['person_id'] = person_id
    
    await query.message.reply_text("نام بانک را وارد کنید (مثال: ملی، پاسارگاد). برای لغو /cancel را بزنید.")
    return GET_BANK_NAME

async def get_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new bank to the database."""
    bank_name = update.message.text
    person_id = context.user_data.get('person_id')
    
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("خطا در اتصال به دیتابیس.")
        return ConversationHandler.END

    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO banks (name, person_id) VALUES (%s, %s)", (bank_name, person_id))
        conn.commit()
        await update.message.reply_text(f"✅ بانک «{bank_name}» با موفقیت اضافه شد.")
    except Exception as e:
        logger.error(f"Error adding bank: {e}")
        await update.message.reply_text("❌ خطایی در ثبت بانک رخ داد.")
    finally:
        conn.close()
        context.user_data.clear()

    return ConversationHandler.END

# ==============================================================================
# ADD ACCOUNT CONVERSATION
# ==============================================================================
async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts add account conversation. Asks to select a person."""
    await update.callback_query.answer()
    # This logic is similar to add_bank_start, so we can reuse parts
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM persons")
        persons = cur.fetchall()
    conn.close()

    if not persons:
        await update.callback_query.message.reply_text("ابتدا باید یک شخص اضافه کنید.")
        return ConversationHandler.END
        
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f"select_person_{p[0]}")] for p in persons]
    await update.callback_query.message.reply_text("این حساب برای کدام شخص است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_PERSON_FOR_ACCOUNT

async def select_person_for_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks to select a bank after a person is chosen."""
    query = update.callback_query
    await query.answer()
    person_id = query.data.split("_")[2]
    context.user_data['person_id'] = person_id
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM banks WHERE person_id = %s", (person_id,))
        banks = cur.fetchall()
    conn.close()

    if not banks:
        await query.message.reply_text("برای این شخص بانکی ثبت نشده. لطفا ابتدا یک بانک اضافه کنید.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(b[1], callback_data=f"select_bank_{b[0]}")] for b in banks]
    await query.message.reply_text("حساب مربوط به کدام بانک است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_BANK_FOR_ACCOUNT

async def select_bank_for_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts asking for account details."""
    query = update.callback_query
    await query.answer()
    bank_id = query.data.split("_")[2]
    context.user_data['bank_id'] = bank_id
    context.user_data['account_data'] = {}
    
    await query.message.reply_text("شماره حساب را وارد کنید. برای رد شدن، /skip را بزنید.")
    return GET_ACCOUNT_NUM

async def get_account_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets account number and asks for card number."""
    context.user_data['account_data']['account_number'] = update.message.text
    await update.message.reply_text("شماره کارت ۱۶ رقمی را وارد کنید. برای رد شدن، /skip را بزنید.")
    return GET_CARD_NUM

async def skip_account_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skips account number and asks for card number."""
    context.user_data['account_data']['account_number'] = None
    await update.message.reply_text("شماره حساب ثبت نشد. حالا شماره کارت ۱۶ رقمی را وارد کنید. برای رد شدن، /skip را بزنید.")
    return GET_CARD_NUM

async def get_card_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets card number and asks for IBAN."""
    context.user_data['account_data']['card_number'] = update.message.text
    await update.message.reply_text("شماره شبا (IBAN) را بدون IR وارد کنید. برای رد شدن، /skip را بزنید.")
    return GET_IBAN

async def skip_card_num(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skips card number and asks for IBAN."""
    context.user_data['account_data']['card_number'] = None
    await update.message.reply_text("شماره کارت ثبت نشد. حالا شماره شبا (IBAN) را بدون IR وارد کنید. برای رد شدن، /skip را بزنید.")
    return GET_IBAN
    
async def get_iban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets IBAN and asks for card image."""
    context.user_data['account_data']['iban'] = f"IR{update.message.text}"
    await update.message.reply_text("در صورت تمایل عکس کارت را ارسال کنید. برای رد شدن، /skip را بزنید.")
    return GET_CARD_IMAGE

async def skip_iban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skips IBAN and asks for card image."""
    context.user_data['account_data']['iban'] = None
    await update.message.reply_text("شماره شبا ثبت نشد. حالا در صورت تمایل عکس کارت را ارسال کنید. برای رد شدن، /skip را بزنید.")
    return GET_CARD_IMAGE

async def get_card_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets card image and saves the account."""
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['account_data']['card_image_url'] = photo_file.file_id
    await save_account(update, context)
    return ConversationHandler.END

async def skip_card_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skips card image and saves the account."""
    context.user_data['account_data']['card_image_url'] = None
    await update.message.reply_text("عکسی ثبت نشد.")
    await save_account(update, context)
    return ConversationHandler.END

async def save_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Final step to save all account data to DB."""
    bank_id = context.user_data['bank_id']
    data = context.user_data['account_data']
    
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("خطا در اتصال به دیتابیس.")
        return
        
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO accounts (bank_id, account_number, card_number, iban, card_image_url)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (bank_id, data.get('account_number'), data.get('card_number'), data.get('iban'), data.get('card_image_url'))
            )
        conn.commit()
        await update.message.reply_text("✅ حساب جدید با موفقیت ثبت شد.")
    except Exception as e:
        logger.error(f"Error saving account: {e}")
        await update.message.reply_text("❌ خطایی در ثبت حساب رخ داد.")
    finally:
        conn.close()
        context.user_data.clear()

# ==============================================================================
# MAIN FUNCTION
# ==============================================================================
def main() -> None:
    """Start the bot."""
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for adding a person
    add_person_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_person_start, pattern="^add_person_start$")],
        states={
            GET_PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_person_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation handler for adding a bank
    add_bank_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_bank_start, pattern="^add_bank_start$")],
        states={
            SELECT_PERSON_FOR_BANK: [CallbackQueryHandler(select_person_for_bank, pattern="^select_person_")],
            GET_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bank_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation handler for adding an account
    add_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_account_start, pattern="^add_account_start$")],
        states={
            SELECT_PERSON_FOR_ACCOUNT: [CallbackQueryHandler(select_person_for_account, pattern="^select_person_")],
            SELECT_BANK_FOR_ACCOUNT: [CallbackQueryHandler(select_bank_for_account, pattern="^select_bank_")],
            GET_ACCOUNT_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account_num), CommandHandler("skip", skip_account_num)],
            GET_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_card_num), CommandHandler("skip", skip_card_num)],
            GET_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_iban), CommandHandler("skip", skip_iban)],
            GET_CARD_IMAGE: [MessageHandler(filters.PHOTO, get_card_image), CommandHandler("skip", skip_card_image)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("grant", grant_access))
    
    # Add conversation handlers
    application.add_handler(add_person_conv)
    application.add_handler(add_bank_conv)
    application.add_handler(add_account_conv)
    
    # This handler must be added AFTER the conversation handlers
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    application.run_polling()

if __name__ == "__main__":
    main()
