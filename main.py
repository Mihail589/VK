import telebot
import vk_api
import requests
import time
import threading
import logging
from telebot.types import Message
import config
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename="log.log",
    filemode="w"
)

# 🔹 Токены
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
VK_TOKEN = config.VK_TOKEN
VK_GROUP_ID = config.VK_GROUP_ID

print(f"VK Token: {VK_TOKEN[:10]}...")  # Логируем только начало токена для безопасности

# 🔹 Инициализация HTTP сессии с повторными попытками
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
session.mount("http://", adapter)
session.mount("https://", adapter)

# 🔹 Инициализация ботов
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

# 🔹 Хранилище для сборки поста
pending_posts = {}
lock = threading.Lock()

def safe_request(url, timeout=30):
    """Безопасный запрос с обработкой ошибок"""
    try:
        response = session.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка запроса к {url}: {e}")
        return None

# 🔹 Функция загрузки фото
def upload_photos_to_vk(photo_urls):
    try:
        if not photo_urls:
            return []
        
        # Получаем URL для загрузки
        upload_data = vk.photos.getWallUploadServer(group_id=VK_GROUP_ID)
        upload_url = upload_data['upload_url']
        
        # Загружаем первую фотографию
        photo_data = safe_request(photo_urls[0])
        if not photo_data:
            return []
        
        files = {'file': ('photo.jpg', photo_data, 'image/jpeg')}
        
        # Загружаем на сервер VK
        upload_response = session.post(upload_url, files=files, timeout=30).json()
        
        # Сохраняем фото
        photo_info = vk.photos.saveWallPhoto(
            group_id=VK_GROUP_ID,
            photo=upload_response['photo'],
            server=upload_response['server'],
            hash=upload_response['hash']
        )
        
        return [f'photo{p["owner_id"]}_{p["id"]}' for p in photo_info]
    except Exception as e:
        logging.error(f"Ошибка загрузки фото: {e}")
        return []

# 🔹 Функция загрузки видео
def upload_video_to_vk(video_url, text):
    try:
        # Получаем URL для загрузки видео
        video_data = vk.video.save(
            group_id=VK_GROUP_ID,
            name=text[:100] if text else 'Video from Telegram',
            description=text[:1000] if text else '',
            no_comments=0
        )
        
        if 'upload_url' not in video_data:
            logging.error(f"Не получили upload_url для видео: {video_data}")
            return None
            
        upload_url = video_data['upload_url']
        
        # Загружаем видео файл
        video_content = safe_request(video_url)
        if not video_content:
            return None
        
        # Загружаем на сервер VK
        response = session.post(upload_url, files={'video_file': video_content}, timeout=120).json()
        
        if 'video_id' in response:
            return f"video{response['owner_id']}_{response['video_id']}"
        else:
            logging.error(f"Ошибка загрузки видео: {response}")
            return None
            
    except Exception as e:
        logging.error(f"Ошибка загрузки видео: {e}")
        return None

# 🔹 Функция загрузки аудио
def upload_audio_to_vk(audio_url):
    try:
        # Получаем URL для загрузки аудио
        upload_data = vk.audio.getWallUploadServer(group_id=VK_GROUP_ID)
        upload_url = upload_data['upload_url']
        
        # Загружаем аудио файл
        audio_content = safe_request(audio_url)
        if not audio_content:
            return None
        
        # Загружаем на сервер VK
        response = session.post(upload_url, files={'file': audio_content}, timeout=30).json()
        
        # Сохраняем аудио
        audio_info = vk.audio.save(
            server=response.get('server'),
            audio=response.get('audio'),
            hash=response.get('hash')
        )
        
        if 'id' in audio_info:
            return f"audio{audio_info['owner_id']}_{audio_info['id']}"
        else:
            logging.error(f"Ошибка сохранения аудио: {audio_info}")
            return None
            
    except Exception as e:
        logging.error(f"Ошибка загрузки аудио: {e}")
        return None

# 🔹 Функция отправки поста в VK
def send_to_vk(message_id):
    with lock:
        if message_id not in pending_posts:
            logging.warning(f"Пост с ID {message_id} не найден в pending_posts")
            return
        
        data = pending_posts.pop(message_id)
        if not data:
            return
            
        text, media_files, video_files, audio_files, poll_data = data

    attachments = []
    
    # Загружаем фото
    if media_files:
        photos = upload_photos_to_vk(media_files)
        attachments.extend(photos)
    
    # Загружаем аудио
    audio_attachment = None
    if audio_files:
        audio_attachment = upload_audio_to_vk(audio_files[0])
        if audio_attachment:
            attachments.append(audio_attachment)
    
    # Загружаем видео
    video_attachment = None
    if video_files:
        video_attachment = upload_video_to_vk(video_files[0], text)
        if video_attachment:
            attachments.append(video_attachment)

    try:
        # Создаем опрос если есть
        poll_id = None
        if poll_data:
            try:
                poll = vk.polls.create(
                    owner_id=f"-{VK_GROUP_ID}",
                    question=poll_data['question'][:500],
                    answers=poll_data['answers'],
                    is_anonymous=1,
                    background_id=9  # можно изменить
                )
                poll_id = poll.get('id')
                if poll_id:
                    attachments.append(f"poll-{VK_GROUP_ID}_{poll_id}")
            except Exception as e:
                logging.error(f"Ошибка создания опроса: {e}")

        # Отправляем пост
        vk.wall.post(
            owner_id=f"-{VK_GROUP_ID}",
            message=text[:4000] if text else "",  # VK ограничение 4000 символов
            attachments=",".join(attachments) if attachments else None,
            from_group=1
        )
        
        logging.info(f"✅ Пост отправлен в VK! (ID: {message_id})")
        print(f"✅ Пост отправлен в VK! (ID: {message_id})")
        
    except Exception as e:
        logging.error(f"❌ Ошибка отправки поста: {e}")
        print(f"❌ Ошибка отправки поста: {e}")

# 🔹 Обработчик постов
@bot.channel_post_handler(content_types=['text', 'photo', 'video', 'audio', 'poll'])
def forward_to_vk(message: Message):
    message_id = message.message_id
    
    # Получаем текст
    text = None
    if message.content_type == 'text':
        text = message.text
    elif message.content_type in ['photo', 'video']:
        text = message.caption
    
    # Пропускаем определенные сообщения
    if (not text and 
        message.content_type not in ['video', 'poll', 'audio'] and 
        (not text or text != "Календарь Счастья 🙌")):
        return

    media_files = []
    video_files = []
    audio_files = []
    poll_data = None

    try:
        if message.content_type == 'photo':
            file_info = bot.get_file(message.photo[-1].file_id)
            media_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"]
        elif message.content_type == 'video':
            file_info = bot.get_file(message.video.file_id)
            video_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"]
        elif message.content_type == 'audio':
            file_info = bot.get_file(message.audio.file_id)
            audio_files = [f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"]
        elif message.content_type == 'poll':
            poll_data = {
                'question': message.poll.question,
                'answers': [option.text for option in message.poll.options]
            }
    except Exception as e:
        logging.error(f"Ошибка получения файла: {e}")
        return

    with lock:
        pending_posts[message_id] = [text, media_files, video_files, audio_files, poll_data]

    # Используем таймер с задержкой 3 секунды для сбора всех данных
    threading.Timer(3.0, send_to_vk, args=[message_id]).start()

# 🔹 Обработчик ошибок
@bot.exception_handler
def handle_exceptions(exception):
    logging.critical(f"Критическая ошибка бота: {exception}")
    
    try:
        bot.send_message(5318464880, f"⚠️ Ошибка бота: {str(exception)[:1000]}")
        
        # Отправляем лог файл
        try:
            with open("log.log", "rb") as f:
                bot.send_document(5318464880, f, caption="Лог файл бота")
        except:
            pass
            
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение об ошибке: {e}")
    
    # Ждем перед перезапуском
    time.sleep(10)
    return True

# 🔹 Запуск бота
def run_bot():
    logging.info("🤖 Бот запускается...")
    print("🤖 Бот запускается...")
    
    while True:
        try:
            logging.info("Запуск polling...")
            bot.polling(non_stop=True, interval=1, timeout=30)
        except Exception as e:
            logging.error(f"Ошибка polling: {e}")
            print(f"Ошибка polling: {e}")
            time.sleep(5)  # Ждем перед перезапуском

if __name__ == "__main__":
    run_bot()
