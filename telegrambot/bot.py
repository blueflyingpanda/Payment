from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from os import environ

def photo_bot():

    CHAT_ID = -1001758658558
    CHAT_SCHOOL_ID = -1001783533146
    # token = "6140474989:AAGKC5TMmrtRM4eFUvG60UD4IBEckx_08Cc"
    token = environ.get("BOT_TOKEN")

    bot = Bot(token)
    dp = Dispatcher(bot)


    @dp.channel_post_handler(content_types=types.ContentType.PHOTO)
    async def photo_grab(message: types.Message):
        if message.sender_chat.id == CHAT_ID:
            file_info = await bot.get_file(message.photo[-1].file_id)
            await message.photo[-1].download(destination_file=f"telegrambot/{file_info.file_path}")

    executor.start_polling(dp)