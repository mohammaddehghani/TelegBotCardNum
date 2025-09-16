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
    ContextTypes,
    filters,
)

# --- Load Environment Variables & Basic Config ---
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID_STR = os.getenv('ADMIN_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

if not all([BOT_TOKEN, ADMIN_ID_STR, DATABASE_URL]):
    raise ValueError("One or more environment variables (TELEGRAM_BOT_TOKEN, ADMIN_ID, DATABASE_URL) are missing.")
if not ADMIN_ID_STR.isdigit():
    raise ValueError("ADMIN_ID must be a number.")
ADMIN_ID = int(ADMIN_ID_STR)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Conversation States ---
(ADD_SELECT_PERSON, ADD_NEW_PERSON, ADD_SELECT_BANK, ADD_NEW_BANK, ADD_GET_NICKNAME, 
 ADD_GET_ACCOUNT_NUM, ADD_GET_CARD_NUM, ADD_GET_SHABA, ADD_GET_IS_SPECIAL, ADD_CONFIRM) = range(10)

(EDIT_SELECT_PERSON, EDIT_SELECT_BANK, EDIT_SELECT_ACCOUNT, EDIT_SHOW_OPTIONS, 
 EDIT_PROMPT_VALUE, EDIT_GET_VALUE, EDIT_DELETE_PROMPT, EDIT_DELETE_CONFIRM) = range(10, 18)

GET_USER_ID_FOR_APPROVAL = 18

# --- Database Functions ---
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        logger.error(f"DB Connection Error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, first_name VARCHAR(255), username VARCHAR(255), is_approved BOOLEAN DEFAULT FALSE);")
        cur.execute("CREATE TABLE IF NOT EXISTS persons (id SERIAL PRIMARY KEY, name VARCHAR(255) UNIQUE NOT NULL);")
        cur.execute("CREATE TABLE IF NOT EXISTS banks (id SERIAL PRIMARY KEY, name VARCHAR(255) UNIQUE NOT NULL);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY, person_id INTEGER REFERENCES persons(id) ON DELETE CASCADE, bank_id INTEGER REFERENCES banks(id) ON DELETE CASCADE,
                nickname VARCHAR(255), account_number VARCHAR(255), card_number VARCHAR(255), shaba_number VARCHAR(255), is_special BOOLEAN DEFAULT FALSE,
                UNIQUE(person_id, bank_id, nickname));
        """)
        conn.commit()
    conn.close()
    logger.info("Database initialized.")

# --- Helper & Permission Functions ---
def is_admin(user_id: int) -> bool: return user_id == ADMIN_ID
def is_approved_user(user_id: int) -> bool:
    if is_admin(user_id): return True
    conn = get_db_connection()
    if not conn: return False
    with conn.cursor() as cur:
        cur.execute("SELECT is_approved FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
    conn.close()
    return result[0] if result else False

# --- Generic Cancel ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_main_menu(update, context, "عملیات لغو شد و به منوی اصلی بازگشتید.")
    context.user_data.clear()
    return ConversationHandler.END

# --- Main Menu & Start Command ---
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text="... به منوی اصلی بازگشتید ..."):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("👤 مشاهده اطلاعات", callback_data='view_info_persons')],
        [InlineKeyboardButton("➕ افزودن اطلاعات", callback_data='add_start')],
        [InlineKeyboardButton("📝 ویرایش اطلاعات", callback_data='edit_start')],
    ]
    if is_admin(chat_id):
        keyboard.append([InlineKeyboardButton("⚙️ مدیریت کاربران", callback_data='admin_menu')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Try to edit the existing message, otherwise send a new one
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_approved_user(user.id):
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ خطای دیتابیس.")
            return
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, first_name, username, is_approved) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (user.id, user.first_name, user.username, False))
            conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"کاربر جدید: {user.full_name} (`{user.id}`) @{user.username or 'ندارد'}", parse_mode='Markdown')
        await update.message.reply_text("درخواست شما برای استفاده از ربات ثبت شد. لطفاً منتظر تایید ادمین بمانید.")
    else:
        await show_main_menu(update, context, "سلام! به ربات مدیریت حساب خوش آمدید.")

# --- VIEW INFORMATION FLOW ---
async def view_select_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM persons ORDER BY name")
        persons = cur.fetchall()
    conn.close()

    if not persons:
        await query.edit_message_text("هیچ شخصی ثبت نشده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" بازگشت", callback_data='main_menu')]]))
        return

    keyboard = [[InlineKeyboardButton(p[1], callback_data=f'view_person_{p[0]}')] for p in persons]
    keyboard.append([InlineKeyboardButton(" بازگشت به منوی اصلی", callback_data='main_menu')])
    await query.edit_message_text("اطلاعات کدام شخص را می‌خواهید مشاهده کنید؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def view_person_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    person_id = int(query.data.split('_')[2])
    context.user_data['view_person_id'] = person_id

    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT b.name, a.nickname, a.account_number, a.card_number, a.shaba_number FROM accounts a JOIN banks b ON a.bank_id = b.id WHERE a.person_id = %s AND a.is_special = TRUE ORDER BY b.name, a.nickname;", (person_id,))
        special_accounts = cur.fetchall()
        
        cur.execute("SELECT DISTINCT b.id, b.name FROM accounts a JOIN banks b ON a.bank_id = b.id WHERE a.person_id = %s AND a.is_special = FALSE ORDER BY b.name;", (person_id,))
        banks = cur.fetchall()
    conn.close()

    message_text = "حساب‌های با کاربرد خاص:\n\n" if special_accounts else "این شخص حساب با کاربرد خاص ندارد.\n\n"
    for acc in special_accounts:
        message_text += f"🏦 **{acc[0]} - {acc[1]}**\nشماره حساب: `{acc[2] or 'N/A'}`\nشماره کارت: `{acc[3] or 'N/A'}`\nشماره شبا: `{acc[4] or 'N/A'}`\n---\n"
    
    keyboard = [[InlineKeyboardButton(b[1], callback_data=f'view_bank_{b[0]}')] for b in banks]
    keyboard.append([InlineKeyboardButton(" بازگشت به لیست اشخاص", callback_data='view_info_persons')])
    keyboard.append([InlineKeyboardButton(" بازگشت به منوی اصلی", callback_data='main_menu')])
    
    message_text += "برای مشاهده حساب‌های عادی، یک بانک را انتخاب کنید:"
    await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def view_bank_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bank_id = int(query.data.split('_')[2])
    person_id = context.user_data.get('view_person_id')

    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT b.name, a.nickname, a.account_number, a.card_number, a.shaba_number FROM accounts a JOIN banks b ON a.bank_id = b.id WHERE a.person_id = %s AND a.bank_id = %s AND a.is_special = FALSE ORDER BY a.nickname;", (person_id, bank_id))
        accounts = cur.fetchall()
    conn.close()

    message_text = f"حساب‌های عادی در **{accounts[0][0]}**:\n\n"
    for acc in accounts:
        message_text += f"👤 **{acc[1]}**\nشماره حساب: `{acc[2] or 'N/A'}`\nشماره کارت: `{acc[3] or 'N/A'}`\nشماره شبا: `{acc[4] or 'N/A'}`\n---\n"
    
    keyboard = [[InlineKeyboardButton(" بازگشت به لیست بانک‌ها", callback_data=f'view_person_{person_id}')], [InlineKeyboardButton(" بازگشت به منوی اصلی", callback_data='main_menu')]]
    await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- ADD INFORMATION CONVERSATION ---
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM persons ORDER BY name")
        persons = cur.fetchall()
    conn.close()
    
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f'add_person_{p[0]}')] for p in persons]
    keyboard.append([InlineKeyboardButton("➕ افزودن شخص جدید", callback_data='add_person_new')])
    keyboard.append([InlineKeyboardButton("لغو", callback_data='cancel')])
    await query.edit_message_text("حساب برای کدام شخص است؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_SELECT_PERSON

async def add_select_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    person_id = int(query.data.split('_')[2])
    context.user_data['person_id'] = person_id
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM banks ORDER BY name")
        banks = cur.fetchall()
    conn.close()
    
    keyboard = [[InlineKeyboardButton(b[1], callback_data=f'add_bank_{b[0]}')] for b in banks]
    keyboard.append([InlineKeyboardButton("➕ افزودن بانک جدید", callback_data='add_bank_new')])
    keyboard.append([InlineKeyboardButton("لغو", callback_data='cancel')])
    await query.edit_message_text("کدام بانک؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_SELECT_BANK

async def add_prompt_new_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("نام شخص جدید را وارد کنید:")
    return ADD_NEW_PERSON

async def add_save_new_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    person_name = update.message.text.strip()
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        try:
            cur.execute("INSERT INTO persons (name) VALUES (%s) RETURNING id", (person_name,))
            person_id = cur.fetchone()[0]
            conn.commit()
            context.user_data['person_id'] = person_id
        except psycopg2.IntegrityError:
            await update.message.reply_text("این نام قبلاً ثبت شده. لطفاً دوباره تلاش کنید.")
            return ADD_NEW_PERSON
    conn.close()
    
    # Continue to bank selection
    return await add_select_person(update, context) # This needs a fake Update object for query
    # A better way:
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM banks ORDER BY name")
        banks = cur.fetchall()
    conn.close()
    keyboard = [[InlineKeyboardButton(b[1], callback_data=f'add_bank_{b[0]}')] for b in banks]
    keyboard.append([InlineKeyboardButton("➕ افزودن بانک جدید", callback_data='add_bank_new')])
    keyboard.append([InlineKeyboardButton("لغو", callback_data='cancel')])
    await update.message.reply_text("کدام بانک؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_SELECT_BANK


async def add_select_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['bank_id'] = int(query.data.split('_')[2])
    await query.edit_message_text("یک نام مستعار برای این حساب وارد کنید (مثلا: حقوق، پس‌انداز):")
    return ADD_GET_NICKNAME

async def add_prompt_new_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("نام بانک جدید را وارد کنید:")
    return ADD_NEW_BANK

async def add_save_new_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank_name = update.message.text.strip()
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        try:
            cur.execute("INSERT INTO banks (name) VALUES (%s) RETURNING id", (bank_name,))
            bank_id = cur.fetchone()[0]
            conn.commit()
            context.user_data['bank_id'] = bank_id
        except psycopg2.IntegrityError:
            await update.message.reply_text("این بانک قبلاً ثبت شده. لطفاً دوباره تلاش کنید.")
            return ADD_NEW_BANK
    conn.close()
    await update.message.reply_text("یک نام مستعار برای این حساب وارد کنید (مثلا: حقوق، پس‌انداز):")
    return ADD_GET_NICKNAME

async def add_get_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nickname'] = update.message.text.strip()
    await update.message.reply_text("شماره حساب را وارد کنید (برای رد شدن /skip):")
    return ADD_GET_ACCOUNT_NUM

async def add_get_account_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['account_number'] = None if update.message.text.lower() == '/skip' else update.message.text.strip()
    await update.message.reply_text("شماره کارت را وارد کنید (برای رد شدن /skip):")
    return ADD_GET_CARD_NUM

async def add_get_card_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['card_number'] = None if update.message.text.lower() == '/skip' else update.message.text.strip()
    await update.message.reply_text("شماره شبا (بدون IR) را وارد کنید (برای رد شدن /skip):")
    return ADD_GET_SHABA

async def add_get_shaba(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shaba_number'] = None if update.message.text.lower() == '/skip' else update.message.text.strip()
    keyboard = [[InlineKeyboardButton("بله", callback_data='add_special_yes'), InlineKeyboardButton("خیر", callback_data='add_special_no')]]
    await update.message.reply_text("آیا این حساب کاربرد خاص دارد؟ (در لیست اصلی نمایش داده شود)", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_GET_IS_SPECIAL

async def add_get_is_special(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['is_special'] = (query.data == 'add_special_yes')
    
    # Confirmation Step
    ud = context.user_data
    text = (f"اطلاعات زیر ثبت شود؟\n\n"
            f"شخص: (ID: {ud['person_id']})\n"
            f"بانک: (ID: {ud['bank_id']})\n"
            f"نام مستعار: {ud['nickname']}\n"
            f"شماره حساب: `{ud.get('account_number') or 'N/A'}`\n"
            f"شماره کارت: `{ud.get('card_number') or 'N/A'}`\n"
            f"شبا: `{ud.get('shaba_number') or 'N/A'}`\n"
            f"کاربرد خاص: {'بله' if ud['is_special'] else 'خیر'}")
            
    keyboard = [[InlineKeyboardButton("✅ تایید و ذخیره", callback_data='add_confirm_save'), InlineKeyboardButton("❌ لغو", callback_data='cancel')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return ADD_CONFIRM

async def add_save_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    conn = get_db_connection()
    if not conn:
        await update.callback_query.edit_message_text("❌ خطای دیتابیس.")
        return ConversationHandler.END
        
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (person_id, bank_id, nickname, account_number, card_number, shaba_number, is_special) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (ud['person_id'], ud['bank_id'], ud['nickname'], ud.get('account_number'), ud.get('card_number'), ud.get('shaba_number'), ud['is_special'])
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving account: {e}")
        await update.callback_query.edit_message_text("❌ خطایی در ثبت حساب رخ داد. ممکن است نام مستعار تکراری باشد.")
        context.user_data.clear()
        return ConversationHandler.END
    finally:
        conn.close()
    
    await update.callback_query.edit_message_text("✅ حساب با موفقیت ثبت شد.")
    await show_main_menu(update, context)
    context.user_data.clear()
    return ConversationHandler.END
    
# --- EDIT INFORMATION CONVERSATION ---
async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This is similar to add_start, but for editing
    query = update.callback_query
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM persons ORDER BY name")
        persons = cur.fetchall()
    conn.close()
    
    if not persons:
        await query.edit_message_text("هیچ شخصی برای ویرایش وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data='main_menu')]]))
        return ConversationHandler.END
        
    keyboard = [[InlineKeyboardButton(p[1], callback_data=f'edit_person_{p[0]}')] for p in persons]
    keyboard.append([InlineKeyboardButton("لغو", callback_data='cancel')])
    await query.edit_message_text("اطلاعات حساب کدام شخص را می‌خواهید ویرایش کنید؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_SELECT_PERSON

async def edit_select_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['person_id'] = int(query.data.split('_')[2])
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT b.id, b.name FROM accounts a JOIN banks b ON a.bank_id = b.id WHERE a.person_id = %s ORDER BY b.name", (context.user_data['person_id'],))
        banks = cur.fetchall()
    conn.close()

    if not banks:
        await query.edit_message_text("هیچ بانکی برای این شخص ثبت نشده.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data='edit_start')]]))
        return EDIT_SELECT_PERSON # Stay in the same state

    keyboard = [[InlineKeyboardButton(b[1], callback_data=f'edit_bank_{b[0]}')] for b in banks]
    keyboard.append([InlineKeyboardButton("لغو", callback_data='cancel')])
    await query.edit_message_text("کدام بانک؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_SELECT_BANK

async def edit_select_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['bank_id'] = int(query.data.split('_')[2])
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT id, nickname FROM accounts WHERE person_id = %s AND bank_id = %s ORDER BY nickname", (context.user_data['person_id'], context.user_data['bank_id']))
        accounts = cur.fetchall()
    conn.close()

    keyboard = [[InlineKeyboardButton(a[1], callback_data=f'edit_acc_{a[0]}')] for a in accounts]
    keyboard.append([InlineKeyboardButton("لغو", callback_data='cancel')])
    await query.edit_message_text("کدام حساب؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_SELECT_ACCOUNT

async def edit_select_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    account_id = int(query.data.split('_')[2])
    context.user_data['account_id'] = account_id
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("SELECT nickname, account_number, card_number, shaba_number, is_special FROM accounts WHERE id = %s", (account_id,))
        acc = cur.fetchone()
    conn.close()
    
    context.user_data['current_account'] = acc
    text = (f"اطلاعات فعلی حساب:\n\n"
            f"نام مستعار: {acc[0]}\n"
            f"شماره حساب: `{acc[1] or 'N/A'}`\n"
            f"شماره کارت: `{acc[2] or 'N/A'}`\n"
            f"شبا: `{acc[3] or 'N/A'}`\n"
            f"کاربرد خاص: {'بله' if acc[4] else 'خیر'}\n\n"
            f"چه کاری می‌خواهید انجام دهید؟")
            
    keyboard = [
        [InlineKeyboardButton("ویرایش نام مستعار", callback_data='edit_field_nickname')],
        [InlineKeyboardButton("ویرایش شماره حساب", callback_data='edit_field_account_number')],
        [InlineKeyboardButton("ویرایش شماره کارت", callback_data='edit_field_card_number')],
        [InlineKeyboardButton("ویرایش شبا", callback_data='edit_field_shaba_number')],
        [InlineKeyboardButton("تغییر وضعیت 'کاربرد خاص'", callback_data='edit_field_is_special')],
        [InlineKeyboardButton("🗑️ حذف این حساب", callback_data='edit_delete')],
        [InlineKeyboardButton("بازگشت", callback_data='cancel')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return EDIT_SHOW_OPTIONS

async def edit_prompt_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    field = query.data.split('_')[2]
    context.user_data['edit_field'] = field
    
    if field == 'is_special':
        current_status = context.user_data['current_account'][4]
        new_status = not current_status
        conn = get_db_connection()
        if not conn: return ConversationHandler.END
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET is_special = %s WHERE id = %s", (new_status, context.user_data['account_id']))
            conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ وضعیت 'کاربرد خاص' با موفقیت به '{'بله' if new_status else 'خیر'}' تغییر کرد.")
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    prompts = {
        'nickname': "نام مستعار جدید را وارد کنید:",
        'account_number': "شماره حساب جدید را وارد کنید (برای خالی کردن /skip):",
        'card_number': "شماره کارت جدید را وارد کنید (برای خالی کردن /skip):",
        'shaba_number': "شماره شبای جدید را وارد کنید (برای خالی کردن /skip):",
    }
    await query.edit_message_text(prompts[field])
    return EDIT_GET_VALUE

async def edit_get_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data['edit_field']
    new_value = None if update.message.text.lower() == '/skip' else update.message.text.strip()
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        # Using format to build query is safe here because `field` is from our controlled callbacks
        query = f"UPDATE accounts SET {field} = %s WHERE id = %s"
        cur.execute(query, (new_value, context.user_data['account_id']))
        conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ اطلاعات با موفقیت به‌روز شد.")
    await show_main_menu(update, context)
    context.user_data.clear()
    return ConversationHandler.END

async def edit_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("✅ بله، حذف کن", callback_data='delete_confirm_yes'), InlineKeyboardButton("❌ خیر، لغو", callback_data='cancel')]]
    await update.callback_query.edit_message_text("آیا از حذف این حساب اطمینان دارید؟ این عمل غیرقابل بازگشت است.", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_DELETE_CONFIRM

async def edit_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("DELETE FROM accounts WHERE id = %s", (context.user_data['account_id'],))
        conn.commit()
    conn.close()
    
    await update.callback_query.edit_message_text("🗑️ حساب با موفقیت حذف شد.")
    await show_main_menu(update, context)
    context.user_data.clear()
    return ConversationHandler.END

# --- ADMIN USER MANAGEMENT ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ تایید دسترسی", callback_data='admin_grant')],
        [InlineKeyboardButton("❌ لغو دسترسی", callback_data='admin_revoke')],
        [InlineKeyboardButton("📋 لیست کاربران", callback_data='admin_list')],
        [InlineKeyboardButton("بازگشت", callback_data='main_menu')],
    ]
    await update.callback_query.edit_message_text("منوی مدیریت کاربران:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, first_name, username, is_approved FROM users ORDER BY user_id")
        users = cur.fetchall()
    conn.close()
    
    message = "لیست کاربران:\n\n" + "\n".join([f"👤 {u[1]} (`{u[0]}`) - {'✅' if u[3] else '❌'}" for u in users])
    await update.callback_query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data='admin_menu')]]))

async def admin_prompt_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = update.callback_query.data.split('_')[1]
    context.user_data['admin_action'] = action
    prompt_text = "شناسه کاربری که می‌خواهید دسترسی‌اش را تایید کنید، وارد نمایید:" if action == 'grant' else "شناسه کاربری که می‌خواهید دسترسی‌اش را لغو کنید، وارد نمایید:"
    await update.callback_query.edit_message_text(prompt_text)
    return GET_USER_ID_FOR_APPROVAL

async def admin_process_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("شناسه نامعتبر است. یک عدد وارد کنید.")
        return GET_USER_ID_FOR_APPROVAL

    action = context.user_data['admin_action']
    new_status = (action == 'grant')
    
    conn = get_db_connection()
    if not conn: return ConversationHandler.END
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET is_approved = %s WHERE user_id = %s", (new_status, user_id))
        conn.commit()
        if cur.rowcount == 0:
            await update.message.reply_text(f"کاربری با شناسه `{user_id}` یافت نشد.")
        else:
            status_text = "تایید شد" if new_status else "لغو شد"
            await update.message.reply_text(f"دسترسی کاربر `{user_id}` با موفقیت {status_text}.")
            try:
                user_message = "دسترسی شما به ربات تایید شد. از /start استفاده کنید." if new_status else "دسترسی شما به ربات توسط ادمین لغو شد."
                await context.bot.send_message(chat_id=user_id, text=user_message)
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
    conn.close()

    await show_main_menu(update, context)
    return ConversationHandler.END


def main() -> None:
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    
    # --- Conversation Handlers ---
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern='^add_start$')],
        states={
            ADD_SELECT_PERSON: [
                CallbackQueryHandler(add_select_person, pattern='^add_person_\\d+$'),
                CallbackQueryHandler(add_prompt_new_person, pattern='^add_person_new$'),
            ],
            ADD_NEW_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_save_new_person)],
            ADD_SELECT_BANK: [
                CallbackQueryHandler(add_select_bank, pattern='^add_bank_\\d+$'),
                CallbackQueryHandler(add_prompt_new_bank, pattern='^add_bank_new$'),
            ],
            ADD_NEW_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_save_new_bank)],
            ADD_GET_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_nickname)],
            ADD_GET_ACCOUNT_NUM: [MessageHandler(filters.TEXT, add_get_account_num)],
            ADD_GET_CARD_NUM: [MessageHandler(filters.TEXT, add_get_card_num)],
            ADD_GET_SHABA: [MessageHandler(filters.TEXT, add_get_shaba)],
            ADD_GET_IS_SPECIAL: [CallbackQueryHandler(add_get_is_special, pattern='^add_special_(yes|no)$')],
            ADD_CONFIRM: [CallbackQueryHandler(add_save_account, pattern='^add_confirm_save$')],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern='^cancel$'), CommandHandler('cancel', cancel)],
    )

    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern='^edit_start$')],
        states={
            EDIT_SELECT_PERSON: [CallbackQueryHandler(edit_select_person, pattern='^edit_person_\\d+$')],
            EDIT_SELECT_BANK: [CallbackQueryHandler(edit_select_bank, pattern='^edit_bank_\\d+$')],
            EDIT_SELECT_ACCOUNT: [CallbackQueryHandler(edit_select_account, pattern='^edit_acc_\\d+$')],
            EDIT_SHOW_OPTIONS: [
                CallbackQueryHandler(edit_prompt_value, pattern='^edit_field_'),
                CallbackQueryHandler(edit_delete_prompt, pattern='^edit_delete$'),
            ],
            EDIT_GET_VALUE: [MessageHandler(filters.TEXT, edit_get_value)],
            EDIT_DELETE_CONFIRM: [CallbackQueryHandler(edit_delete_confirm, pattern='^delete_confirm_yes$')],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern='^cancel$'), CommandHandler('cancel', cancel)],
    )

    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_prompt_user_id, pattern='^admin_(grant|revoke)$')],
        states={
            GET_USER_ID_FOR_APPROVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_process_user_id)],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern='^cancel$'), CommandHandler('cancel', cancel)],
    )

    # --- Add handlers to application ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_conv)
    application.add_handler(edit_conv)
    application.add_handler(admin_conv)
    
    # Static menu navigations
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(admin_menu, pattern='^admin_menu$'))
    application.add_handler(CallbackQueryHandler(admin_list_users, pattern='^admin_list$'))
    
    # View flow
    application.add_handler(CallbackQueryHandler(view_select_person, pattern='^view_info_persons$'))
    application.add_handler(CallbackQueryHandler(view_person_details, pattern='^view_person_'))
    application.add_handler(CallbackQueryHandler(view_bank_accounts, pattern='^view_bank_'))

    # Fallback cancel for conversations
    application.add_handler(CallbackQueryHandler(cancel, pattern='^cancel$'))
    
    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()
