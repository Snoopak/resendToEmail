import os
import smtplib
import asyncio
import logging
from email.message import EmailMessage
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv("BOT_TOKEN")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
TARGET_EMAIL = os.getenv("TARGET_EMAIL", EMAIL_ADDRESS) # За замовчуванням ту саму пошту       

bot = Bot(token=TOKEN)
dp = Dispatcher()

class MailFlow(StatesGroup):
    waiting_for_subject = State()
    waiting_for_text = State()

buffer = {}

def get_action_keyboard():
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити тему", callback_data="add_subject")],
        [InlineKeyboardButton(text="📤 Відправити зараз", callback_data="send_now")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def get_forward_data(message: types.Message, bot: Bot) -> dict:
    """Витягує ім'я, посилання та завантажує аватарку автора пересланого повідомлення."""
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
            
            # Спроба завантажити аватарку користувача
            photos = await bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                photo = photos.photos[0][0] # Беремо найменший розмір для аватарки
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
            
            # Спроба завантажити аватарку каналу
            chat_info = await bot.get_chat(chat.id)
            if chat_info.photo:
                avatar_path = f"avatar_c_{chat.id}.jpg"
                file = await bot.get_file(chat_info.photo.small_file_id)
                await bot.download(file, destination=avatar_path)
                data["avatar_path"] = avatar_path

        elif isinstance(origin, types.MessageOriginHiddenUser):
            data["name"] = origin.sender_user_name
            data["type"] = "Прихований користувач (Налаштування приватності)"
            
        elif isinstance(origin, types.MessageOriginChat):
            data["name"] = origin.sender_chat.title
            data["type"] = "Група"
            
    except Exception as e:
        logging.error(f"Помилка отримання аватарки: {e}")

    return data

def generate_html_email(subject: str, text: str, forward_data: dict) -> str:
    """Генерує HTML-шаблон із блоком автора, якщо є переслане повідомлення."""
    formatted_text = text.replace('\n', '<br>')
    
    forward_html = ""
    if forward_data:
        # Якщо є аватарка, використовуємо CID (внутрішнє посилання), інакше - заглушку
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
            </div>
        </div>
    </body>
    </html>
    """

def send_email_sync(files: list, text_content: str, subject: str, forward_data: dict):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = TARGET_EMAIL
    
    msg.set_content(text_content)
    
    html_content = generate_html_email(subject, text_content, forward_data)
    msg.add_alternative(html_content, subtype='html')

    # Вбудовуємо аватарку в HTML тіло (якщо вона є)
    if forward_data and forward_data.get("avatar_path") and os.path.exists(forward_data["avatar_path"]):
        with open(forward_data["avatar_path"], 'rb') as img:
            # get_payload()[1] звертається до HTML частини листа
            msg.get_payload()[1].add_related(img.read(), maintype='image', subtype='jpeg', cid='avatar_img')

    # Додаємо звичайні вкладення (файли/фото)
    for file_obj in files:
        file_path = file_obj["path"]
        file_name = file_obj["name"]
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                file_data = f.read()
            msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=file_name)
        
    with smtplib.SMTP_SSL('smtp.ukr.net', 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)

async def execute_send(chat_id: int):
    if chat_id not in buffer: return
    data = buffer.pop(chat_id)
    files = data.get("files", [])
    text_content = data.get("text", "Без тексту")
    subject = data.get("subject", "📁 Файли з Telegram / Viber")
    forward_data = data.get("forward_data")
    
    try:
        await asyncio.to_thread(send_email_sync, files, text_content, subject, forward_data)
        files_count = len(files)
        await bot.send_message(chat_id, f"✅ Відправлено! (Вкладень: {files_count})\n**Тема:** {subject}", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Помилка відправки для {chat_id}: {e}")
        await bot.send_message(chat_id, f"❌ Помилка: {e}")
    finally:
        # Видаляємо медіафайли
        for file_obj in files:
            if os.path.exists(file_obj["path"]): os.remove(file_obj["path"])
        # Видаляємо аватарку
        if forward_data and forward_data.get("avatar_path") and os.path.exists(forward_data["avatar_path"]):
            os.remove(forward_data["avatar_path"])

async def process_and_send_timer(chat_id: int):
    try:
        await asyncio.sleep(8.0) 
        if chat_id in buffer:
            reply_id = buffer[chat_id].get("reply_id")
            if reply_id:
                try: await bot.edit_message_reply_markup(chat_id=chat_id, message_id=reply_id, reply_markup=None)
                except: pass
            await bot.send_message(chat_id, "⏳ Час вийшов, відправляю...")
            await execute_send(chat_id)
    except asyncio.CancelledError:
        pass 

@dp.message(F.document | F.photo | F.video | F.audio | F.voice | F.animation)
async def handle_files(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    media_group_id = message.media_group_id
    
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
    else: return
    
    safe_prefix = str(message.message_id)
    file_path, file_name = f"{safe_prefix}_{original_name}", original_name
    
    try:
        file = await bot.get_file(file_id)
        await bot.download(file, destination=file_path)
        
        # Асинхронно отримуємо дані автора пересилання
        forward_data = await get_forward_data(message, bot)
        caption_text = message.caption if message.caption else "Без тексту"

        if chat_id not in buffer or (media_group_id and buffer[chat_id].get("media_group_id") != media_group_id):
            await state.clear()
            if chat_id in buffer:
                if "task" in buffer[chat_id]: buffer[chat_id]["task"].cancel()
                for old_f in buffer[chat_id].get("files", []):
                    if os.path.exists(old_f["path"]): os.remove(old_f["path"])
            
            reply = await message.reply("📥 **Отримано!** Можеш дописати текст або обрати дію.", reply_markup=get_action_keyboard(), parse_mode="Markdown")

            buffer[chat_id] = {
                "files": [{"path": file_path, "name": file_name}],
                "text": caption_text,
                "subject": "📁 Файли з Telegram / Viber",
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
    if await state.get_state() is not None: return 
        
    if chat_id in buffer and "task" in buffer[chat_id]:
        buffer[chat_id]["task"].cancel() 
        reply_id = buffer[chat_id].get("reply_id")
        if reply_id:
            try: await bot.edit_message_reply_markup(chat_id=chat_id, message_id=reply_id, reply_markup=None)
            except: pass
            
        buffer[chat_id]["text"] = message.text
        # Якщо текст відправлено як окреме повідомлення (але це пересилка), оновлюємо дані автора
        if message.forward_origin:
            buffer[chat_id]["forward_data"] = await get_forward_data(message, bot)
            
        await execute_send(chat_id)

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

@dp.message(MailFlow.waiting_for_subject, F.text)
async def state_subject_received(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    if chat_id in buffer:
        buffer[chat_id]["subject"] = message.text
        await state.set_state(MailFlow.waiting_for_text)
        await message.reply("✅ Тему збережено!\nТепер напиши **текст** листа (або натисни /skip).", parse_mode="Markdown")
    else: await state.clear()

@dp.message(MailFlow.waiting_for_text, F.text)
async def state_text_received(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    if chat_id in buffer:
        if message.text != "/skip": buffer[chat_id]["text"] = message.text
        await message.reply("⏳ Відправляю...")
        await execute_send(chat_id)
    await state.clear()

async def main():
    logging.info("🔥 Бот з аватарками запущений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())