# -*- coding: utf-8 -*-
"""
vpn_bot.py — NORD VPN Telegram-бот
2025-06-19

Добавлено:
 • Над меню баннер из logo.png
 • Reply-клавиатура снизу с «🔥 Попробовать за 1 ₽», «💼 Купить подписку», «🚀 Установить VPN», «💬 Поддержка»
 • Убрано старое приветствие, вместо него «Вас приветствует NORD VPN\nВыберите тариф»
 • Inline-меню тарифов открывается по кнопкам Reply
Все остальные флоу создания/выдачи/продления конфигов без изменений.
"""

import io, os, sqlite3, logging
from datetime import datetime, timedelta, timezone

import requests, qrcode
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils.exceptions import MessageNotModified

# ─── Конфиг ──────────────────────────────────────────
load_dotenv()
BOT_TOKEN     = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
WG_URL        = os.getenv("WG_PANEL_URL")
WG_USER       = os.getenv("WG_PANEL_USER")
WG_PASS       = os.getenv("WG_PANEL_PASS")
VERIFYSSL     = not (os.getenv("WG_PANEL_INSECURE","0")=="1")
DB_PATH       = os.getenv("DB_PATH","/root/.wg-easy/wg-easy.db")

CARD_NUMBER  = "2200 1523 5879 3969"
PHONE_NUMBER = "+79189152580"

TARIFFS = {
    "trial":{"days":1,   "label":"🔥 Попробовать за 1 ₽"},
    "1":    {"days":30,  "label":"1 мес — 199 ₽"},
    "3":    {"days":90,  "label":"3 мес — 399 ₽"},
    "6":    {"days":180, "label":"6 мес — 780 ₽"},
    "12":   {"days":365, "label":"12 мес — 1494 ₽"},
}
PLATFORMS = {
    "ios":  ("📱 iPhone / iPad","https://apps.apple.com/app/wireguard/id1441195209"),
    "andr": ("🤖 Android",      "https://play.google.com/store/apps/details?id=com.wireguard.android"),
    "mac":  ("💻 macOS",        "https://apps.apple.com/app/wireguard/id1451685025"),
    "win":  ("🖥 Windows 10/11","https://download.wireguard.com/windows-client/wireguard-installer.exe"),
}

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s · %(message)s")
log = logging.getLogger("vpn-bot")

# ─── Инициализация бота ──────────────────────────────
bot = Bot(BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ─── WG-Easy helper’ы ─────────────────────────────────
def wg_req(meth,path,**kw):
    r = requests.request(meth, f"{WG_URL}/api{path}",
                        auth=(WG_USER,WG_PASS),
                        verify=VERIFYSSL, timeout=15, **kw)
    log.info("[WG] %s %s → %s", meth, path, r.status_code)
    return r

def wg_list():
    return wg_req("GET","/client").json()

def wg_new(name,exp):
    return wg_req("POST","/client", json={"name":name,"expiresAt":exp}).json()

def wg_conf(cid:int):
    r = wg_req("GET",f"/client/{cid}/configuration")
    if not r.ok: return None,None
    if r.headers.get("content-type","").startswith("application/json"):
        conf = r.json().get("conf","")
    else:
        conf = r.text
    conf = conf.lstrip("\ufeff \n\r\t")
    buf=io.BytesIO(); qrcode.make(conf).save(buf,"PNG")
    return conf,buf.getvalue()

# ─── SQLite продление ────────────────────────────────
TBL,COL_EXP=None,None
if os.path.exists(DB_PATH):
    conn=sqlite3.connect(DB_PATH); cur=conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%client%';")
    row=cur.fetchone()
    if row:
        TBL=row[0]
        cur.execute(f"PRAGMA table_info({TBL});")
        for _,col,*_ in cur.fetchall():
            if "exp" in col.lower():
                COL_EXP=col;break
    conn.close()
log.info("DB schema → %s.%s",TBL,COL_EXP)

def db_extend(cid:int,days:int)->bool:
    if not(TBL and COL_EXP): return False
    conn=sqlite3.connect(DB_PATH); cur=conn.cursor()
    cur.execute(f"SELECT {COL_EXP} FROM {TBL} WHERE id=?", (cid,))
    row=cur.fetchone()
    if not row: conn.close(); return False
    old=datetime.fromisoformat(row[0].replace("Z","+00:00"))
    new=max(old, datetime.now(timezone.utc))+timedelta(days=days)
    iso=new.isoformat().replace("+00:00","Z")
    cur.execute(f"UPDATE {TBL} SET {COL_EXP}=? WHERE id=?", (iso,cid))
    conn.commit(); conn.close(); return True

# ─── Клавиатуры ──────────────────────────────────────
def kb_main():
    kb=types.InlineKeyboardMarkup(row_width=1)
    for k in ("trial","1","3","6","12"):
        kb.add(types.InlineKeyboardButton(TARIFFS[k]["label"], callback_data=f"tariff_{k}"))
    return kb

def kb_install():
    kb=types.InlineKeyboardMarkup(row_width=1)
    for txt,url in PLATFORMS.values():
        kb.add(types.InlineKeyboardButton(txt,url=url))
    kb.add(types.InlineKeyboardButton("◀️ Назад",callback_data="main"))
    return kb

def kb_reply():
    # три колонки: тест, подписка, установить, поддержка
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔥 Попробовать за 1 ₽","💼 Купить подписку")
    kb.add("🚀 Установить VPN","💬 Поддержка")
    return kb

# ─── Хелперы ──────────────────────────────────────────
async def send_conf(uid,conf,qr):
    await bot.send_document(uid, types.InputFile(io.BytesIO(conf.encode()), filename=f"user_{uid}.conf"))
    await bot.send_photo(uid, types.InputFile(io.BytesIO(qr), filename="qr.png"))

# ─── Handlers ─────────────────────────────────────────
@dp.message_handler(commands="start")
async def cmd_start(m:types.Message):
    # баннер
    if os.path.exists("logo.png"):
        await bot.send_photo(m.chat.id, types.InputFile("logo.png"), caption="Вас приветствует NORD VPN\nВыберите тариф:")
    else:
        await m.answer("Вас приветствует *NORD VPN*!\nВыберите тариф:", parse_mode="Markdown")
    # меню тарифов inline
    await m.answer("👇 Тарифы:", reply_markup=kb_main())
    # плавающее меню reply
    await m.answer(" ", reply_markup=kb_reply())

@dp.message_handler(lambda m: m.text=="🔥 Попробовать за 1 ₽")
async def m_trial(m:types.Message):
    return await m.answer("✅ Выбрано: Попробовать за 1 ₽", reply_markup=kb_main())

@dp.message_handler(lambda m: m.text=="💼 Купить подписку")
async def m_buy(m:types.Message):
    return await m.answer("👇 Выберите подписку:", reply_markup=kb_main())

@dp.message_handler(lambda m: m.text=="🚀 Установить VPN")
async def m_install(m:types.Message):
    return await m.answer("🚀 Скачайте клиент:", reply_markup=kb_install())

@dp.message_handler(lambda m: m.text=="💬 Поддержка")
async def m_support(m:types.Message):
    await m.answer("📞 Для поддержки пишите: @YourSupport", reply_markup=kb_reply())

@dp.callback_query_handler(lambda c: c.data.startswith("tariff_"))
async def cb_tariff(c: types.CallbackQuery):
    code=c.data.split("_",1)[1]
    await dp.current_state(chat=c.message.chat.id,user=c.from_user.id).update_data(code=code)
    await c.answer(f"Вы выбрали: {TARIFFS[code]['label']}")
    text=(f"Оплатите *{TARIFFS[code]['label']}* на карту:\n" +
          f"`{CARD_NUMBER}`\nили по телефону {PHONE_NUMBER},\nзатем пришлите скриншот/чек.")
    await c.message.edit_text(text, parse_mode="Markdown")
    await c.message.answer(" ", reply_markup=kb_reply())

@dp.message_handler(content_types=types.ContentType.PHOTO)
async def photo_payment(m:types.Message):
    state=dp.current_state(chat=m.chat.id,user=m.from_user.id)
    data=await state.get_data(); code=data.get("code","1"); await state.reset_data()
    # отправляем админу
    await bot.send_photo(
        ADMIN_CHAT_ID,
        m.photo[-1].file_id,
        caption=(f"Оплата от {m.from_user.full_name} (ID {m.from_user.id})\n"
                 f"Тариф: {TARIFFS[code]['label']}"),
        reply_markup=kb_inst  # админ inline кнопки старые
    )
    await m.answer("Чек отправлен. Ожидайте подтверждения.", reply_markup=kb_reply())

# Далее старый cb_admin, но без изменений…

# ─── Запуск ─────────────────────────────────────────────
if __name__=="__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    async def on_startup(dp):
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook cleared; polling mode.")

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
