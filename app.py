from datetime import datetime, timedelta, timezone
from functools import wraps
import logging
import sqlite3
import sys

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import time
import os
import base64

import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS

TRUSTED_IPS = ["https://game.school1598.ru"]

app = Flask(__name__)
limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["2/second"],
        storage_uri="memory://",)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True, methods=["GET", "POST", "OPTIONS"])


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
    level=logging.DEBUG,
    datefmt='%d.%m.%Y %H:%M:%S',
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
        return f(*args, sub=payload['sub'], role=payload['role'], **kwargs)

    return wrapper

def get_auth_token(password: str, role: str) -> str:
    current_time = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {
            "sub": password,
            "role": role,
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
                    SELECT firstname, lastname, grade, money, company, player_id FROM players WHERE password=?;
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
                        SELECT firstname, lastname, cash, minister_id, field_activity FROM ministers WHERE password=?;
                        """, (password,))
            try:
                user = cur.fetchone()
                role = f"{user[4]}"
            except TypeError:
                return jsonify(status=UNAUTHORIZED, message=["wrong password"]), UNAUTHORIZED

    token = get_auth_token(password, role)
    if sys.version_info.minor < 10:
        token = token.decode('utf-8')  # noqa
    logger.info(f'{user} вошёл в аккаунт')
    return jsonify(status=200, message=user, role=role, auth_token=token)



@app.route("/company-diagram", methods=["GET"])
def get_company_diagram():
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("SELECT name, profit FROM companies WHERE private=0")
        companies = cur.fetchall()
        cur.execute("SELECT SUM(profit) FROM companies WHERE private=0")
        profit_sum = cur.fetchone()[0]

    return jsonify(status=200, companies=companies, sum=profit_sum)

@app.route("/get-telegram-photos", methods=["GET"])
def get_photos():
    path = os.listdir("telegrambot/photos")
    path.sort()
    if not path:
        return jsonify(status=NOT_FOUND, message="photos doesn't exist"), NOT_FOUND

    if len(path) > 10:
        for i in range(0, 3):
            os.remove(f"telegrambot/photos/{list(reversed(path))[i]}")
        path = os.listdir("telegrambot/photos")

    images = []
    for i, filename in enumerate(path):
        with open(f"telegrambot/photos/{filename}", "rb") as f:
            images.append(base64.b64encode(f.read()))
            images[i] = images[i].decode("utf-8")

    return jsonify(status=200, images=images)



@app.route('/player', methods=['GET'])
@check_authorization
def get_player_info(sub=None, role=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, grade, money, company, player_id, fine, tax_paid, founder FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a player"]), NOT_FOUND

    return jsonify(status=200, player=user)


@app.route('/paytax', methods=['GET'])
@check_authorization
def pay_tax(sub=None, role=None):
    TAX_AMOUNT = 10
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, money, tax_paid, fine, player_id FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
        if user[2] < TAX_AMOUNT:
            return jsonify(status=400, message="not enough money to pay tax", fine=user[4])
        if user[3]:  # if tax has already been paid
            return jsonify(status=400, message="taxes have already been paid", fine=user[4])
        cur.execute("""
                    UPDATE players SET money=money - ?, tax_paid=1 WHERE password=?;
                    """, (TAX_AMOUNT, sub))
        con.commit()

    userLog = f"{user[1]} {user[0]}, PLAYER_ID: {user[5]}"
    logger.info(f'Игрок {userLog} уплатил налоги')
    return jsonify(status=200, message="taxes are paid", fine=user[4])


@app.route('/transfer', methods=['POST'])  # {"amount": 42, "receiver": 21}
@check_authorization
def transfer_money(sub=None, role=None):
    amount = float(request.get_json().get('amount'))
    receiver = float(request.get_json().get('receiver'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()

        if role == "player":
            cur.execute("""
                        SELECT firstname, lastname, money, player_id FROM players WHERE password=?;
                        """, (sub,))
            us_role, us_id = "Игрок", "PLAYER_ID"
        elif role == "mvd" or role == "judgement" or role == "economic" or role == "socdev":
            cur.execute("""
                        SELECT firstname, lastname, money, minister_id FROM ministers WHERE password=?;
                        """, (sub,))
            us_role, us_id = "Министр", "MINISTER_ID"
        user = cur.fetchone()

        if user[2] < amount:
            return jsonify(status=400, message="not enough money to transfer")

        cur.execute("""SELECT firstname, lastname, player_id FROM players WHERE player_id=?""", (receiver,))
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
        elif role == "mvd" or role == "judgement" or role == "economic" or role == "socdev":
            cur.execute("""
                        UPDATE ministers SET money=money - ? WHERE password=?;
                        """, (amount, sub))
        con.commit()

    userLog = f"{user[1]} {user[0]}, {us_id}: {user[3]}"
    receiverLog = f"{receiver_user[1]} {receiver_user[0]}, PLAYER_ID: {receiver_user[2]}"
    logger.info(f'{us_role} {userLog} отправил {amount} тлц игроку {receiverLog}')
    return jsonify(status=200, message="money transfered")



@app.route('/pay', methods=['POST'])  # {"amount": 12, "company": "bumblebee", isTeacher: false}
@check_authorization
def pay_company(sub=None, role=None):
    amount = float(request.get_json().get('amount'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")
    receiver = request.get_json().get('company')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        if role == "player":
            cur.execute("""
                        SELECT money, player_id, firstname, lastname FROM players WHERE password=?;
                        """, (sub,))
            us_role, us_id = "Игрок", "PLAYER_ID"
        elif role == "teacher":
            cur.execute("""
                        SELECT money, teacher_id, firstname, middlename FROM teachers WHERE password=?;
                        """, (sub,))
            us_role, us_id = "Учитель", "TEACHER_ID"
        elif role == "mvd" or role == "judgement" or role == "economic" or role == "socdev":
            cur.execute("""
                        SELECT money, minister_id, firstname, lastname FROM ministers WHERE password=?;
                        """, (sub,))
            us_role, us_id = "Министр", "MINISTER_ID"
        user = cur.fetchone()
        if user[0] < amount:
            return jsonify(status=400, message="not enough money to pay")

        if role != "teacher":
            cur.execute("""SELECT name FROM companies WHERE name=?""", (receiver,))
        else:
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
        elif role == "mvd" or role == "judgement" or role == "economic" or role == "socdev":
            cur.execute("""
                        UPDATE ministers SET money=money - ? WHERE password=?;
                        """, (amount, sub))

        cur.execute("""UPDATE companies SET money=money + ? WHERE name=?""", (amount, receiver))
        cur.execute("""UPDATE companies SET profit=profit + ? WHERE name=?""", (amount, receiver))
        con.commit()

    userLog = f"{user[3]} {user[2]}, {us_id}: {user[1]}"
    logger.info(f'{us_role} {userLog} отправил {amount} тлц фирме {receiver}')
    return jsonify(status=200, message="money paid")



@app.route('/company', methods=['GET'])
@check_authorization
def get_company_info(sub=None, role=None):
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
        members = [member[2] + " " + member[3] + ", PLAYER_ID: " + str(member[0]) for member in members]

        if sub not in subs:
            return jsonify(status=401, error=f"User cannot view info of company with id {company_id}")

        cur.execute("""
                    SELECT tax_paid, fine, founder FROM players WHERE password=?
                    """, (sub,))
        player_info = cur.fetchone()

    return jsonify(status=200, company=company, members=members, playerinfo=player_info)



@app.route("/company-paytaxfine", methods=["GET"])
@check_authorization
def company_tax(sub=None, role=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT company, firstname, lastname, player_id FROM players WHERE password=? AND founder=1 AND company NOT NULL
                    """, (sub,))
        try:
            company = cur.fetchone()
            founder = f"{company[2]} {company[1]}, PLAYER_ID: {company[3]}"
            company = company[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND
        
        cur.execute("""SELECT tax_paid, tax, revenue, money, fine FROM companies WHERE company_id=? AND private=1""", (company,))
        try:
            tax_paid = cur.fetchone()
            tax_paid, tax, revenue, money, fine, = tax_paid[0], tax_paid[1], tax_paid[2], tax_paid[3], tax_paid[4]
            if tax_paid and not fine:
                return jsonify(status=400, message="debts have already been paid")
            if tax_paid:
                debt_amount = fine
            elif not fine:
                debt_amount = (revenue / 100) * tax
            else:
                debt_amount = (revenue / 100) * tax + fine
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such company"), NOT_FOUND

        if money < debt_amount:
            return jsonify(status=400, message="not enough money to pay debts", tax_amount=debt_amount)
        
        cur.execute("""
                    UPDATE companies SET money=money - ?, tax_paid=1, fine=0 WHERE company_id=?;
                    """, (debt_amount, company,))
    
    logger.info(f"Налоги фирмы {company} были уплачены её владельцем {founder}")
    return jsonify(status=200, message="taxes are paid")



@app.route('/company-salary', methods=['POST'])
@check_authorization
def pay_company_salary(sub=None, role=None):
    salary = float(request.get_json().get('salary'))
    employees = request.get_json().get('employees')

    if salary < 1:
        return jsonify(status=400, message=f"invalid salary {salary}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT company, firstname, lastname, player_id FROM players WHERE password=? AND founder=1 AND company NOT NULL
                    """, (sub,))
        try:
            company = cur.fetchone()
            founder = f"{company[2]} {company[1]}, PLAYER_ID: {company[3]}"
            company = company[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT money, tax_paid, fine FROM companies WHERE company_id=?""", (company,))
        try:
            money = cur.fetchone()
            money, tax_paid, fine, = money[0], money[1], money[2]
            if not tax_paid or fine:
                return jsonify(status=400, message="tax aren't paid")
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such company"), NOT_FOUND

        if money < salary * len(employees):
            return jsonify(status=400, message="not enough money")
        cur.execute("""
                    SELECT player_id FROM players WHERE company=?;
                    """, (company,))
        members = [member[0] for member in cur.fetchall()]
        for employee in employees:
            if not employee in members:
                return jsonify(status=400, message="there is no employee in company")

        for employee in employees:
            cur.execute("""
                        UPDATE companies SET money=money - ? WHERE company_id=?;
                        """, (salary, company,))
            cur.execute("""
                        UPDATE players SET money=money + ? WHERE player_id=?;
                        """, (salary, employee,))
        

    employeesLog = [f"{i}, " for i in employees]
    logger.info(f'Зарплаты фирмы {company} в размере {salary} тлц были выплачены сотрудникам {employeesLog} её владельцем {founder}')
    return jsonify(status=200, message="salary paid")



@app.route('/teacher', methods=['GET'])
@check_authorization
def get_teacher_info(sub=None, role=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                        SELECT firstname, middlename, money, teacher_id, subject FROM teachers WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a teacher"]), NOT_FOUND

    return jsonify(status=200, teacher=user)



@app.route('/teacher-salary', methods=['POST'])
@check_authorization
def pay_teacher_salary(sub=None, role=None):
    MAX_AMOUNT = 30
    MIN_AMOUNT = 10
    TAX = 0.1
    amount = float(request.get_json().get('amount'))
    if amount > MAX_AMOUNT or amount < MIN_AMOUNT:
        return jsonify(status=400, message=f"invalid salary")
    tax_amount = round(amount * TAX)
    receiver = float(request.get_json().get('receiver'))

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, teacher_id FROM teachers WHERE password=?;
                    """, (sub,))
        teacher = cur.fetchone()
        teacher = f"{teacher[1]} {teacher[0]}, TEACHER_ID: {teacher[2]}"

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

    logger.info(f'Учитель {teacher} выплатил зарплату: ({amount}) игроку с PLAYER_ID: {receiver}')
    return jsonify(status=200, message="salary paid")



@app.route('/minister', methods=['GET'])
@check_authorization
def get_minister_info(sub=None, role=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, grade, money, cash, minister_id, field_activity FROM ministers WHERE password=?;
                    """, (sub,))
        user = cur.fetchone()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a minister"]), NOT_FOUND

    return jsonify(status=200, minister=user)



@app.route('/debtors', methods=['GET'])
@check_authorization
def get_debtors(sub=None, role=None):
    if role != "mvd":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, player_id, tax_paid, fine FROM players WHERE fine > 1;""")
        users = cur.fetchall()

    return jsonify(status=200, debtors=users)



@app.route('/check-player', methods=['GET'])
@check_authorization
def check_player(sub=None, role=None):
    if role != "economic" and role != "judgement":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = float(request.args.get('player_id'))

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, player_id, fine, tax_paid FROM players WHERE player_id=?;
                    """, (student_id,))
        player = cur.fetchone()
        if not player:
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND

    return jsonify(status=200, player=player)



@app.route('/drop-charges', methods=['POST'])
@check_authorization
def drop_charges(sub=None, role=None):
    if role != "economic" and role != "judgement":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = float(request.get_json().get('player_id'))

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (sub,))
        minister = cur.fetchone()
        minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"

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

    logger.info(f"Штрафы и налоги аннулированы для игрока с PLAYER_ID: {student_id} министром {minister}")
    return jsonify(status=200, message="charges dropped")



@app.route('/withdraw', methods=['POST'])
@check_authorization
def withdraw(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = float(request.get_json().get('player_id'))
    amount = float(request.get_json().get('amount'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        if minister[2] < amount:
            return jsonify(status=400, message="not enough cash")
        minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[3]}"

        cur.execute("""
                    SELECT firstname, lastname, money, player_id FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND
        if amount > user[2]:
            return jsonify(status=400, message="not enough money to withdraw")

        cur.execute("""
                    UPDATE ministers SET cash=cash - ? WHERE password=?;
                    """, (amount, sub))
        cur.execute("""
                    UPDATE players SET money=money - ? WHERE player_id=?;
                    """, (amount, student_id,))

    userLog = f"{user[1]} {user[0]}, PLAYER_ID: {user[3]}"
    logger.info(f"Игрок {userLog} вывел {amount} тлц с помощью министра экономики {minister}")
    return jsonify(status=200, message="successful withdrawal")



@app.route('/deposit', methods=['POST'])
@check_authorization
def deposit(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = float(request.get_json().get('player_id'))
    amount = float(request.get_json().get('amount'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[3]}"

        cur.execute("""
                    SELECT firstname, lastname, money, player_id FROM players WHERE player_id=?;
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

    userLog = f"{user[1]} {user[0]}, PLAYER_ID: {user[3]}"
    logger.info(f"Игрок {userLog} внёс {amount} тлц с помощью министра экономики {minister}")
    return jsonify(status=200, message="successful deposit")



@app.route('/add-employee', methods=['POST'])
@check_authorization
def add_employee(sub=None, role=None):
    company = float(request.get_json().get('company'))
    founder_id = float(request.get_json().get("founder"))
    employee_id = float(request.get_json().get('employee'))

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (sub,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"
        except TypeError:
            return jsonify(status=400, message="no such minister"), 400

        cur.execute("""SELECT * FROM players WHERE company=? AND founder=1 AND player_id=?""", (company, founder_id,))
        try:
            founder = cur.fetchone()[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company IS NULL""", (employee_id,))
        employee = cur.fetchone()
        if not employee:
            return jsonify(status=400, message="no such employee OR working in another company OR is founder"), 400

        cur.execute("""UPDATE players SET company = ? WHERE player_id=?""", (company, employee_id,))
        con.commit()

    logger.info(f'Игрок c PLAYER_ID: {employee_id} был нанят в фирму {company} министром экономики {minister}')
    return jsonify(status=200, message="player was added to the company")



@app.route('/remove-employee', methods=['POST'])
@check_authorization
def remove_employee(sub=None, role=None):
    company = float(request.get_json().get('company'))
    founder_id = float(request.get_json().get("founder"))
    employee_id = float(request.get_json().get('employee'))

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (sub,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"
        except TypeError:
            return jsonify(status=400, message="no such minister"), 400

        cur.execute("""SELECT * FROM players WHERE company=? AND founder=1 AND player_id=?""", (company, founder_id,))
        try:
            founder = cur.fetchone()[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company=?""", (employee_id, company,))
        employee = cur.fetchone()
        if not employee:
            return jsonify(status=400, message="no such employee OR working in another company OR is founder"), 400

        cur.execute("""UPDATE players SET company = NULL WHERE player_id=?""", (employee_id,))
        con.commit()

    logger.info(f'Игрок с PLAYER_ID: {employee_id} был уволен из фирмы {company} министром экономики {minister}')
    return jsonify(status=200, message="player was removed from the company")



@app.route('/add-player-fine', methods=["POST"])
@check_authorization
def add_player_fine(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    player_id = float(request.get_json().get("player"))
    fine = float(request.get_json().get("fine"))
    if fine < 1:
        return jsonify(status=400, message=f"invalid fine {fine}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (sub,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"
        except TypeError:
            return jsonify(status=400, message="no such minister"), 400

        cur.execute("""
                    SELECT * FROM players WHERE player_id=?
                    """, (player_id,))
        player = cur.fetchone()
        if not player:
            return jsonify(status=NOT_FOUND, message="no such player"), NOT_FOUND

        cur.execute("""
                    UPDATE players SET fine = fine + ? WHERE player_id=?
                    """, (fine, player_id,))
    
    logger.info(f"Штраф в размере {fine} тлц был выписан игроку с PLAYER_ID: {player_id} министром экономики {minister}")
    return jsonify(status=200, message="fine issued")



@app.route('/add-firm-fine', methods=["POST"])
@check_authorization
def add_firm_fine(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    firm_id = float(request.get_json().get("firm"))
    fine = float(request.get_json().get("fine"))
    if fine < 1:
        return jsonify(status=400, message=f"invalid fine {fine}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (sub,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"
        except TypeError:
            return jsonify(status=400, message="no such minister"), 400

        cur.execute("""
                    SELECT * FROM companies WHERE company_id=?
                    """, (firm_id,))
        company = cur.fetchone()
        if not company:
            return jsonify(status=NOT_FOUND, message="no such company"), NOT_FOUND

        cur.execute("""
                    UPDATE companies SET fine = fine + ? WHERE company_id=?
                    """, (fine, firm_id,))
    
    logger.info(f"Штраф в размере {fine} тлц был выписан фирме с COMPANY_ID: {firm_id} министром экономики {minister}")
    return jsonify(status=200, message="fine issued")



@app.route('/ministry_economic_logs', methods=['GET'])
@check_authorization
def get_logs(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    length = float(request.args.get("length"))
    debug = []
    data = {}

    with open("history.log", "r") as f:
        for line in reversed(list(f)):
            if "rest_logger" in line.split(" - "):
                line = line.split(" - ")
                add = line[0] + " ----- " + line[3]
                debug.append(add)
    if length > len(debug) or length == 0:
        length = len(debug)
    for i in range(length):
        data[i] = debug[i]

    return jsonify(status=200, logs=data)



@app.route("/minister-cash", methods=["GET"])
@check_authorization
def minister_cash(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, minister_id, cash FROM ministers WHERE password=?
                    """, (sub,))
        minister = cur.fetchone()

    return jsonify(status=200, minister=minister)



@app.route('/clear_logs', methods=["GET"])
@check_authorization
def clear_logs(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"

    with open("history.log", mode="wb"):
        pass

    logger.info(f"Логи были очищены министром экономики {minister}")
    return jsonify(status=200, message="logs cleared")



if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True) # ssl_context=('cert.pem','key.pem')