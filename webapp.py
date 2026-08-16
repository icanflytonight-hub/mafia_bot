import asyncio
import threading
import logging
import traceback
from flask import Flask, request
from aiogram import types

from config import BOT_TOKEN
from bot import dp, bot

app = Flask(__name__)

# Создаём постоянный event loop и запускаем его в фоновом потоке
loop = asyncio.new_event_loop()

def run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, args=(loop,), daemon=True).start()

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        try:
            update = types.Update.model_validate(request.get_json(), context={"bot": bot})
            future = asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), loop)
            future.result(timeout=30)
            return "ok"
        except Exception:
            logging.error("Error processing update:\n" + traceback.format_exc())
            return "error", 500
    return "Method not allowed", 405

@app.route("/")
def index():
    return "Bot is running"
