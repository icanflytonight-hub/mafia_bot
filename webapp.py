import asyncio
import threading
import logging
import traceback
from flask import Flask, request
from aiogram import types

from config import BOT_TOKEN
from bot import dp, bot

app = Flask(__name__)

loop = asyncio.new_event_loop()

def run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, args=(loop,), daemon=True).start()

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        data = request.get_json()
        # Проверяем, есть ли сообщение
        if "message" in data and "chat" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            future = asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id, "Тестовое сообщение от вебхука!"),
                loop
            )
            try:
                future.result(timeout=30)
                return "ok"
            except Exception as e:
                logging.error(f"Error sending test message: {e}\n{traceback.format_exc()}")
                return "error", 500
        else:
            return "ok"  # игнорируем другие типы обновлений
    return "Method not allowed", 405

@app.route("/")
def index():
    return "Bot is running"
