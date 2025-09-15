import os
import logging
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')

# Database connection details
DB_CONFIG = {
    "host": os.getenv('PGHOST'),
    "port": os.getenv('PGPORT'),
    "user": os.getenv('PGUSER'),
    "password": os.getenv('PGPASSWORD'),
    "dbname": os.getenv('PGDATABASE')
}

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Initialization ---
def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        logger.info("Database connection successful.")
        with conn.cursor() as cur:
            # Create users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    access_granted BOOLEAN DEFAULT FALSE,
                    full_name VARCHAR(255)
                );
            """)
            # Create persons table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS persons (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL
                );
            """)
            # Create banks table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS banks (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    person_id INTEGER REFERENCES persons(id) ON DELETE CASCADE
                );
            """)
            # Create accounts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    bank_id INTEGER REFERENCES banks(id) ON DELETE CASCADE,
                    account_number VARCHAR(255),
                    card_number VARCHAR(20),
                    iban VARCHAR(34),
                    card_image_url TEXT
                );
            """)
            conn.commit()
            logger.info("Tables checked/created successfully.")
    except psycopg2.OperationalError as e:
        logger.error(f"DATABASE CONNECTION FAILED: {e}")
        # In a real app, you might want to exit or handle this more gracefully
        raise
    except Exception as e:
        logger.error(f"An error occurred during DB initialization: {e}")
    finally:
        if conn:
            conn.close()

# --- Utility Functions ---
def get_db_connection():
    """Establishes and returns a new database connection."""
    try:
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to get DB connection: {e}")
        return None

def is_admin(update: Update) -> bool:
    """Checks if the user is the admin."""
    return update.effective_user.id == ADMIN_USER_ID

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    user = update.effective_user
    user_id = user.id
    full_name = user.full_name

    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("Error: Could not connect to the database.")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id = %s", (user_id,))
        db_user = cur.fetchone()

        if not db_user:
            is_user_admin = (user_id == ADMIN_USER_ID)
            cur.execute(
                "INSERT INTO users (telegram_id, full_name, is_admin, access_granted) VALUES (%s, %s, %s, %s)",
                (user_id, full_name, is_user_admin, is_user_admin)
            )
            conn.commit()
            if is_user_admin:
                await update.message.reply_text(f"Welcome Admin, {full_name}! Your access is configured.")
            else:
                await update.message.reply_text(f"Welcome, {full_name}! Your request for access has been sent to the admin.")
                await context.bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text=f"New user registration:\nName: {full_name}\nID: {user_id}\nUsername: @{user.username}\n\nUse /grant {user_id} to grant access."
                )
        else:
            # User exists, check access
            access_granted = db_user[3] # access_granted column
            if access_granted:
                keyboard = [[InlineKeyboardButton("Show Persons", callback_data='show_persons')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Welcome back! Choose an option:", reply_markup=reply_markup)
            else:
                await update.message.reply_text("Your access is still pending approval from the admin.")

    conn.close()

# --- Callback Query Handler ---
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer()

    # Simple logic for now, to be expanded
    if query.data == 'show_persons':
        await query.edit_message_text(text="Here are the persons...")
    # Add more logic for other callbacks (e.g., showing banks, accounts)
    else:
        await query.edit_message_text(text=f"Selected option: {query.data}")

# --- Admin Commands ---
async def grant_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to grant access to a user."""
    if not is_admin(update):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    try:
        user_id_to_grant = int(context.args[0])
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("DB connection error.")
            return
        
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET access_granted = TRUE WHERE telegram_id = %s", (user_id_to_grant,))
            conn.commit()
            if cur.rowcount > 0:
                await update.message.reply_text(f"Access granted to user ID: {user_id_to_grant}")
                await context.bot.send_message(chat_id=user_id_to_grant, text="You have been granted access! Press /start to begin.")
            else:
                await update.message.reply_text(f"User ID {user_id_to_grant} not found.")

        conn.close()

    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /grant <user_id>")
    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")

# --- Main Application ---
def main() -> None:
    """Start the bot."""
    # First, ensure the database and tables are ready
    try:
        init_db()
    except psycopg2.OperationalError:
        # Exit if the database connection fails on startup
        logger.critical("Could not connect to the database. The bot will not start.")
        return

    # Set up the bot application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("grant", grant_access))
    application.add_handler(CallbackQueryHandler(button))

    # Start the Bot
    logger.info("Starting bot polling...")
    application.run_polling()


if __name__ == '__main__':
    main()
