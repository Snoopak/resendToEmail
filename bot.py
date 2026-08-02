import os
import smtplib
import asyncio
import logging
import socket
from email.message import EmailMessage
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from database import (
    init_db, save_user_email, verify_code, get_user_email,
    is_user_verified, get_user_data, delete_user
)

# --- ЗАВАНТАЖЕННЯ .env ---
try:
    from dotenv import load_dotenv
    if os.path.exists(".env"):
        load_dotenv()
        print("✅ .env файл завантажено")
except ImportError:
    pass

# --- ПАТЧ ДЛЯ ВИПРАВЛЕННЯ [Errno 101] (Примусовий IPv4) ---
old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(*args, **kwargs):
    responses = old_getaddrinfo(*args, **kwargs)
    return [response for response in responses if response[0] == socket.AF_INET]
socket.getaddrinfo = new_getaddrinfo
# --------------------------------------------------------

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- ЗМІННІ СЕРЕДОВИЩА ---
TOKEN = os.getenv("BOT_TOKEN")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not TOKEN:
    logging.error("❌ BOT_TOKEN не знайдено! Створіть .env файл.")
    exit()

if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
    logging.warning("⚠️ EMAIL_ADDRESS або EMAIL_PASSWORD не задані! Бот не зможе надсилати листи.")

# Ініціалізація БД
init_db()

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ============================================================
# FSM СТЕЙТИ
# ============================================================
class Registration(StatesGroup):
    waiting_for_email = State()
    waiting_for_code = State()

class MailFlow(StatesGroup):
    waiting_for_subject = State()
    waiting_for_text = State()

# ============================================================
# ГЛОБАЛЬНІ ЗМІННІ
# ============================================================
buffer = {}
semaphore = asyncio.Semaphore(3)

# ============================================================
# КЛАВІАТУРИ
# ============================================================

# 1. Reply Keyboard (клавіатура внизу)
def get_main_reply_keyboard():
    """Головна клавіатура внизу (Reply Keyboard)."""
    buttons = [
        [KeyboardButton(text="📧 Змінити email")],
        [KeyboardButton(text="❓ Допомога")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=False
    )

# 2. Inline Keyboard (кнопки в повідомленні)
def get_action_keyboard():
    """Кнопки для роботи з файлами."""
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити тему", callback_data="add_subject")],
        [InlineKeyboardButton(text="📤 Відправити зараз", callback_data="send_now")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ============================================================

async def send_verification_code(email: str, code: str):
    """Надсилає красивий HTML-лист з кодом підтвердження (без JS)."""
    subject = "🔐 Підтвердження email для Telegram-бота"

    text = f"""
Ваш код підтвердження: {code}

Цей код дійсний 5 хвилин.
Введіть його в Telegram-боті, щоб завершити реєстрацію.

Якщо ви не реєструвалися в боті @ResendToEmail_bot — просто проігноруйте цей лист.
"""

    html = f"""
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Підтвердження email</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background: #fafafa;
                margin: 0;
                padding: 30px 15px;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .container {{
                max-width: 480px;
                width: 100%;
                margin: 0 auto;
                background: #ffffff;
                border-radius: 16px;
                padding: 40px 35px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.03);
                border: 1px solid #ebebeb;
            }}
            .badge {{
                display: inline-block;
                background: #eef2ff;
                color: #4338ca;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 14px;
                border-radius: 30px;
                letter-spacing: 0.3px;
                text-transform: uppercase;
                margin-bottom: 20px;
            }}
            h1 {{
                font-size: 24px;
                font-weight: 700;
                color: #111827;
                margin: 0 0 8px 0;
                letter-spacing: -0.4px;
            }}
            .sub {{
                color: #6b7280;
                font-size: 15px;
                line-height: 1.6;
                margin: 0 0 28px 0;
            }}
            .code-block {{
                background: #f9fafb;
                border-radius: 12px;
                padding: 24px;
                text-align: center;
                border: 1px solid #e5e7eb;
                margin-bottom: 28px;
                user-select: all;
                -webkit-user-select: all;
                cursor: text;
                transition: background 0.15s, border-color 0.15s;
            }}
            .code-block:hover {{
                background: #f3f4f6;
                border-color: #4338ca;
            }}
            .code-number {{
                font-size: 44px;
                font-weight: 700;
                letter-spacing: 10px;
                color: #111827;
                font-feature-settings: "tnum";
            }}
            .copy-hint {{
                font-size: 13px;
                color: #9ca3af;
                margin-top: 10px;
                user-select: none;
                -webkit-user-select: none;
            }}
            .code-block:hover .copy-hint {{
                color: #6b7280;
            }}
            .info-box {{
                background: #f3f4f6;
                border-radius: 10px;
                padding: 16px 20px;
                font-size: 14px;
                color: #374151;
                line-height: 1.5;
                border-left: 3px solid #4338ca;
            }}
            .info-box strong {{
                display: block;
                margin-bottom: 2px;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #f3f4f6;
                font-size: 12px;
                color: #9ca3af;
                text-align: center;
                line-height: 1.6;
            }}
            .footer a {{
                color: #4338ca;
                text-decoration: none;
                font-weight: 500;
            }}
            .footer a:hover {{
                text-decoration: underline;
            }}
            .bot-name {{
                font-weight: 600;
                color: #111827;
            }}
            @media (max-width: 480px) {{
                .container {{
                    padding: 28px 20px;
                }}
                .code-number {{
                    font-size: 34px;
                    letter-spacing: 6px;
                }}
                h1 {{
                    font-size: 21px;
                }}
            }}
            @media (prefers-color-scheme: dark) {{
                body {{
                    background: #1a1a1a;
                }}
                .container {{
                    background: #262626;
                    border-color: #404040;
                }}
                h1 {{
                    color: #f3f4f6;
                }}
                .sub {{
                    color: #a3a3a3;
                }}
                .code-block {{
                    background: #1f1f1f;
                    border-color: #404040;
                }}
                .code-number {{
                    color: #f3f4f6;
                }}
                .code-block:hover {{
                    background: #2a2a2a;
                }}
                .info-box {{
                    background: #1f1f1f;
                    color: #d1d5db;
                    border-left-color: #818cf8;
                }}
                .footer {{
                    border-top-color: #404040;
                    color: #737373;
                }}
                .bot-name {{
                    color: #f3f4f6;
                }}
                .badge {{
                    background: #312e81;
                    color: #a5b4fc;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="badge">🔐 Безпека</div>
            <h1>Підтвердіть email</h1>
            <p class="sub">
                Ви отримали цей код, тому що реєструєтесь у боті
                <strong>@ResendToEmail_bot</strong>.
            </p>
            <div class="code-block">
                <div class="code-number">{code}</div>
                <div class="copy-hint">👆 Виділіть код і скопіюйте його</div>
            </div>
            <div class="info-box">
                <strong>✏️ Як завершити реєстрацію</strong>
                Вставте цей код у Telegram-бот. Після підтвердження ви зможете надсилати файли на свою пошту.
            </div>
            <div class="footer">
                <span class="bot-name">ResendToEmail</span> ·
                <a href="https://t.me/ResendToEmail_bot">@ResendToEmail_bot</a><br>
                Якщо ви не запитували цей код — просто проігноруйте лист.
            </div>
        </div>
    </body>
    </html>
    """

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = email
    msg.set_content(text)
    msg.add_alternative(html, subtype='html')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)


async def get_forward_data(message: types.Message, bot: Bot) -> dict:
    """Витягує дані автора, якщо повідомлення переслане."""
    if not message.forward_origin:
        return None

    data = {"name": "Невідомо", "type": "", "link": "", "avatar_path": None}
    origin = message.forward_origin

    try:
        if isinstance(origin, types.MessageOriginUser):
            user = origin.sender_user
            data["name"] = user.full_name
            data["type"] = "Користувач"
            if user.username:
                data["link"] = f"https://t.me/{user.username}"
            
            photos = await bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                photo = photos.photos[0][0]
                avatar_path = f"avatar_u_{user.id}.jpg"
                file = await bot.get_file(photo.file_id)
                await bot.download(file, destination=avatar_path)
                data["avatar_path"] = avatar_path

        elif isinstance(origin, types.MessageOriginChannel):
            chat = origin.chat
            data["name"] = chat.title
            data["type"] = "Канал"
            if chat.username:
                data["link"] = f"https://t.me/{chat.username}"
            
            chat_info = await bot.get_chat(chat.id)
            if chat_info.photo:
                avatar_path = f"avatar_c_{chat.id}.jpg"
                file = await bot.get_file(chat_info.photo.small_file_id)
                await bot.download(file, destination=avatar_path)
                data["avatar_path"] = avatar_path

        elif isinstance(origin, types.MessageOriginHiddenUser):
            data["name"] = origin.sender_user_name
            data["type"] = "Прихований користувач"
            
        elif isinstance(origin, types.MessageOriginChat):
            data["name"] = origin.sender_chat.title
            data["type"] = "Група"
            
    except Exception as e:
        logging.error(f"Помилка отримання аватарки: {e}")

    return data


def generate_html_email(subject: str, text: str, forward_data: dict) -> str:
    """Генерує HTML-лист з блоком автора (якщо є) та футером."""
    formatted_text = text.replace('\n', '<br>')
    
    forward_html = ""
    if forward_data:
        avatar_src = "cid:avatar_img" if forward_data.get("avatar_path") else "https://ui-avatars.com/api/?name=" + forward_data['name'][:1] + "&background=random"
        link_html = f'<br><a href="{forward_data["link"]}" style="font-size: 13px; color: #4299e1; text-decoration: none;">🔗 Перейти до профілю/каналу</a>' if forward_data.get("link") else ''
        
        forward_html = f"""
        <div style="background-color: #f1f5f9; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; margin-bottom: 20px; display: table; width: 100%;">
            <div style="display: table-cell; width: 50px; vertical-align: top; padding-right: 15px;">
                <img src="{avatar_src}" style="width: 45px; height: 45px; border-radius: 50%; display: block; background-color: #cbd5e1; object-fit: cover;">
            </div>
            <div style="display: table-cell; vertical-align: middle;">
                <strong style="color: #2b6cb0; font-size: 15px; display: block; margin-bottom: 2px;">{forward_data['name']}</strong>
                <span style="font-size: 12px; color: #64748b; background-color: #e2e8f0; padding: 2px 6px; border-radius: 4px;">{forward_data['type']}</span>
                {link_html}
            </div>
        </div>
        """

    footer = """
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
    <p style="text-align: center; font-size: 12px; color: #a0aec0;">
        📨 Це повідомлення надіслано через Telegram-бота <strong><a href="https://t.me/ResendToEmail_bot" style="color: #4299e1; text-decoration: underline;">@ResendToEmail_bot</a></strong>
    </p>
    """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f9; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
            <div style="background-color: #2b6cb0; color: #ffffff; padding: 15px 20px; text-align: center;">
                <h2 style="margin: 0; font-size: 18px;">{subject}</h2>
            </div>
            <div style="padding: 25px; line-height: 1.6; font-size: 15px;">
                {forward_html}
                <div style="background-color: #ffffff; border-left: 4px solid #4299e1; padding: 15px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                    {formatted_text}
                </div>
                {footer}
            </div>
        </div>
    </body>
    </html>
    """


def send_email_sync(files: list, text_content: str, subject: str, forward_data: dict, target_email: str):
    """Відправка листа через Gmail SMTP на вказану пошту."""
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = target_email
    
    msg.set_content(text_content)
    html_content = generate_html_email(subject, text_content, forward_data)
    msg.add_alternative(html_content, subtype='html')

    if forward_data and forward_data.get("avatar_path") and os.path.exists(forward_data["avatar_path"]):
        with open(forward_data["avatar_path"], 'rb') as img:
            msg.get_payload()[1].add_related(img.read(), maintype='image', subtype='jpeg', cid='avatar_img')

    for file_obj in files:
        file_path = file_obj["path"]
        file_name = file_obj["name"]
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                file_data = f.read()
            msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=file_name)
        
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)


async def execute_send(chat_id: int):
    """Асинхронна обгортка для відправки."""
    if chat_id not in buffer: 
        return
    
    user_email = get_user_email(chat_id)
    if not user_email:
        await bot.send_message(chat_id, "❌ Email не підтверджено! Напиши /start")
        return
    
    data = buffer.pop(chat_id)
    files = data.get("files", [])
    text_content = data.get("text", "Без тексту")
    subject = data.get("subject", "📁 Файли з Telegram")
    forward_data = data.get("forward_data")
    
    try:
        async with semaphore:
            await asyncio.to_thread(send_email_sync, files, text_content, subject, forward_data, user_email)
        
        files_count = len(files)
        await bot.send_message(
            chat_id, 
            f"✅ Відправлено на {user_email}! (Вкладень: {files_count})\n**Тема:** {subject}", 
            parse_mode="Markdown"
        )
        logging.info(f"📨 Лист відправлено для {chat_id} на {user_email}")
    except Exception as e:
        logging.error(f"Помилка: {e}")
        await bot.send_message(chat_id, f"❌ Помилка: {e}")
    finally:
        for file_obj in files:
            if os.path.exists(file_obj["path"]): 
                os.remove(file_obj["path"])
        if forward_data and forward_data.get("avatar_path") and os.path.exists(forward_data["avatar_path"]):
            os.remove(forward_data["avatar_path"])


async def process_and_send_timer(chat_id: int):
    """Автоматична відправка через 8 секунд."""
    try:
        await asyncio.sleep(8.0) 
        if chat_id in buffer:
            reply_id = buffer[chat_id].get("reply_id")
            if reply_id:
                try: 
                    await bot.edit_message_reply_markup(chat_id=chat_id, message_id=reply_id, reply_markup=None)
                except: 
                    pass
            await bot.send_message(chat_id, "⏳ Час вийшов, відправляю...")
            await execute_send(chat_id)
    except asyncio.CancelledError:
        pass 


# ============================================================
# ОБРОБНИКИ КОМАНД
# ============================================================

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    if user_data and user_data["is_verified"]:
        await message.reply(
            f"👋 Вітаю! Твій email: **{user_data['email']}**\n\n"
            "Надішли мені фото або файл — я відправлю його на пошту.\n"
            "📌 Можна змінити тему або текст через кнопки.",
            parse_mode="Markdown",
            reply_markup=get_main_reply_keyboard()
        )
        return

    if user_data and not user_data["is_verified"]:
        await state.set_state(Registration.waiting_for_code)
        await message.reply(
            "📧 На твою пошту вже надіслано код підтвердження.\n\n"
            "Введи 6-значний код із листа.\n\n"
            "Не отримав листа? Напиши /resend_code"
        )
        return

    await state.set_state(Registration.waiting_for_email)
    await message.reply(
        "📧 **Вітаю!**\n\n"
        "Будь ласка, введи свою email-адресу.\n"
        "На неї я надішлю код підтвердження.\n\n"
        "Наприклад: `my@email.com`",
        parse_mode="Markdown"
    )


@dp.message(F.text == "/resend_code")
async def resend_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if not user_data:
        await message.reply("❌ Спочатку напиши /start, щоб зареєструватися.")
        return
    
    if user_data["is_verified"]:
        await message.reply("✅ Твій email вже підтверджено!")
        return
    
    code = save_user_email(user_id, user_data["email"])
    
    try:
        await send_verification_code(user_data["email"], code)
    except Exception as e:
        logging.error(f"Помилка повторної відправки: {e}")
        await message.reply("❌ Не вдалося надіслати лист. Спробуй пізніше.")
        return
    
    await state.set_state(Registration.waiting_for_code)
    await message.reply(
        "📧 **Новий код надіслано!**\n\n"
        "Перевір пошту і введи 6-значний код.\n"
        "⏳ Код дійсний 5 хвилин."
    )


# ============================================================
# ОБРОБНИКИ РЕЄСТРАЦІЇ
# ============================================================

@dp.message(Registration.waiting_for_email, F.text)
async def email_received(message: types.Message, state: FSMContext):
    email = message.text.strip()
    user_id = message.from_user.id
    
    if "@" not in email or "." not in email:
        await message.reply("❌ Це схоже на неправильну email-адресу. Спробуй ще раз.")
        return
    
    code = save_user_email(user_id, email)
    
    try:
        await send_verification_code(email, code)
    except Exception as e:
        logging.error(f"Помилка відправки коду: {e}")
        await message.reply("❌ Не вдалося надіслати лист. Перевір правильність email або спробуй пізніше.")
        return
    
    await state.set_state(Registration.waiting_for_code)
    await message.reply(
        "📧 **Код надіслано!**\n\n"
        "Перевір пошту і введи 6-значний код сюди.\n"
        "⏳ Код дійсний 5 хвилин.\n\n"
        "Не отримав листа? Напиши /resend_code"
    )


@dp.message(Registration.waiting_for_code, F.text)
async def code_received(message: types.Message, state: FSMContext):
    code = message.text.strip()
    user_id = message.from_user.id
    
    if verify_code(user_id, code):
        await state.clear()
        email = get_user_email(user_id)
        await message.reply(
            f"✅ **Email підтверджено!**\n\n"
            f"📧 {email}\n\n"
            "Тепер надсилай мені файли, і я буду відправляти їх на цю пошту.",
            reply_markup=get_main_reply_keyboard()
        )
    else:
        await message.reply(
            "❌ **Невірний або прострочений код!**\n\n"
            "Спробуй ще раз або напиши /resend_code для нового."
        )


# ============================================================
# ОБРОБНИКИ REPLY KEYBOARD (кнопки внизу)
# ============================================================

@dp.message(F.text == "📧 Змінити email")
async def change_email_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    import sqlite3
    from database import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()

    await state.set_state(Registration.waiting_for_email)
    await message.reply(
        "📧 Введи нову email-адресу, на яку я буду надсилати листи.\n\n"
        "Наприклад: `my@email.com`",
        parse_mode="Markdown"
    )


@dp.message(F.text == "❓ Допомога")
async def help_button(message: types.Message):
    await message.reply(
        "📖 **Допомога**\n\n"
        "1️⃣ Надішли мені будь-який файл або фото.\n"
        "2️⃣ Я відправлю його на твою пошту.\n"
        "3️⃣ Можна змінити тему або дописати текст через кнопки.\n\n"
        "📧 Щоб змінити email — натисни кнопку нижче.",
        parse_mode="Markdown",
        reply_markup=get_main_reply_keyboard()
    )


# ============================================================
# ОБРОБНИКИ ФАЙЛІВ ТА ТЕКСТУ
# ============================================================

@dp.message(F.document | F.photo | F.video | F.audio | F.voice | F.animation)
async def handle_files(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    media_group_id = message.media_group_id
    
    if not is_user_verified(chat_id):
        await message.reply("❌ Спочатку підтверди email командою /start")
        return
    
    if message.document:
        file_id, original_name = message.document.file_id, message.document.file_name or "document"
    elif message.photo:
        file_id, original_name = message.photo[-1].file_id, "photo.jpg"
    elif message.video:
        file_id, original_name = message.video.file_id, message.video.file_name or "video.mp4"
    elif message.audio:
        file_id, original_name = message.audio.file_id, message.audio.file_name or "audio.mp3"
    elif message.voice:
        file_id, original_name = message.voice.file_id, "voice.ogg"
    elif message.animation:
        file_id, original_name = message.animation.file_id, message.animation.file_name or "animation.mp4"
    else: 
        return
    
    safe_prefix = str(message.message_id)
    file_path, file_name = f"{safe_prefix}_{original_name}", original_name
    
    try:
        file = await bot.get_file(file_id)
        await bot.download(file, destination=file_path)
        
        forward_data = await get_forward_data(message, bot)
        caption_text = message.caption if message.caption else "Без тексту"

        if chat_id not in buffer or (media_group_id and buffer[chat_id].get("media_group_id") != media_group_id):
            await state.clear()
            if chat_id in buffer:
                if "task" in buffer[chat_id]: 
                    buffer[chat_id]["task"].cancel()
                for old_f in buffer[chat_id].get("files", []):
                    if os.path.exists(old_f["path"]): 
                        os.remove(old_f["path"])
            
            reply = await message.reply(
                "📥 **Отримано!** Можеш дописати текст або обрати дію.", 
                reply_markup=get_action_keyboard(), 
                parse_mode="Markdown"
            )

            buffer[chat_id] = {
                "files": [{"path": file_path, "name": file_name}],
                "text": caption_text,
                "subject": "📁 Файли з Telegram",
                "reply_id": reply.message_id,
                "media_group_id": media_group_id,
                "forward_data": forward_data,
                "task": asyncio.create_task(process_and_send_timer(chat_id))
            }
        else:
            buffer[chat_id]["files"].append({"path": file_path, "name": file_name})
            if caption_text != "Без тексту" and buffer[chat_id]["text"] == "Без тексту":
                buffer[chat_id]["text"] = caption_text
            
    except Exception as e:
        await message.reply(f"❌ Помилка: {e}")


@dp.message(F.text & ~F.document & ~F.photo & ~F.video & ~F.audio & ~F.voice & ~F.animation)
async def handle_quick_text(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    
    if await state.get_state() is not None: 
        return 
        
    if chat_id in buffer and "task" in buffer[chat_id]:
        buffer[chat_id]["task"].cancel() 
        reply_id = buffer[chat_id].get("reply_id")
        if reply_id:
            try: 
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=reply_id, reply_markup=None)
            except: 
                pass
            
        buffer[chat_id]["text"] = message.text
        if message.forward_origin:
            buffer[chat_id]["forward_data"] = await get_forward_data(message, bot)
            
        await execute_send(chat_id)


# ============================================================
# ОБРОБНИКИ INLINE КНОПОК (в повідомленні)
# ============================================================

@dp.callback_query(F.data == "send_now")
async def cb_send_now(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id in buffer:
        buffer[chat_id]["task"].cancel()
        await callback.message.edit_text("⏳ Відправляю...")
        await execute_send(chat_id)
    await callback.answer()


@dp.callback_query(F.data == "add_subject")
async def cb_add_subject(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    if chat_id in buffer:
        buffer[chat_id]["task"].cancel() 
        await state.set_state(MailFlow.waiting_for_subject) 
        await callback.message.edit_text("✏️ Напиши нову **тему** для листа:", parse_mode="Markdown")
    await callback.answer()


# ============================================================
# ОБРОБНИКИ FSM (ТЕМА / ТЕКСТ)
# ============================================================

@dp.message(MailFlow.waiting_for_subject, F.text)
async def state_subject_received(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    if chat_id in buffer:
        buffer[chat_id]["subject"] = message.text
        await state.set_state(MailFlow.waiting_for_text)
        await message.reply("✅ Тему збережено!\nТепер напиши **текст** листа (або натисни /skip).", parse_mode="Markdown")
    else: 
        await state.clear()


@dp.message(MailFlow.waiting_for_text, F.text)
async def state_text_received(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    if chat_id in buffer:
        if message.text != "/skip": 
            buffer[chat_id]["text"] = message.text
        await message.reply("⏳ Відправляю...")
        await execute_send(chat_id)
    await state.clear()


# ============================================================
# ЗАПУСК БОТА
# ============================================================

async def main():
    logging.info("🔥 Бот-місток запущений!")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(0.5)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Polling впав: {e}")

if __name__ == "__main__":
    asyncio.run(main())