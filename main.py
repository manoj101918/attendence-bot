import math
import time
import asyncio
import logging
from functools import partial
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, TypeHandler, PicklePersistence
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    filename='bot_debug.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# --- CONFIGURATION ---
ECAP_URL = "https://webprosindia.com/vignanit"
TOKEN =os.getenv("TOKEN")

# Cache the driver path so we don't install on every request
try:
    DRIVER_PATH = ChromeDriverManager().install()
    logging.info(f"Driver installed at: {DRIVER_PATH}")
except Exception as e:
    logging.error(f"Failed to install driver: {e}")
    DRIVER_PATH = None

def get_attendance_data(uname, pword):
    logging.info(f"get_attendance_data called for user ending in ...{str(uname)[-3:] if uname else 'None'}")
    if not DRIVER_PATH:
        logging.warning("Driver path not found. Re-installing...")
        try:
             path = ChromeDriverManager().install()
             driver_service = Service(path)
        except Exception as e:
             logging.error(f"Fatal error installing driver: {e}")
             return None
    else:
        driver_service = Service(DRIVER_PATH)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--blink-settings=imagesEnabled=false") # Disable images
    
    try:
        driver = webdriver.Chrome(service=driver_service, options=options)
    except Exception as e:
        logging.error(f"Failed to create driver: {e}")
        return None

    wait = WebDriverWait(driver, 15)

    try:
        # 1. Login Phase
        driver.get(ECAP_URL)
        wait.until(EC.presence_of_element_located((By.NAME, "txtId2"))).send_keys(uname)
        driver.find_element(By.NAME, "txtPwd2").send_keys(pword)
        driver.find_element(By.NAME, "imgBtn2").click()

        # 2. Navigation Phase
        register_link = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "ACADAMIC REGISTER")))
        register_link.click()

        # 3. Frame Handling
        try:
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "capIframeId")))
        except:
            try:
                wait.until(EC.frame_to_be_available_and_switch_to_it(0))
            except:
                pass 

        # 4. Data Extraction
        result = {
            "daily_log": [],
            "last_date": "Unknown",
            "total": None
        }
        
        total_attended = 0
        total_held = 0
        
        # Locate table
        try:
            target_table = driver.find_element(By.XPATH, "//table[.//td[contains(text(), 'Sl.No')]]")
            rows = target_table.find_elements(By.TAG_NAME, "tr")
        except:
            rows = driver.find_elements(By.XPATH, "//table//tr")

        if len(rows) > 0:
            pass 

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 3: 
                try:
                    col_text_0 = cols[0].text.strip()
                    if "Sl.No" in col_text_0 or "Subject" in col_text_0:
                        try:
                            result["last_date"] = cols[-3].text.strip()
                        except:
                            pass
                        continue
                    
                    subject = cols[1].text.strip()
                    
                    if "TOTAL" in subject.upper() or not subject:
                        continue

                    text_att = cols[-2].text.strip()
                    daily_status = cols[-3].text.strip()
                    
                    if "/" in text_att:
                        parts = text_att.split("/")
                        if len(parts) == 2:
                            attended = int(parts[0])
                            held = int(parts[1])
                            
                            total_attended += attended
                            total_held += held
                            
                            if daily_status and daily_status != "-":
                                result["daily_log"].append({
                                    "subject": subject,
                                    "status": daily_status
                                })

                except Exception as e:
                    continue
        
        if total_held > 0:
            perc = (total_attended / total_held) * 100
            result["total"] = {
                "attended": total_attended,
                "held": total_held,
                "percentage": perc
            }
        
        logging.info("Data fetching successful")
        return result

    except Exception as e:
        logging.error(f"Scraper Error: {e}")
        return None
    finally:
        driver.quit()

# --- HELPER FUNCTIONS ---
def calculate_needs(attended, held):
    percentage = (attended / held) * 100
    if percentage < 75:
        needed = math.ceil((0.75 * held - attended) / 0.25)
        return needed, "need"
    else:
        can_skip = math.floor((attended - 0.75 * held) / 0.75)
        return can_skip, "skip"

def format_attendance_message(data, username):
    if not data or not data.get("total"):
        debug_info = f"Found {len(data.get('daily_log', []))} logs." if data else "Data is None"
        return f"❌ Could not fetch attendance data. {debug_info}"

    total_row = data["total"]
    daily_log = data["daily_log"]
    last_date = data["last_date"]
    
    msg = f"👤 *User:* {username}\n"

    val, type_ = calculate_needs(total_row['attended'], total_row['held'])
    if type_ == "need":
        msg += f"⚠️ *Status:* You need to attend **{val}** more classes to reach 75%.\n"
    else:
        msg += f"✅ *Status:* You can safely skip **{val}** classes and stay above 75%.\n"

    msg += f"📊 *Total:* {total_row['attended']}/{total_row['held']} ({total_row['percentage']:.2f}%)\n"

    if daily_log and last_date != "Unknown":
        msg += f"\n📅 *Activity on {last_date}:*\n"
        for item in daily_log:
            status_icon = "✅" if "P" in item['status'] else "❌"
            msg += f"{status_icon} *{item['subject']}:* {item['status']}\n"
    else:
        msg += "\nℹ️ *Activity:* No updates found for the latest date.\n"

    msg += f"\n_Last Fetched: {time.strftime('%H:%M:%S')}_"
    return msg

# --- BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Welcome to your VIIT Attendance Bot.\nUse `/login username password` to get your status.", parse_mode='Markdown')

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log EVERY update received to verify reception"""
    logging.info(f"RAW UPDATE RECEIVED: {update.to_dict()}")

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please use the format: `/login <username> <password>`")
        return

    username, password = context.args[0], context.args[1]
    
    # Store credentials
    context.user_data['username'] = username
    context.user_data['password'] = password
    logging.info(f"User {username} logged in")
    
    # Force save to disk
    try:
        await context.application.persistence.flush()
    except Exception as e:
        logging.error(f"Persistence flush failed: {e}")

    status_msg = await update.message.reply_text("⏳ Navigating to Academic Register... This may take up to 30 seconds.")

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, partial(get_attendance_data, username, password))

    if data:
        result_text = format_attendance_message(data, username)
        # New callback data identifier 'refresh_v2' to invalidate old buttons
        keyboard = [[InlineKeyboardButton("🔄 Update", callback_data="refresh_v2")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(result_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await status_msg.edit_text("❌ Login failed or table not found. Ensure your credentials are correct.")

async def refresh_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logging.info(f"Processing callback: {query.data}")
    
    # Enforce v2 to ignore old session buttons
    if query.data != "refresh_v2":
        await query.answer("⚠️ This button is expired. Please /login again.", show_alert=True)
        return

    await query.answer("Refreshing data...")

    username = context.user_data.get('username')
    password = context.user_data.get('password')

    if not username or not password:
        logging.warning(f"Refresh failed for user {context._user_id}: Missing credentials")
        await query.edit_message_text("❌ Session expired. Please /login again.")
        return

    try:
        await query.edit_message_text(f"{query.message.text_markdown}\n\n⏳ _Refreshing data..._", parse_mode='Markdown')
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(None, partial(get_attendance_data, username, password))
        
        if data:
            result_text = format_attendance_message(data, username)
            keyboard = [[InlineKeyboardButton("🔄 Update", callback_data="refresh_v2")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(result_text, parse_mode='Markdown', reply_markup=reply_markup)
            logging.info("Refresh UI updated successfully.")
        else:
            await query.edit_message_text("❌ Update failed. Could not fetch data.")
            logging.error("Refresh failed: Scraper returned None.")

    except Exception as e:
        logging.error(f"Refresh Error trace: {e}")
        await query.edit_message_text(f"❌ An error occurred: {e}")

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    print("Bot is starting...")
    
    # Enable persistence for production
    persistence = PicklePersistence(filepath='bot_session.pickle')
    app = Application.builder().token(TOKEN).persistence(persistence).build()
    
    # Add raw logger FIRST
    app.add_handler(TypeHandler(Update, log_all_updates), group=-1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CallbackQueryHandler(refresh_data))
    

    app.run_polling()
