import asyncio
import os
import logging

from flask import Flask, request
from aiogram import Bot, Dispatcher, types

from config import BOT_TOKEN, WEBHOOK_URL
from bot import dp, bot

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

# Устанавливаем вебхук при импорте (важно для Render)
async def set_webhook_on_startup():
    await bot.set_webhook(WEBHOOK_URL)

asyncio.run(set_webhook_on_startup())
