import asyncio
import feedparser
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import schedule
import time
from datetime import datetime, timedelta, timezone

# --- Настройки пользователя ---
import os
TELEGRAM_TOKEN = os.getenv("7700932777:AAGuwc0w9vq3QzmKX1qQfoFSI2hTahy0RVA")
TELEGRAM_USER_ID = int(os.getenv("58354833"))

# --- RSS-ленты на русском языке ---
RSS_FEEDS = {
    'Умный Дом': 'https://news.google.com/rss/search?q=умный+дом&hl=ru&gl=RU&ceid=RU:ru',
    'ИИ': 'https://news.google.com/rss/search?q=искусственный+интеллект&hl=ru&gl=RU&ceid=RU:ru',
}

bot = telegram.Bot(token=TELEGRAM_TOKEN)

# --- Память о уже отправленных ссылках ---
sent_links = set()

# --- Основная функция ---
async def fetch_news():
    now = datetime.now(timezone.utc)
    one_week_ago = now - timedelta(days=7)
    new_articles = 0

    for category, feed_url in RSS_FEEDS.items():
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            link = entry.link
            title = entry.title
            published_parsed = entry.get('published_parsed')

            if published_parsed:
                published_datetime = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                if published_datetime >= one_week_ago:
                    if link not in sent_links:
                        # Формируем текст подписи
                        caption = f"📰 [{category}] {title}"

                        # Формируем кнопку
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("Читать статью", url=link)]
                        ])

                        # Пытаемся найти картинку
                        image_url = None
                        if 'media_content' in entry:
                            image_url = entry.media_content[0]['url']
                        elif 'media_thumbnail' in entry:
                            image_url = entry.media_thumbnail[0]['url']
                        else:
                            for l in entry.get('links', []):
                                if l.get('type', '').startswith('image/'):
                                    image_url = l.get('href')
                                    break

                        # Отправляем с фото или просто текст
                        if image_url:
                            await bot.send_photo(chat_id=TELEGRAM_USER_ID, photo=image_url, caption=caption, reply_markup=keyboard)
                        else:
                            await bot.send_message(chat_id=TELEGRAM_USER_ID, text=caption, reply_markup=keyboard)

                        sent_links.add(link)
                        new_articles += 1
                        await asyncio.sleep(1)

    if new_articles == 0:
        await bot.send_message(chat_id=TELEGRAM_USER_ID, text="❗ Новых новостей за последнюю неделю не найдено.")

# --- Планировщик ---
def schedule_job():
    asyncio.run(fetch_news())

schedule.every(30).minutes.do(schedule_job)

# Сразу проверяем при запуске
asyncio.run(fetch_news())
print("✅ Бот запущен! Новости будут проверяться каждые 30 минут.")

while True:
    schedule.run_pending()
    time.sleep(10)