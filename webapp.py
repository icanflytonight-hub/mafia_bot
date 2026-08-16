import asyncio
import threading
import logging
from flask import Flask, request
from aiogram import types

from config import BOT_TOKEN, WEBHOOK_URL
from bot import dp, bot

app = Flask(__name__)

# Создаём постоянный event loop и запускаем его в отдельном потоке
loop = asyncio.new_event_loop()

def run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, args=(loop,), daemon=True).start()

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = types.Update.model_validate(request.get_json(), context={"bot": bot})
        future = asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), loop)
        try:
            future.result(timeout=30)  # ждём завершения обработки
            return "ok"
        except Exception as e:
            logging.error(f"Error processing update: {e}")
            return "error", 500
    return "Method not allowed", 405

@app.route("/")
def index():
    return "Bot is running"

# Установка вебхука при старте (в постоянном loop)
async def set_webhook_on_startup():
    await bot.set_webhook(WEBHOOK_URL)

# Запускаем установку вебхука в нашем loop
asyncio.run_coroutine_threadsafe(set_webhook_on_startup(), loop)
