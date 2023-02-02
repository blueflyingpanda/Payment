from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor

bot = Bot(token="6158749782:AAG8pLkXKzV2ZPGbybpE8Dyo01YYYG3zN58")
dp = Dispatcher(bot)

@dp.message_handler(content_types=types.ContentType.PHOTO)
async def start_command(message: types.Message):
    file_info = await bot.get_file(message.photo[-1].file_id)
    await message.photo[-1].download(f"telegrambot/{file_info.file_path}")


if __name__ == "__main__":
    executor.start_polling(dp)