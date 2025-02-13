import telebot
import vk_api
import requests
import time
import threading
from telebot.types import Message

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
        files = {f'file0': ('photo.jpg', requests.get(photo_files[0]).content, 'image/jpeg')}
        response = requests.post(upload_url, files=files).json()
        photo_info = vk.photos.saveWallPhoto(group_id=VK_GROUP_ID, photo=response['photo'], server=response['server'], hash=response['hash'])
        return [f'photo{p["owner_id"]}_{p["id"]}' for p in photo_info]
    except Exception as e:
        print(f"❌ Ошибка загрузки фото: {e}")
        return []

# 🔹 Функция отправки поста в VK https://oauth.vk.com/blank.html#access_token=vk1.a.Vkg2I8eJDP4qsaX3oGFS07jJxF5t4eWyGADc5XhDE-LQChIL_noApkbZt8ZzcsDVrvG_73_CdArj19AlFI8LtVQLELLKklZ-NKXmgnFQeX8xhLf0cwR1drsPrwOgi6-DPtvZoZltgIvGt34CHTsTXYSPwZKaFXea4b1-KnI8voq9lx-iJ2I1HgD1DAI4p7yw99gH916JtdtEhVB93GiaCQ&expires_in=0&user_id=85840378&email=gamarnik_2011@mail.ru

def send_to_vk(message_id):
    with lock:
        if message_id not in pending_posts:
            return
        text, media_files, video_files = pending_posts.pop(message_id)
    
    # Проверяем, есть ли запрещенные теги
    if text and any(tag in text.lower() for tag in ['#мысли', '#мемы']):
        print(f"⚠️ Пост с тегами {text} не был отправлен в VK.")
        return

    attachments = upload_photos_to_vk(media_files) if media_files else []
    
    try:
        vk.wall.post(owner_id=f"-{VK_GROUP_ID}", message=text or "", attachments=",".join(attachments))
        print(f"✅ Пост отправлен в VK! (ID: {message_id})")
    except Exception as e:
        print(f"❌ Ошибка отправки поста: {e}")

# 🔹 Обработчик постов
a = []
@bot.channel_post_handler(content_types=['text', 'photo', 'video'])
def forward_to_vk(message: Message):
    global a
    message_id = message.message_id  
    text = message.text or message.caption  

    if not text and message.content_type != 'video':
        return
    print(text)  
    media_files = []
    video_files = []
    
    if text and any(tag in text.lower() for tag in ['#мысли', '#мемы']):
        print(f"⚠️ Пост с тегами {text} не был обработан.")
        return
    
    if message.content_type == 'photo':
        media_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{bot.get_file(message.photo[-1].file_id).file_path}"]
    elif message.content_type == 'video':
        video_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{bot.get_file(message.video.file_id).file_path}"]

    with lock:
        if message_id in pending_posts:
            if media_files:
                pending_posts[message_id][1] = media_files[:1]  # Оставляем только одно фото
            pending_posts[message_id][2].extend(video_files)
        else:
            pending_posts[message_id] = [text, media_files[:1], video_files]

    threading.Timer(2, send_to_vk, args=[message_id]).start()

# 🔹 Запуск бота
print("🤖 Бот запущен...")
bot.polling(none_stop=True)
