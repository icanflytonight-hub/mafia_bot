import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8606990913:AAGYVkPLzwzajysoLbgFAyNoNTG-T6frHgs")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message()
async def echo(message: types.Message):
    await message.answer(f"Я получил сообщение! chat_id={message.chat.id}, user_id={message.from_user.id}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
