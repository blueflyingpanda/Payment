import sqlite3
import logging
from telebot import types, TeleBot


logging.basicConfig(filename='history.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('only_logger')


context = {}


def ask_role(message):
    keyboard = types.InlineKeyboardMarkup()
    key_student = types.InlineKeyboardButton(text='Ученик', callback_data='student')
    keyboard.add(key_student)
    key_teacher = types.InlineKeyboardButton(text='Учитель', callback_data='teacher')
    keyboard.add(key_teacher)
    question = 'Вы кто?'
    bot.send_message(message.from_user.id, text=question, reply_markup=keyboard)


def ask_name(message):
    global context
    context[message.from_user.username] = {}
    context[message.from_user.username]['fio'] = message.text.strip().lower()
    bot.send_message(message.from_user.id, text=f"Ваше имя {message.text}")
    bot.send_message(message.from_user.id, text="Введите почту")
    bot.register_next_step_handler(message, ask_email)


def ask_email(message):
    context[message.from_user.username]['email'] = message.text.strip().lower()
    bot.send_message(message.from_user.id, text=f"Ваша почта {message.text}")
    bot.send_message(message.from_user.id, text="Введите класс")
    bot.register_next_step_handler(message, ask_grade)


def ask_grade(message):
    bot.send_message(message.from_user.id, text=f"Ваш класс {message.text}")
    try:
        f, i, o = context[message.from_user.username]['fio'].split()
        grade = int(message.text)
    except Exception as e:
        bot.send_message(message.from_user.id, text=f"Данные введены неверно\n{str(e)}")
        return
    con = sqlite3.connect("payments.sqlite")
    cur = con.cursor()
    cur.execute(f"""
        INSERT INTO students(nickname, firstname, middlename, lastname, grade, email, money, company)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?) 
    """, (message.from_user.username, i, o, f, grade, context[message.from_user.username]['email'], 0, None))
    try:
        con.commit()
    except Exception as e:
        bot.send_message(message.from_user.id, text=f"данные не сохранены\n{str(e)}")
    finally:
        con.close()
    bot.send_message(message.from_user.id, text="данные сохранены")


if __name__ == '__main__':
    with open("token.txt") as t:
        token = t.read()
    bot = TeleBot(token)


    @bot.callback_query_handler(func=lambda call: True)  # noqa
    def callback_handler(call):
        if call.data == "student":  # call.data это callback_data, которую мы указали при объявлении кнопки
            bot.send_message(call.message.chat.id, 'Создаю нового ученика')
            bot.send_message(call.message.chat.id, 'Введите фио. В Формате Иванов Иван Иванович')
            bot.register_next_step_handler(call.message, ask_name)
        else:
            bot.send_message(call.message.chat.id, 'Создаю нового учителя')


    @bot.message_handler(content_types=["text", "audio", "document", "photo", "sticker", "video", "voice", "animation"])  # noqa
    def get_messages(message):
        if message.text == "/start":
            bot.send_message(message.from_user.id, "Добро пожаловать!")
            ask_role(message)
        elif message.text == "/help":
            bot.send_message(message.from_user.id, 'твой id: ' + str(message.from_user.id) + '\nтвой ник: '
                             + str(message.from_user.username))
        else:
            bot.send_message(message.from_user.id, "Я тебя не понимаю \U0001F643\nНапиши /help.")  # TODO: logic in here


    bot.polling(none_stop=True, interval=1)
