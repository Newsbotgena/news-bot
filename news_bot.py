import feedparser
import telegram
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
import re
import os
import json
import time
import threading

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("7850099140:AAHFALV-Ed5tkKLqgoIQakItcxkE7_HYRdk")
YOUR_CHAT_ID = int(os.getenv("58354833"))

# Русскоязычные RSS-фиды по теме ИИ и умный дом
RSS_FEEDS = [
    'https://habr.com/ru/rss/hub/machine_learning/ ',
    'https://habr.com/ru/rss/hub/smart_home/ ',
    'https://vc.ru/feed ',
    'https://www.3dnews.ru/software-news/feed/ ',
    'https://www.ixbt.com/news.rss ',
    'https://ain.ua/feed/ ',
    'https://www.cnews.ru/inc/rss/news_all_full.asp ',
    'https://rssexport.rbc.ru/rbcnews/news/technology.rss ',
]

# Файл для хранения уже отправленных ссылок
SENT_NEWS_FILE = 'sent_news.json'

# === Вспомогательные функции ===
def get_week_ago():
    return datetime.now() - timedelta(days=7)

def is_russian_text(text):
    """Проверяет, является ли текст русскоязычным"""
    if not text:
        return False
    cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    return cyrillic_chars / len(text) > 0.5 if len(text) > 0 else False

def clean_html(text):
    """Очищает текст от недопустимых HTML-тегов и закрывает незакрытые."""
    if not text:
        return ''

    allowed_tags = ['<b>', '</b>', '<i>', '</i>', '<a>', '</a>', '<code>', '</code>', '<pre>', '</pre>', '<u>', '</u>', '<s>', '</s>']
    cleaned_text = text

    # Удаляем все теги, кроме допустимых
    for tag in re.findall(r'<[^>]+>', text):
        if tag not in allowed_tags:
            cleaned_text = cleaned_text.replace(tag, '')

    # Закрываем незакрытые теги
    open_tags = {
        '<b>': '</b>',
        '<i>': '</i>',
        '<u>': '</u>',
        '<s>': '</s>',
        '<code>': '</code>',
        '<pre>': '</pre>'
    }

    for tag, closing_tag in open_tags.items():
        if cleaned_text.count(tag) > cleaned_text.count(closing_tag):
            cleaned_text += closing_tag

    # Убираем лишние пробелы
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text

def load_sent_news():
    """Загружает список уже отправленных ссылок из файла"""
    if os.path.exists(SENT_NEWS_FILE):
        with open(SENT_NEWS_FILE, 'r', encoding='utf-8') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()

def save_sent_news(sent_links):
    """Сохраняет список отправленных ссылок в файл"""
    with open(SENT_NEWS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(sent_links), f, ensure_ascii=False, indent=2)

# === Парсер новостей ===
def fetch_news(sent_links):
    news = []
    week_ago = get_week_ago()
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                try:
                    published_time = datetime(*entry.published_parsed[:6])
                    if published_time < week_ago:
                        continue  # Старше недели

                    title = entry.title
                    if not is_russian_text(title):
                        continue  # Не русский заголовок

                    link = entry.link
                    if link in sent_links:
                        continue  # Уже отправляли эту новость

                    summary = entry.get('summary', '')[:200] + '...' if entry.get('summary') else ''

                    # Извлечение изображения
                    image_url = None
                    if hasattr(entry, 'media_content') and len(entry.media_content) > 0:
                        image_url = entry.media_content[0]['url']
                    elif hasattr(entry, 'enclosures') and len(entry.enclosures) > 0:
                        image_url = entry.enclosures[0].get('href')
                    elif 'summary_detail' in entry and 'value' in entry.summary_detail:
                        soup = BeautifulSoup(entry.summary_detail.value, 'html.parser')
                        img_tag = soup.find('img')
                        if img_tag:
                            image_url = img_tag.get('src')

                    news.append({
                        'title': title,
                        'link': link,
                        'summary': summary,
                        'image': image_url,
                        'published': published_time.strftime('%Y-%m-%d %H:%M')
                    })
                except Exception as e:
                    print(f"Ошибка при обработке записи: {e}")
                    continue
        except Exception as e:
            print(f"Ошибка при парсинге фида {url}: {e}")
    return news

# === Команды бота ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я буду присылать тебе свежие русскоязычные новости про ИИ и умный дом.")

async def send_news(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    sent_links = load_sent_news()

    news = fetch_news(sent_links)
    if not news:
        await bot.send_message(chat_id=YOUR_CHAT_ID, text="Новостей за последнюю неделю не найдено.")
        return

    for article in news:
        cleaned_summary = clean_html(article['summary'])

        message_text = f"""
🗞 <b>{article['title']}</b>
🕒 {article['published']}
📝 {cleaned_summary}
🔗 <a href='{article['link']}'>Читать далее</a>
"""

        try:
            if article['image']:
                try:
                    await bot.send_photo(
                        chat_id=YOUR_CHAT_ID,
                        photo=article['image'],
                        caption=message_text,
                        parse_mode='HTML'
                    )
                except Exception as e:
                    print(f"Ошибка при отправке изображения: {e}")
                    await bot.send_message(
                        chat_id=YOUR_CHAT_ID,
                        text=message_text,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
            else:
                await bot.send_message(
                    chat_id=YOUR_CHAT_ID,
                    text=message_text,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )

            sent_links.add(article['link'])
            save_sent_news(sent_links)
            time.sleep(2)

        except telegram.error.BadRequest as e:
            print(f"Ошибка Telegram API: {e}. Пропускаем новость.")
            continue

# === Flask сервер для UptimeRobot ===
from flask import Flask

def start_web_server():
    app = Flask(__name__)

    @app.route('/')
    def home():
        return "Бот работает!", 200

    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))

# === Основная функция запуска бота ===
async def run_bot():
    if not TELEGRAM_TOKEN or not YOUR_CHAT_ID:
        print("❌ TELEGRAM_TOKEN или YOUR_CHAT_ID не заданы!")
        return

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    job_queue = application.job_queue
    job_queue.run_repeating(send_news, interval=3600, first=10)

    print("🔄 Бот запущен...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

# === Точка входа ===
if __name__ == '__main__':
    if not os.getenv("TELEGRAM_TOKEN") or not os.getenv("YOUR_CHAT_ID"):
        print("❌ TELEGRAM_TOKEN или YOUR_CHAT_ID не заданы в Secret!")
    else:
        # Запуск Flask-сервера в отдельном потоке
        web_thread = threading.Thread(target=start_web_server)
        web_thread.daemon = True
        web_thread.start()

        # Запуск Telegram-бота
        import asyncio

        asyncio.run(run_bot())
