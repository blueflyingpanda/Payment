import sqlite3


con = sqlite3.connect("payments.sqlite")
cur = con.cursor()

cur.execute("""CREATE TABLE students(student_id INTEGER PRIMARY KEY AUTOINCREMENT,
            firstname VARCHAR(255) NOT NULL,
            middlename VARCHAR(255) NOT NULL,
            lastname VARCHAR(255) NOT NULL,
            grade INTEGER NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            money INTEGER NOT NULL,
            company INTEGER,
            FOREIGN KEY (company) REFERENCES companies(company_id))""")

cur.execute("""CREATE TABLE teachers(teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
            firstname VARCHAR(255) NOT NULL,
            middlename VARCHAR(255) NOT NULL,
            lastname VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE)""")

cur.execute("""CREATE TABLE companies(company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL UNIQUE,
            owner INTEGER NOT NULL,
            FOREIGN KEY (owner) REFERENCES students(student_id))""")

print('db created!')
