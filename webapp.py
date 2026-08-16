import asyncio
import os
import logging

from flask import Flask, request
from aiogram import Bot, Dispatcher, types

from config import BOT_TOKEN, WEBHOOK_URL
from bot import dp, bot  # импортируем из bot.py

app = Flask(__name__)

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = types.Update.model_validate(request.get_json(), context={"bot": bot})
        asyncio.run(dp.feed_update(bot, update))
        return "ok"
    return "Method not allowed", 405

@app.route("/")
def index():
    return "Bot is running"

if __name__ == "__main__":
    # Устанавливаем вебхук при старте
    asyncio.run(bot.set_webhook(WEBHOOK_URL))
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)