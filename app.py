from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(
    filename='history.log',
    filemode='w',
    format='%(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger('only_logger')


@app.route('/', methods=['GET'])
def hello_world():
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
            SELECT * FROM students;
        """)
        rows = cur.fetchall()
    return jsonify(status=200, message=rows)


@app.route('/student', methods=['POST'])
def register_student():

    lastname = request.form.get('lastname')
    firstname = request.form.get('firstname')
    middlename = request.form.get('middlename')
    email = request.form.get('email')
    grade = int(request.form.get('grade'))

    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO students(firstname, middlename, lastname, grade, email, money, company)
            VALUES (?, ?, ?, ?, ?, ?, ?) 
            """, (firstname, middlename, lastname, grade, email, 0, None)
        )
        con.commit()
    return jsonify(status=201, message="Student registered")


if __name__ == '__main__':
    app.run()
