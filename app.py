import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from functools import wraps

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
        token = request.headers.get('Authorization')
        if not token:
            return jsonify(status=UNAUTHORIZED, message=["unauthorized"]), UNAUTHORIZED
        try:
            payload = jwt.decode(token, secret, algorithms=[HASH_ALGO])
        except jwt.exceptions.PyJWTError as e:
            logger.warning(str(e))
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
    is_teacher = False
    password = request.form.get('password')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, grade, money, company, player_id FROM players WHERE password=?;
                    """, (password,))
        user = cur.fetchall()
        if not user:
            is_teacher = True
            cur.execute("""
                        SELECT firstname, middlename, lastname, money, teacher_id FROM teachers WHERE password=?;
                        """, (password,))
            user = cur.fetchall()
        if not user:
            is_teacher = None
            cur.execute("""
                        SELECT firstname, middlename, lastname, cash, coin, minister_id FROM ministers WHERE password=?;
                        """, (password,))
            user = cur.fetchall()
        if not user:
            return jsonify(status=UNAUTHORIZED, message=["wrong password"]), UNAUTHORIZED
        user = user[0]
    token = get_auth_token(password)
    if sys.version_info.minor < 10:
        token = token.decode('utf-8')  # noqa
    logger.debug(f'{user} logged in')
    return jsonify(status=200, message=user, teacher=is_teacher, auth_token=token)


@app.route('/paytax', methods=['POST'])
@check_authorization
def pay_tax(sub=None):
    TAX_AMOUNT = 10
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, money, tax_paid, fine, player_id FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()[0]
        if user[3] < TAX_AMOUNT:
            logger.debug(f'{user} has not enough money to pay tax')
            return jsonify(status=400, message="not enough money to pay tax", fine=user[5])
        if user[4]:  # if tax has already been paid
            return jsonify(status=400, message="taxes have already been paid", fine=user[5])
        cur.execute("""
                    UPDATE players SET money=money - ?, tax_paid=1 WHERE password=?;
                    """, (TAX_AMOUNT, sub))
        con.commit()
    logger.debug(f'{user} paid taxes')
    return jsonify(status=200, message="taxes are paid", fine=user[5])


@app.route('/transfer', methods=['POST'])  # {"amount": 42, "receiver": 21}
@check_authorization
def transfer_money(sub=None):
    amount = request.get_json().get('amount')
    if amount < 1:
        logger.debug(f'invalid amount {amount}')
        return jsonify(status=400, message=f"invalid amount {amount}")
    receiver = request.get_json().get('receiver')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, money, player_id FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()[0]
        if user[3] < amount:
            logger.debug(f'{user} has not enough money to transfer: {user[3]} < {amount}')
            return jsonify(status=400, message="not enough money to transfer")
        cur.execute("""SELECT player_id FROM players WHERE player_id=?""", (receiver,))
        receiver_user = cur.fetchall()
        if not receiver_user:
            logger.debug(f'user with id {receiver} does not exist')
            return jsonify(status=400, message="receiver does not exist")
        cur.execute("""
                    UPDATE players SET money=money + ? WHERE player_id=?;
                    """, (amount, receiver))
        cur.execute("""
                    UPDATE players SET money=money - ? WHERE password=?;
                    """, (amount, sub))
        con.commit()
    logger.debug(f'{user} transfered {amount} money to user with id {receiver}')
    return jsonify(status=200, message="money transferred")


@app.route('/pay', methods=['POST'])  # {"amount": 12, "company": "bumblebee", isTeacher: false}
@check_authorization
def pay_company(sub=None):
    amount = request.get_json().get('amount')
    if amount < 1:
        logger.debug(f'invalid amount {amount}')
        return jsonify(status=400, message=f"invalid amount {amount}")
    receiver = request.get_json().get('company')
    is_teacher = request.get_json().get('isTeacher')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        if is_teacher:
            cur.execute("""
                        SELECT firstname, middlename, lastname, money, teacher_id FROM teachers WHERE password=?;
                        """, (sub,))
        else:
            cur.execute("""
                        SELECT firstname, middlename, lastname, money, player_id FROM players WHERE password=?;
                        """, (sub,))
        user = cur.fetchall()[0]
        if user[3] < amount:
            logger.debug(f'{user} has not enough money to pay: {user[3]} < {amount}')
            return jsonify(status=400, message="not enough money to pay")
        if is_teacher:
            cur.execute("""SELECT name FROM companies WHERE name=? AND private=1""", (receiver,))
            company = cur.fetchall()
            if not company:
                return jsonify(status=400, message="no such company")
            cur.execute("""
                        UPDATE teachers SET money=money - ? WHERE password=?;
                        """, (amount, sub))
        else:
            cur.execute("""SELECT name FROM companies WHERE name=?""", (receiver,))
            company = cur.fetchall()
            if not company:
                return jsonify(status=400, message="no such company")
            cur.execute("""
                        UPDATE players SET money=money - ? WHERE password=?;
                        """, (amount, sub))
        cur.execute("""UPDATE companies SET money=money + ? WHERE name=?""", (amount, receiver))
        con.commit()
    logger.debug(f'{user} paid {amount} money to company {receiver}')
    return jsonify(status=200, message="money paid")


@app.route('/teacher-salary', methods=['POST'])  # {"amount": 12, "receiver": 9}
@check_authorization
def pay_teacher_salary(sub=None):
    MAX_AMOUNT = 30
    tax = 0.1
    amount = request.get_json().get('amount')
    if amount > MAX_AMOUNT:
        logger.debug(f'max salary {MAX_AMOUNT} < {amount}')
        return jsonify(status=400, message=f"max salary is {MAX_AMOUNT}")
    if amount < 1:
        logger.debug(f'invalid amount {amount}')
        return jsonify(status=400, message=f"invalid amount {amount}")
    tax_amount = round(amount * tax)
    receiver = request.get_json().get('receiver')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, teacher_id, company_money FROM teachers WHERE password=?;
                    """, (sub,))
        teacher = cur.fetchone()
        if teacher[4] < amount:
            logger.debug(f'not enough money for teacher to pay salary {teacher[4]} < {amount}')
            return jsonify(status=400, message=f"not enough money for teacher to pay salary", company_money=teacher[4])
        cur.execute("""SELECT player_id, tax_paid FROM players WHERE player_id=?""", (receiver,))
        player = cur.fetchall()
        if not player:
            logger.debug(f'no player with id {receiver}')
            return jsonify(status=200, message="player does not exist")
        tax_was_paid = player[0][1]
        if not tax_was_paid:
            amount -= tax_amount
        cur.execute(
            """UPDATE players SET money=money + ?, tax_paid= CASE WHEN ? > 0 THEN 1 ELSE tax_paid END WHERE player_id=?""",
            (amount, tax_amount, receiver))
        cur.execute(
            """UPDATE teachers SET company_money=company_money - ?, password=?""",
            (amount, sub))
        con.commit()
    logger.debug(f'{teacher} paid {amount} salary to player with id {receiver}')
    return jsonify(status=200, message="salary paid")


@app.route('/company-salary', methods=['POST'])
@check_authorization
def pay_company_salary(sub=None):
    INCOME_TAX = 0.1
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        founder = cur.fetchone()
        if not founder:
            logger.warning(f'no such founder {sub}')
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND
        company = founder[0]
        cur.execute("""SELECT salary, money FROM companies WHERE company_id=?""", (company,))
        salary = cur.fetchone()
        if not salary:
            logger.warning(f'no such company {company}')
            return jsonify(status=NOT_FOUND, message="no such company"), NOT_FOUND
        salary, money = salary[0], salary[1]
        cur.execute("""SELECT COUNT(player_id)
                    FROM players INNER JOIN companies c on c.company_id = players.company
                    WHERE company = ? """, (company,))
        employees = cur.fetchone()[0]
        if money < salary * employees:
            logger.warning(f'not enough money to pay salary in company {company}: {money} < {salary * employees}')
            return jsonify(status=400, message="not enough money"), 400
        cur.execute("""
                    UPDATE players SET money = money + ? WHERE player_id IN (SELECT player_id
                    FROM players INNER JOIN companies c on c.company_id = players.company
                    WHERE company = ? )""", (round(salary * (1 - INCOME_TAX)), company))
        cur.execute("""UPDATE companies SET money = money - ? WHERE company_id=?""", (salary * employees, company))
        con.commit()
    logger.debug(f'{company} paid salary init by {sub}')
    return jsonify(status=200, message="salary paid")


@app.route('/add-employee', methods=['POST'])  # {"signature": "36deacb32d93988f9b8a0cd06b56af05144b6a17eb40f049d7ca1acef8a4e055", "employee": 12}
@check_authorization
def add_employee(sub=None):
    signature = request.get_json().get('signature')
    employee_id = request.get_json().get('employee')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        founder = cur.fetchone()
        if not founder:
            logger.warning(f'no such founder {sub}')
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND
        company = founder[0]
        cur.execute("""SELECT minister_id FROM ministers WHERE password=?""", (signature,))
        minister = cur.fetchone()
        if not minister:
            logger.warning(f'wrong minister signature')
            return jsonify(status=400, message="wrong minister signature"), 400
        minister = minister[0]
        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company IS NULL""", (employee_id,))
        employee = cur.fetchone()
        if not employee:
            logger.warning(f'no such employee OR working in another company OR is founder - id {employee_id}')
            return jsonify(status=400, message="no such employee OR working in another company OR is founder"), 400
        cur.execute("""UPDATE players SET company = ? WHERE player_id=?""", (company, employee_id))
        con.commit()
    logger.debug(f'player {employee_id} was added to the company {company} by {sub} - minister {minister}')
    return jsonify(status=200, message="player was added to the company")


@app.route('/remove-employee', methods=['POST'])  # {"signature": "36deacb32d93988f9b8a0cd06b56af05144b6a17eb40f049d7ca1acef8a4e055", "employee": 12}
@check_authorization
def remove_employee(sub=None):
    signature = request.get_json().get('signature')
    employee_id = request.get_json().get('employee')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT company FROM players WHERE password=? AND founder=1 AND company NOT NULL""", (sub,))
        founder = cur.fetchone()
        if not founder:
            logger.warning(f'no such founder {sub}')
            return jsonify(status=NOT_FOUND, message="no such founder"), NOT_FOUND
        company = founder[0]
        cur.execute("""SELECT minister_id FROM ministers WHERE password=?""", (signature,))
        minister = cur.fetchone()
        if not minister:
            logger.warning(f'wrong minister signature')
            return jsonify(status=400, message="wrong minister signature"), 400
        minister = minister[0]
        cur.execute("""SELECT player_id FROM players WHERE player_id=? AND founder IS NULL AND company=?""", (employee_id, company))
        employee = cur.fetchone()
        if not employee:
            logger.warning(f'no such employee OR not working in this company OR is founder - id {employee_id}')
            return jsonify(status=400, message="no such employee OR not working in this company OR is founder"), 400
        cur.execute("""UPDATE players SET company = NULL WHERE player_id=?""", (employee_id,))
        con.commit()
    logger.debug(f'player {employee_id} was removed from the company {company} by {sub} - minister {minister}')
    return jsonify(status=200, message="player was removed from the company")


@app.route('/check-player', methods=['GET'])
def check_player():
    student_id = request.args.get('player_id')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT fine, tax_paid FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            logger.warning(f"player {student_id} does not exist")
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND
    return jsonify(status=200, fine=user[0], tax_paid=user[1])


@app.route('/debtors', methods=['GET'])
def get_debtors():
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""SELECT player_id, tax_paid, fine FROM players WHERE fine > 1;""")
        users = cur.fetchall()
    return jsonify(status=200, debtors=users)


@app.route('/drop-charges', methods=['POST'])
def drop_charges():
    student_id = request.get_json().get('player_id')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT fine FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            logger.warning(f"player {student_id} does not exist")
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND
        cur.execute("""
                    UPDATE players SET fine=0, tax_paid=1 WHERE player_id=?;
                    """, (student_id,))
        con.commit()
    logger.info(f"charges dropped for player {student_id}")
    return jsonify(status=200, message="charges dropped")


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
            logger.warning(f"company {company_id} does not exist")
            return jsonify(status=NOT_FOUND, message="company does not exist"), NOT_FOUND
        cur.execute("""
                    SELECT player_id, password FROM players WHERE company=?;
                    """, (company_id,))
        members = cur.fetchall()
        subs = {member[1] for member in members}
        members = [member[0] for member in members]
        if sub not in subs:
            return jsonify(status=401, error=f"User cannot view info of company with id {company_id}")
    return jsonify(status=200, company=company, members=members)


@app.route('/withdraw', methods=['POST'])
@check_authorization
def withdraw(sub=None):
    student_id = request.get_json().get('player_id')
    amount = request.get_json().get('amount')
    if amount < 1:
        logger.debug(f'invalid amount {amount}')
        return jsonify(status=400, message=f"invalid amount {amount}")
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT money, player_id FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            logger.warning(f"player {student_id} does not exist")
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND
        if amount > user[0]:
            logger.debug(f'{user} has not enough money to withdraw: {user[0]} < {amount}')
            return jsonify(status=400, message="not enough money to withdraw")

        cur.execute("""
                    SELECT cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        if not minister:
            logger.warning(f"minister does not exist")
            return jsonify(status=NOT_FOUND, message="minister does not exist"), NOT_FOUND
        if minister[0] < amount:
            logger.debug(f'minister has not enough cash: {minister[0]} < {amount}')
            return jsonify(status=400, message="not enough cash")
        cur.execute("""
                    UPDATE ministers SET cash=cash - ?, coin=coin + ? WHERE password=?;
                    """, (amount, amount, sub))
        cur.execute("""
                    UPDATE players SET money=money - ? WHERE player_id=?;
                    """, (amount, student_id,))
    logger.info(f"{user} withdrew {amount}")
    return jsonify(status=200, message="successful withdrawal")


@app.route('/deposit', methods=['POST'])
@check_authorization
def deposit(sub=None):
    student_id = request.get_json().get('player_id')
    amount = request.get_json().get('amount')
    if amount < 1:
        logger.debug(f'invalid amount {amount}')
        return jsonify(status=400, message=f"invalid amount {amount}")
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT money, player_id FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            logger.warning(f"player {student_id} does not exist")
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND

        cur.execute("""
                    SELECT cash, minister_id FROM ministers WHERE password=?;
                    """, (sub,))
        minister = cur.fetchone()
        if not minister:
            logger.warning(f"minister does not exist")
            return jsonify(status=NOT_FOUND, message="minister does not exist"), NOT_FOUND

        cur.execute("""
                    UPDATE ministers SET cash=cash + ?, coin=coin - ? WHERE password=?;
                    """, (amount, amount, sub))
        cur.execute("""
                    UPDATE players SET money=money + ? WHERE player_id=?;
                    """, (amount, student_id,))
    logger.info(f"{user} deposited {amount}")
    return jsonify(status=200, message="successful deposit")


@app.route('/player', methods=['GET'])
@check_authorization
def get_player_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, grade, money, company, player_id, fine, founder, player_id FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()[0]
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a player"]), NOT_FOUND
    return jsonify(status=200, player=user)


@app.route('/teacher', methods=['GET'])
@check_authorization
def get_teacher_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                        SELECT firstname, middlename, lastname, money, teacher_id, subject, company_money FROM teachers WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()[0]
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a teacher"]), NOT_FOUND
    return jsonify(status=200, teacher=user)


if __name__ == '__main__':
    app.run()
