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
logger = logging.getLogger('only_logger')


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
                    SELECT firstname, middlename, lastname, grade, money, company FROM players WHERE password=?;
                    """, (password,))
        user = cur.fetchall()
        if not user:
            is_teacher = True
            cur.execute("""
                        SELECT firstname, middlename, lastname, money FROM teachers WHERE password=?;
                        """, (password,))
            user = cur.fetchall()
        if not user:
            return jsonify(status=UNAUTHORIZED, message=["wrong password"]), UNAUTHORIZED
    token = get_auth_token(password)
    if sys.version_info.minor < 10:
        token = token.decode('utf-8')  # noqa
    logger.debug(f'{"teacher" if is_teacher else "player"} {user.firstname} {user.middlename} {user.lastname} logged in')
    return jsonify(status=200, message=user, teacher=is_teacher, auth_token=token)


@app.route('/debug', methods=['GET'])
def debug_database():  # TODO: remove in production
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT * FROM players;
                    """)
        players = cur.fetchall()
        cur.execute("""
                    SELECT * FROM teachers;
                    """)
        teachers = cur.fetchall()
    return jsonify(status=200, players=players, teachers=teachers)


@app.route('/player', methods=['GET'])
@check_authorization
def get_player_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, grade, money, company FROM players WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a player"]), NOT_FOUND
    return jsonify(status=200, player=user)


@app.route('/teacher', methods=['GET'])
@check_authorization
def get_teacher_info(sub=None):
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT firstname, middlename, lastname, money FROM teachers WHERE password=?;
                    """, (sub,))
        user = cur.fetchall()
    if not user:
        return jsonify(status=NOT_FOUND, message=["not a teacher"]), NOT_FOUND
    return jsonify(status=200, teacher=user)


if __name__ == '__main__':
    app.run()
