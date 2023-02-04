from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from PIL import Image
from os import environ

CHAT_ID = -1001758658558
CHAT_SCHOOL_ID = -1001783533146
token = environ.get("BOT_TOKEN")


bot = Bot(token)
dp = Dispatcher(bot)

@dp.message_handler()
async def private_reply(message: types.Message):
    user_id = message.from_user.id

    if message.text.lower() == "привет":
        await bot.send_message(user_id, "И тебе привет ;p")
    else:
        await bot.send_message(user_id, 
"""
Бро, знаю, тебе очень хочется с кем-то пообщаться,
но я не такой хороший собеседник, которым мог бы быть, 
извини ;c

@Твой тырильщик фотографий
""")

@dp.channel_post_handler(content_types=types.ContentType.PHOTO)
async def photo_grab(message: types.Message):
    if message.sender_chat.id == CHAT_ID:
        file_info = await bot.get_file(message.photo[-1].file_id)
        await message.photo[-1].download(destination_file=f"telegrambot/{file_info.file_path}")


if __name__ == "__main__":
    executor.start_polling(dp)