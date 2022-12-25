import sys

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from functools import wraps
import sqlite3
import logging
import jwt

app = Flask(__name__)
CORS(app)

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
            payload = jwt.decode(token, secret, algorithms=HASH_ALGO)
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
    tax_amount = round(amount * tax)
    amount -= tax_amount
    receiver = request.get_json().get('receiver')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, teacher_id FROM teachers WHERE password=?;
                    """, (sub,))
        teacher = cur.fetchall()[0]
        cur.execute("""SELECT player_id FROM players WHERE player_id=?""", (receiver,))
        player = cur.fetchall()
        if not player:
            logger.debug(f'no player with id {receiver}')
            return jsonify(status=200, message="player does not exist")
        cur.execute("""UPDATE players SET money=money + ?, tax_paid= CASE WHEN ? > 0 THEN 1 ELSE tax_paid END WHERE player_id=?""", (amount, tax_amount, receiver))
        con.commit()
    logger.debug(f'{teacher} paid {amount} salary to player with id {receiver}')
    return jsonify(status=200, message="salary paid")


@app.route('/check-player', methods=['GET'])
def check_player():
    student_id = request.args.get('player_id')
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT fine FROM players WHERE player_id=?;
                    """, (student_id,))
        user = cur.fetchone()
        if not user:
            logger.warning(f"player {student_id} does not exist")
            return jsonify(status=NOT_FOUND, message="player does not exist"), NOT_FOUND
    return jsonify(status=200, fine=user[0])


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
                    UPDATE players SET fine=0 WHERE player_id=?;
                    """, (student_id,))
        con.commit()
    logger.info(f"charges dropped for player {student_id}")
    return jsonify(status=200, message="charges dropped")


@app.route('/withdraw', methods=['POST'])
@check_authorization
def withdraw(sub=None):
    student_id = request.get_json().get('player_id')
    amount = request.get_json().get('amount')
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
                        SELECT firstname, middlename, lastname, money, teacher_id FROM teachers WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()[0]
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a teacher"]), NOT_FOUND
    return jsonify(status=200, teacher=user)


if __name__ == '__main__':
    app.run()
