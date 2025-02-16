import telebot
import vk_api
import requests
import time
import threading, asyncio
from telebot.types import Message
import logging
logging.basicConfig(
    level=logging.DEBUG, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename="log.log",  # Запись в файл
    filemode="w"  # "w" - перезапись, "a" - добавление в файл
)

# 🔹 Токены
TELEGRAM_TOKEN = '8156604929:AAEZvaMT1_Gvlcy9T5LpDoD0Xf8TztdBkCA'
VK_TOKEN = "vk1.a.Vkg2I8eJDP4qsaX3oGFS07jJxF5t4eWyGADc5XhDE-LQChIL_noApkbZt8ZzcsDVrvG_73_CdArj19AlFI8LtVQLELLKklZ-NKXmgnFQeX8xhLf0cwR1drsPrwOgi6-DPtvZoZltgIvGt34CHTsTXYSPwZKaFXea4b1-KnI8voq9lx-iJ2I1HgD1DAI4p7yw99gH916JtdtEhVB93GiaCQ"
VK_GROUP_ID = "229078892"

# 🔹 Инициализация
bot = telebot.TeleBot(TELEGRAM_TOKEN)
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

# 🔹 Хранилище для сборки поста
pending_posts = {}
lock = threading.Lock()

# 🔹 Функция загрузки фото
def upload_photos_to_vk(photo_files):
    try:
        if not photo_files:
            return []
        upload_url = vk.photos.getWallUploadServer(group_id=VK_GROUP_ID)['upload_url']
        files = {'file': ('photo.jpg', requests.get(photo_files[0]).content, 'image/jpeg')}
        response = requests.post(upload_url, files=files).json()
        photo_info = vk.photos.saveWallPhoto(group_id=VK_GROUP_ID, photo=response['photo'], server=response['server'], hash=response['hash'])
        return [f'photo{p["owner_id"]}_{p["id"]}' for p in photo_info]
    except Exception as e:
        print(f"❌ Ошибка загрузки фото: {e}")
        return []

# 🔹 Функция загрузки видео
def upload_video_to_vk(video_file):
    try:
        upload_url = vk.video.save(group_id=VK_GROUP_ID, name='Uploaded Video', description='Video from Telegram')['upload_url']
        video_data = requests.get(video_file).content
        response = requests.post(upload_url, files={'file': video_data}).json()
        return f"video{response['owner_id']}_{response['id']}"
    except Exception as e:
        print(f"❌ Ошибка загрузки видео: {e}")
        return None

# 🔹 Функция загрузки аудио
def upload_audio_to_vk(audio_file):
    try:
        upload_url = vk.audio.getWallUploadServer(group_id=VK_GROUP_ID)['upload_url']
        files = {'file': requests.get(audio_file).content}
        response = requests.post(upload_url, files=files).json()
        audio_info = vk.audio.save(owner_id=response['owner_id'], audio=response['audio'])
        return f"audio{audio_info['owner_id']}_{audio_info['id']}"
    except Exception as e:
        print(f"❌ Ошибка загрузки аудио: {e}")
        return None

# 🔹 Функция отправки поста в VK
def send_to_vk(message_id):
    with lock:
        if message_id not in pending_posts:
            return
        text, media_files, video_files, audio_files, poll_data = pending_posts.pop(message_id)
    
    # Проверяем, есть ли запрещенные теги
    if text and any(tag in text.lower() for tag in ['#мысли', '#мемы']):
        print(f"⚠️ Пост с тегами {text} не был отправлен в VK.")
        return

    attachments = upload_photos_to_vk(media_files) if media_files else []
    audio_attachment = upload_audio_to_vk(audio_files[0]) if audio_files else None
    video_attachment = upload_video_to_vk(video_files[0]) if video_files else None
    
    try:
        post_text = text or ""
        if audio_attachment:
            post_text += f"\n{audio_attachment}"
        if video_attachment:
            post_text += f"\n{video_attachment}"
        # Если есть опрос, создаем его
        if poll_data:
            vk.polls.create(
                owner_id=f"-{VK_GROUP_ID}",
                question=poll_data['question'],
                answers=poll_data['answers'],
                is_anonymous=1,
            )

        vk.wall.post(owner_id=f"-{VK_GROUP_ID}", message=post_text, attachments=",".join(attachments))
        print(f"✅ Пост отправлен в VK! (ID: {message_id})")
        logging.info(f"✅ Пост отправлен в VK! (ID: {message_id})")
    except Exception as e:
        print(f"❌ Ошибка отправки поста: {e}")
        logging.info(f"❌ Ошибка отправки поста: {e}")

# 🔹 Обработчик постов
@bot.channel_post_handler(content_types=['text', 'photo', 'video', 'audio', 'poll'])
def forward_to_vk(message: Message):
    message_id = message.message_id  
    text = message.text or message.caption  

    if not text and message.content_type != 'video' and message.content_type != "poll" and message.content_type != "audio":
        return

    media_files = []
    video_files = []
    audio_files = []
    poll_data = None
    
    if message.content_type == 'photo':
        media_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{bot.get_file(message.photo[-1].file_id).file_path}"]
    elif message.content_type == 'video':
        video_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{bot.get_file(message.video.file_id).file_path}"]
    elif message.content_type == 'audio':
        audio_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{bot.get_file(message.audio.file_id).file_path}"]
    elif message.content_type == 'poll':
        poll_data = {
            'question': message.poll.question,
            'answers': [option.text for option in message.poll.options]
        }

    with lock:
        pending_posts[message_id] = [text, media_files[:1], video_files, audio_files, poll_data]

    threading.Timer(2, send_to_vk, args=[message_id]).start()

# 🔹 Запуск бота
print("🤖 Бот запущен...")
logging.info("🤖 Бот запущен...")

while True:
    try:
        bot.polling(non_stop=False)
    except Exception as e:
        logging.critical(e)
        asyncio.run(bot.sendMessage(5318464880, f"Ошибка {e}"))
        with open("log.log", "rb") as f:
            bot.send_document(5318464880, f, caption="Документ для вас!")