from datetime import datetime, timedelta, timezone
from functools import wraps
import logging
import sqlite3

import os
import sys
import time
from threading import Thread
import base64
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
# from PIL import Image
# from PIL.ExifTags import TAGS

import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

TRUSTED_IPS = ['blueflyingpanda.github.io']

UNAUTHORIZED = 401
NOT_FOUND = 404

SECRET_FILE = 'secret.txt'
HASH_ALGO = "HS256"
with open(SECRET_FILE) as fr:
    secret = fr.read().strip()

LOG_FILE = 'history.log'
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger('rest_logger')


def check_authorization(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        time.sleep(1)
        token = request.headers.get('Authorization')
        if not token:
            return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED
        try:
            payload = jwt.decode(token, secret, algorithms=[HASH_ALGO])
        except jwt.exceptions.PyJWTError as e:
            logger.warning(str(e) + " (ОШИБКА АВТОРИЗАЦИИ)")
            return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED
        return f(*args, sub=payload['sub'], **kwargs)

    return wrapper

def get_auth_token(password: str) -> str:
    current_time = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {
            "sub": password,
            "iat": current_time.timestamp(),
            "exp": (current_time + timedelta(days=1)).timestamp()
        },
        secret,
        algorithm=HASH_ALGO)
    return token

@app.route('/auth', methods=['POST'])
def authenticate_user():
    role = "player"
    password = request.form.get('password')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, grade, money, company, player_id FROM players WHERE password=?;
                    """, (password,))
        user = cur.fetchone()
        if not user:
            role = "teacher"
            cur.execute("""
                        SELECT firstname, middlename, money, teacher_id FROM teachers WHERE password=?;
                        """, (password,))
            user = cur.fetchone()
        if not user:
            cur.execute("""
                        SELECT firstname, middlename, lastname, cash, minister_id, field_activity FROM ministers WHERE password=?;
                        """, (password,))
            try:
                user = cur.fetchone()
                role = f"{user[5]}"
            except TypeError:
                return jsonify(status=UNAUTHORIZED, message=["wrong password"]), UNAUTHORIZED

    token = get_auth_token(password)
    if sys.version_info.minor < 10:
        token = token.decode('utf-8')  # noqa
    logger.debug(f'{user} вошёл в аккаунт')
    return jsonify(status=200, message=user, role=role, auth_token=token)



@app.route("/firm-diagram", methods=["GET"])
def get_firm_diagram():
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("SELECT name, profit FROM companies WHERE private=1")
        companies = cur.fetchall()
        cur.execute("SELECT SUM(profit) FROM companies")
        profit_sum = cur.fetchone()[0]

    return jsonify(status=200, companies=companies, sum=profit_sum)

@app.route("/get-telegram-photos", methods=["GET"])
def get_photos():
    path = os.listdir("telegrambot/photos")
    if not path:
        return jsonify(status=NOT_FOUND, message="photos doesn't exist"), NOT_FOUND

    if len(path) > 15:
        for i in range(5):
            os.remove(f"telegrambot/photos/{list(reversed(path))[i]}")
        path = os.listdir("telegrambot/photos")

    images = []
    count = 0
    for filename in path:
        with open(f"telegrambot/photos/{filename}", "rb") as f:
            images.append(base64.b64encode(f.read()))
            images[count] = images[count].decode("utf-8")
            count += 1

    return jsonify(status=200, images=images)



@app.route('/player', methods=['GET'])
@check_authorization
def get_player_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, grade, money, company, player_id, fine, tax_paid, founder FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a player"]), NOT_FOUND
    return jsonify(status=200, player=user)


@app.route('/paytax', methods=['POST'])
@check_authorization
def pay_tax(sub=None):
    TAX_AMOUNT = 10
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, money, tax_paid, fine, player_id FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
        if user[3] < TAX_AMOUNT:
            return jsonify(status=400, message="not enough money to pay tax", fine=user[5])
        if user[4]:  # if tax has already been paid
            return jsonify(status=400, message="taxes have already been paid", fine=user[5])
        cur.execute("""
                    UPDATE players SET money=money - ?, tax_paid=1 WHERE password=?;
                    """, (TAX_AMOUNT, sub))
        con.commit()

    userLog = f"{user[2]} {user[0]} {user[1]}, ID: {user[6]}"
    logger.debug(f'Игрок {userLog} уплатил налоги')
    return jsonify(status=200, message="taxes are paid", fine=user[5])


@app.route('/transfer', methods=['POST'])  # {"amount": 42, "receiver": 21}
@check_authorization
def transfer_money(sub=None):
    amount = request.get_json().get('amount')
    role = request.get_json().get('role')
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")
    receiver = request.get_json().get('receiver')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()

        if role == "player":
            cur.execute("""
                        SELECT firstname, middlename, lastname, money, player_id FROM players WHERE password=?;
                        """, (sub,))
        elif role == "mvd":
            cur.execute("""
                        SELECT firstname, middlename, lastname, cash, minister_id FROM ministers WHERE password=?;
                        """, (sub,))
        user = cur.fetchone()

        if user[3] < amount:
            return jsonify(status=400, message="not enough money to transfer")

        cur.execute("""SELECT firstname, middlename, lastname, player_id FROM players WHERE player_id=?""", (receiver,))
        receiver_user = cur.fetchone()
        if not receiver_user:
            return jsonify(status=400, message="receiver does not exist")

        cur.execute("""
                    UPDATE players SET money=money + ? WHERE player_id=?;
                    """, (amount, receiver))
        if role == "player":
            cur.execute("""
                        UPDATE players SET money=money - ? WHERE password=?;
                        """, (amount, sub))
        elif role == "mvd":
            cur.execute("""
                        UPDATE ministers SET cash=cash - ? WHERE password=?;
                        """, (amount, sub))
        con.commit()

    userLog = f"{user[2]} {user[0]} {user[1]}, ID: {user[4]}"
    receiverLog = f"{receiver_user[2]} {receiver_user[0]} {receiver_user[1]} ID: {receiver_user[3]}"
    logger.debug(f'Игрок {userLog} отправил сумму: ({amount}) игроку {receiverLog}')
    return jsonify(status=200, message="money transferred")



@app.route('/pay', methods=['POST'])  # {"amount": 12, "company": "bumblebee", isTeacher: false}
@check_authorization
def pay_company(sub=None):
    amount = request.get_json().get('amount')
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")
    receiver = request.get_json().get('company')
    role = request.get_json().get('role')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        if role == "player":
            cur.execute("""
                        SELECT money, player_id, firstname, middlename, lastname FROM players WHERE password=?;
                        """, (sub,))
        elif role == "teacher":
            cur.execute("""
                        SELECT money, teacher_id, firstname, middlename FROM teachers WHERE password=?;
                        """, (sub,))
        elif role == "mvd":
            cur.execute("""
                        SELECT cash, minister_id, firstname, middlename, lastname FROM ministers WHERE password=?;
                        """, (sub,))
        user = cur.fetchone()
        if user[0] < amount:
            return jsonify(status=400, message="not enough money to pay")

        if role == "player":
            cur.execute("""SELECT name FROM companies WHERE name=?""", (receiver,))
        elif role == "teacher" or role == "mvd":
            cur.execute("""SELECT name FROM companies WHERE name=? AND private=1""", (receiver,))
        company = cur.fetchone()
        if not company:
            return jsonify(status=400, message="no such company")

        if role == "player":
            cur.execute("""
                        UPDATE players SET money=money - ? WHERE password=?;
                        """, (amount, sub))
        elif role == "teacher":
            cur.execute("""
                        UPDATE teachers SET money=money - ? WHERE password=?;
                        """, (amount, sub))
        elif role == "mvd":
            cur.execute("""
                        UPDATE ministers SET cash=cash - ? WHERE password=?;
                        """, (amount, sub))

        cur.execute("""UPDATE companies SET money=money + ? WHERE name=?""", (amount, receiver))
        cur.execute("""UPDATE companies SET profit=profit + ? WHERE name=?""", (amount, receiver))
        con.commit()

    userLog = f"{user[2]} {user[3]}, ID: {user[1]}"
    receiverLog = receiver[0]
    logger.debug(f'Пользователь {user} отправил сумму: ({amount}) компании {receiverLog}')
    return jsonify(status=200, message="money paid")



@app.route('/company', methods=['GET'])
@check_authorization
def get_company_info(sub=None):
    company_id = request.args.get('company_id')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT * FROM companies WHERE company_id=?;
                    """, (company_id,))
        company = cur.fetchone()
        if not company:
            return jsonify(status=NOT_FOUND, message="company does not exist"), NOT_FOUND

        cur.execute("""
                    SELECT player_id, password, lastname, firstname FROM players WHERE company=?;
                    """, (company_id,))
        members = cur.fetchall()
        subs = {member[1] for member in members}
        members = [member[2] + " " + member[3] + " (ID: " + str(member[0]) + ")" for member in members]

        if sub not in subs:
            return jsonify(status=401, error=f"User cannot view info of company with id {company_id}")

        cur.execute("""
                    SELECT tax_paid, fine, founder FROM players WHERE password=?
                    """, (sub,))
        player_info = cur.fetchone()

    return jsonify(status=200, company=company, members=members, playerinfo=player_info)



@app.route('/company-salary', methods=['POST'])
@check_authorization
def pay_company_salary(sub=None):
    INCOME_TAX = 0.1

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT company, firstname, middlename, lastname, player_id FROM players WHERE password=? AND founder=1 AND company NOT NULL
                    """, (sub,))
        try:
            company = cur.fetchone()
            founder = f"{company[1]} {company[3]} {company[2]}, ID: {company[4]}"
            company = company[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT salary, money, tax_paid FROM companies WHERE company_id=?""", (company,))
        try:
            salary = cur.fetchone()
            salary, money, tax = salary[0], salary[1], salary[2]
            if tax:
                INCOME_TAX = 0
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such company"), NOT_FOUND

        cur.execute("""SELECT COUNT(player_id)
                    FROM players INNER JOIN companies c on c.company_id = players.company
                    WHERE company = ? """, (company,))
        employees = cur.fetchone()[0]
        if money < salary * employees:
            return jsonify(status=400, message="not enough money"), 400

        cur.execute("""
                    UPDATE players SET money = money + ? WHERE player_id IN (SELECT player_id
                    FROM players INNER JOIN companies c on c.company_id = players.company
                    WHERE company = ? )""", (round(salary * (1 - INCOME_TAX)), company))
        cur.execute("""UPDATE companies SET money = money - ? WHERE company_id=?""", (salary * employees, company))
        cur.execute("""UPDATE companies SET tax_paid=1 WHERE company_id=?""", (company,))
        con.commit()

    logger.debug(f'Зарплаты компании {company} были выплачены владельцем фирмы {founder}')
    return jsonify(status=200, message="salary paid")



@app.route('/add-employee', methods=['POST'])
@check_authorization
def add_employee(sub=None):
    signature = request.get_json().get('signature')
    employee_id = request.get_json().get('employee')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        try:
            company = cur.fetchone()[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT firstname, middlename, lastname, minister_id FROM ministers WHERE password=?""", (signature,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[2]} {minister[0]} {minister[1]}, ID: {minister[3]}"
        except TypeError:
            return jsonify(status=400, message="wrong minister signature"), 400

        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company IS NULL""", (employee_id,))
        employee = cur.fetchone()
        if not employee:
            return jsonify(status=400, message="no such employee OR working in another company OR is founder"), 400

        cur.execute("""UPDATE players SET company = ? WHERE player_id=?""", (company, employee_id))
        con.commit()

    logger.debug(f'Игрок {employee_id} был нанят в компанию {company} министром экономики {minister}')
    return jsonify(status=200, message="player was added to the company")



@app.route('/remove-employee', methods=['POST'])
@check_authorization
def remove_employee(sub=None):
    signature = request.get_json().get('signature')
    employee_id = request.get_json().get('employee')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        try:
            company = cur.fetchone()[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT firstname, middlename, lastname, minister_id FROM ministers WHERE password=?""", (signature,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[2]} {minister[0]} {minister[1]}, ID: {minister[3]}"
        except TypeError:
            return jsonify(status=400, message="wrong minister signature"), 400

        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company=?""", (employee_id, company))
        employee = cur.fetchone()
        if not employee:
            return jsonify(status=400, message="no such employee OR not working in this company OR is founder"), 400

        cur.execute("""UPDATE players SET company = NULL WHERE player_id=?""", (employee_id,))
        con.commit()

    logger.debug(f'Игрок {employee_id} был уволен из компании {company} министром экономики {minister}')
    return jsonify(status=200, message="player was removed from the company")



@app.route('/teacher', methods=['GET'])
@check_authorization
def get_teacher_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                        SELECT firstname, middlename, money, teacher_id, subject FROM teachers WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a teacher"]), NOT_FOUND

    return jsonify(status=200, teacher=user)



@app.route('/teacher-salary', methods=['POST'])  # TODO: убрать счёт предприятия у учителя (мод на бесконечные деньги, юху)
@check_authorization
def pay_teacher_salary(sub=None):
    MAX_AMOUNT = 30
    MIN_AMOUNT = 10
    TAX = 0.1
    amount = request.get_json().get('amount')
    if amount > MAX_AMOUNT or amount < MIN_AMOUNT:
        return jsonify(status=400, message=f"invalid salary")
    tax_amount = round(amount * TAX)
    receiver = request.get_json().get('receiver')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, teacher_id FROM teachers WHERE password=?;
                    """, (sub,))
        teacher = cur.fetchone()
        teacher = f"{teacher[1]} {teacher[0]}, ID: {teacher[2]}"

        cur.execute("""SELECT player_id, tax_paid FROM players WHERE player_id=?""", (receiver,))
        player = cur.fetchone()
        if not player:
            return jsonify(status=400, message="player does not exist")

        tax_was_paid = player[1]
        if not tax_was_paid:
            amount -= tax_amount

        cur.execute(
            """UPDATE players SET money=money + ?, tax_paid= CASE WHEN ? > 0 THEN 1 ELSE tax_paid END WHERE player_id=?""",
            (amount, tax_amount, receiver))
        con.commit()

    logger.debug(f'Учитель {teacher} выплатил зарплату: ({amount}) игроку с ИНН: ({receiver})')
    return jsonify(status=200, message="salary paid")



@app.route('/minister', methods=['GET'])
@check_authorization
def get_minister_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, grade, cash, minister_id, field_activity FROM ministers WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a minister"]), NOT_FOUND

    return jsonify(status=200, minister=user)


@app.route('/check-player', methods=['GET'])
@check_authorization
def check_player(sub=None):
    student_id = request.args.get('player_id')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT fine, tax_paid FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND

    return jsonify(status=200, fine=user[0], tax_paid=user[1])



@app.route('/debtors', methods=['GET'])
@check_authorization
def get_debtors(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, player_id, tax_paid, fine FROM players WHERE fine > 1;""")
        users = cur.fetchall()

    return jsonify(status=200, debtors=users)



@app.route('/drop-charges', methods=['POST'])
@check_authorization
def drop_charges(sub=None):
    student_id = request.get_json().get('player_id')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, middlename, lastname, minister_id FROM ministers WHERE password=?""", (sub,))
        minister = cur.fetchone()
        minister = f"{minister[2]} {minister[0]} {minister[1]}, ID: {minister[3]}"

        cur.execute("""
                    SELECT fine FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND

        cur.execute("""
                    UPDATE players SET fine=0, tax_paid=1 WHERE player_id=?;
                    """, (student_id,))
        con.commit()

    logger.info(f"Штрафы и налоги аннулированы для игрока {student_id} министром {minister}")
    return jsonify(status=200, message="charges dropped")



@app.route('/withdraw', methods=['POST'])
@check_authorization
def withdraw(sub=None):
    student_id = request.get_json().get('player_id')
    amount = int(request.get_json().get('amount'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        if minister[3] < amount:
            return jsonify(status=400, message="not enough cash")
        minister = f"{minister[2]} {minister[0]} {minister[1]}, ID: {minister[4]}"

        cur.execute("""
                    SELECT firstname, middlename, lastname, money, player_id FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND
        if amount > user[3]:
            return jsonify(status=400, message="not enough money to withdraw")

        cur.execute("""
                    UPDATE ministers SET cash=cash - ? WHERE password=?;
                    """, (amount, sub))
        cur.execute("""
                    UPDATE players SET money=money - ? WHERE player_id=?;
                    """, (amount, student_id,))

    logger.info(f"Игрок {user} вывел сумму: ({amount}) с помощью министра экономики {minister}")
    return jsonify(status=200, message="successful withdrawal")



@app.route('/deposit', methods=['POST'])
@check_authorization
def deposit(sub=None):
    student_id = request.get_json().get('player_id')
    amount = int(request.get_json().get('amount'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        minister = f"{minister[2]} {minister[0]} {minister[1]}, ID: {minister[4]}"

        cur.execute("""
                    SELECT firstname, middlename, lastname, money, player_id FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND

        cur.execute("""
                    UPDATE ministers SET cash=cash + ? WHERE password=?;
                    """, (amount, sub))
        cur.execute("""
                    UPDATE players SET money=money + ? WHERE player_id=?;
                    """, (amount, student_id,))

    logger.info(f"Игрок {user} внёс сумму: ({amount}) с помощью министра экономики {minister}")
    return jsonify(status=200, message="successful deposit")



@app.route('/ministry_economic_logs', methods=['GET'])
@check_authorization
def get_logs(sub=None):
    length = int(request.args.get("length"))
    debug = []
    data = {}

    with open("history.log", "r") as f:
        for line in reversed(list(f)):
            if "rest_logger" in line.split(" - "):
                line = line.split(" - ")
                add = line[0].split(",")[0] + " " + line[3]
                debug.append(add)
    if length > len(debug) or length == 0:
        length = len(debug)
    for i in range(length):
        data[i] = debug[i]

    return jsonify(status=200, logs=data)



@app.route("/minister-cash", methods=["GET"])
@check_authorization
def minister_cash(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, minister_id, cash FROM ministers WHERE password=?
                    """, (sub,))
        minister = cur.fetchone()

    return jsonify(status=200, minister=minister)



@app.route('/clear_logs', methods=["GET"])
@check_authorization
def clear_logs(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        minister = f"{minister[2]} {minister[0]} {minister[1]}, ID: {minister[3]}"

    with open("history.log", mode="wb"):
        pass

    logger.info(f"Логи были очищены министром экономики {minister}")
    return jsonify(status=200, message="logs cleared")



def update_db():
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("UPDATE players SET fine= CASE WHEN tax_paid=0 THEN fine + 1 ELSE fine END")
        cur.execute("UPDATE players SET tax_paid=0")
        con.commit()
    logger.info('ПЕРИОДИЧЕСКОЕ ОБНОВЛЕНИЕ БАЗЫ ДАННЫХ УСПЕШНО!')

if __name__ == '__main__':
    app.run(port=5000, debug=True)