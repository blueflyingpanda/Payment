from datetime import datetime, timedelta, timezone
from functools import wraps
import logging
import sqlite3
import sys

import os
import time
import base64
# from PIL import Image
# from PIL.ExifTags import TAGS

import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS

TRUSTED_IPS = ["https://blueflyingpanda.github.io"]

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": TRUSTED_IPS}}, supports_credentials=True, methods=["GET", "POST", "OPTIONS"])


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
        # time.sleep(1)
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
    path.sort()
    if not path:
        return jsonify(status=NOT_FOUND, message="photos doesn't exist"), NOT_FOUND

    if len(path) > 15:
        for i in range(0, 6):
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
            return jsonify(status=400, message="not enough money to pay tax", fine=user[5])
        if user[3]:  # if tax has already been paid
            return jsonify(status=400, message="taxes have already been paid", fine=user[5])
        cur.execute("""
                    UPDATE players SET money=money - ?, tax_paid=1 WHERE password=?;
                    """, (TAX_AMOUNT, sub))
        con.commit()

    userLog = f"{user[1]} {user[0]}, PLAYER_ID: {user[5]}"
    logger.info(f'Игрок {userLog} уплатил налоги')
    return jsonify(status=200, message="taxes are paid", fine=user[5])


@app.route('/transfer', methods=['POST'])  # {"amount": 42, "receiver": 21}
@check_authorization
def transfer_money(sub=None, role=None):
    amount = request.get_json().get('amount')
    role = request.get_json().get('role')
    receiver = request.get_json().get('receiver')
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

        if user[3] < amount:
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
    amount = request.get_json().get('amount')
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")
    receiver = request.get_json().get('company')
    role = request.get_json().get('role')

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



@app.route("/company-paytax", methods=["GET"])
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
        
        cur.execute("""SELECT tax_paid, tax, revenue, money FROM companies WHERE company_id=?""", (company,))
        try:
            tax_paid = cur.fetchone()
            tax_paid, tax, revenue, money, = tax_paid[0], tax_paid[1], tax_paid[2], tax_paid[3]
            tax_amount = (revenue / 100) * tax
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such company"), NOT_FOUND

        
        if tax_paid:
            return jsonify(status=400, message="taxes have already been paid")
        if money < tax_amount:
            return jsonify(status=400, message="not enough money to pay taxes", tax_amount=tax_amount)
        
        cur.execute("""
                    UPDATE companies SET money=money - ?, tax_paid=1 WHERE company_id=?;
                    """, (tax_amount, company,))
    
    logger.info(f"Налоги фирмы {company} были уплачены её владельцем {founder}")
    return jsonify(status=200, message="taxes are paid")



@app.route('/company-salary', methods=['POST'])
@check_authorization
def pay_company_salary(sub=None, role=None):
    salary = request.get_json().get('salary')
    employees = request.get_json().get('employees')
    print(employees)
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

        cur.execute("""SELECT money, tax_paid FROM companies WHERE company_id=?""", (company,))
        try:
            money = cur.fetchone()
            money, tax_paid = money[0], money[1]
            if not tax_paid:
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



@app.route('/add-employee', methods=['POST'])
@check_authorization
def add_employee(sub=None, role=None):
    signature = request.get_json().get('signature')
    employee_id = request.get_json().get('employee')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        try:
            company = cur.fetchone()[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (signature,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"
        except TypeError:
            return jsonify(status=400, message="wrong minister signature"), 400

        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company IS NULL""", (employee_id,))
        employee = cur.fetchone()
        if not employee:
            return jsonify(status=400, message="no such employee OR working in another company OR is founder"), 400

        cur.execute("""UPDATE players SET company = ? WHERE player_id=?""", (company, employee_id))
        con.commit()

    logger.info(f'Игрок c PLAYER_ID: {employee_id} был нанят в фирму {company} министром экономики {minister}')
    return jsonify(status=200, message="player was added to the company")



@app.route('/remove-employee', methods=['POST'])
@check_authorization
def remove_employee(sub=None, role=None):
    signature = request.get_json().get('signature')
    employee_id = request.get_json().get('employee')

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        try:
            company = cur.fetchone()[0]
        except TypeError:
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND

        cur.execute("""SELECT firstname, lastname, minister_id FROM ministers WHERE password=?""", (signature,))
        try:
            minister = cur.fetchone()
            minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[2]}"
        except TypeError:
            return jsonify(status=400, message="wrong minister signature"), 400

        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company=?""", (employee_id, company))
        employee = cur.fetchone()
        if not employee:
            return jsonify(status=400, message="no such employee OR not working in this company OR is founder"), 400

        cur.execute("""UPDATE players SET company = NULL WHERE player_id=?""", (employee_id,))
        con.commit()

    logger.info(f'Игрок с PLAYER_ID: {employee_id} был уволен из фирмы {company} министром экономики {minister}')
    return jsonify(status=200, message="player was removed from the company")



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
    if role != "economic" or role != "judgement":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = request.args.get('player_id')

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
    if role != "economic" or role != "judgement":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = request.get_json().get('player_id')

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

    student_id = request.get_json().get('player_id')
    amount = int(request.get_json().get('amount'))
    if amount < 1:
        return jsonify(status=400, message=f"invalid amount {amount}")

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, lastname, cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        if minister[3] < amount:
            return jsonify(status=400, message="not enough cash")
        minister = f"{minister[1]} {minister[0]}, MINISTER_ID: {minister[3]}"

        cur.execute("""
                    SELECT firstname, lastname, money, player_id FROM players WHERE player_id=?;
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

    userLog = f"{user[1]} {user[0]}, PLAYER_ID: {user[3]}"
    logger.info(f"Игрок {userLog} вывел {amount} тлц с помощью министра экономики {minister}")
    return jsonify(status=200, message="successful withdrawal")



@app.route('/deposit', methods=['POST'])
@check_authorization
def deposit(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

    student_id = request.get_json().get('player_id')
    amount = int(request.get_json().get('amount'))
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



@app.route('/ministry_economic_logs', methods=['GET'])
@check_authorization
def get_logs(sub=None, role=None):
    if role != "economic":
        return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED

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



def update_db():
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("UPDATE players SET fine= CASE WHEN tax_paid=0 THEN fine + 1 ELSE fine END")
        cur.execute("UPDATE players SET tax_paid=0")
        con.commit()
    logger.info('ПЕРИОДИЧЕСКОЕ ОБНОВЛЕНИЕ БАЗЫ ДАННЫХ УСПЕШНО!')

if __name__ == '__main__':
    app.run(port=5000, debug=True)