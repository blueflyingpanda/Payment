import sqlite3
import pandas as pd
import numpy as np
from app import logger
from hashlib import sha256



IDS_FILE = 'ids.txt'
TABLE_FILE = 'economic_game.xlsx'
MINISTRY_TABLE_FILE = 'economic_game_ministers.xlsx'
table_name, extension = TABLE_FILE.rsplit('.', 1)
table_with_passwords = f'{table_name}_with_passwords.{extension}'
table_name, extension = MINISTRY_TABLE_FILE.rsplit('.', 1)
ministry_table_with_passwords = f'{table_name}_with_passwords.{extension}'

con = sqlite3.connect("payments.sqlite")
cur = con.cursor()


def get_ids(from_file: str) -> list[str]:
    with open(from_file) as fr:
        return [line.strip() for line in fr.readlines()]


def assign_passwords(from_table: str, to_table: str, passwords: list[str]) -> pd.DataFrame:
    df = pd.read_excel(from_table, engine='openpyxl')
    df['password'] = passwords[:len(df)]
    df['sent'] = 0
    df.sort_values(by='lastname', inplace=True)
    df.to_excel(to_table, engine='openpyxl')
    return df


def create_tables() -> None:
    cur.execute("""CREATE TABLE players(player_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firstname VARCHAR(255) NOT NULL,
                    middlename VARCHAR(255) NOT NULL,
                    lastname VARCHAR(255) NOT NULL,
                    grade INTEGER NOT NULL,
                    password VARCHAR(255) NOT NULL UNIQUE,
                    email VARCHAR(255) UNIQUE,
                    money INTEGER NOT NULL,
                    company INTEGER,
                    tax_paid INTEGER,
                    fine INTEGER,
                    FOREIGN KEY (company) REFERENCES companies(company_id))""")

    cur.execute("""CREATE TABLE teachers(teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firstname VARCHAR(255) NOT NULL,
                    middlename VARCHAR(255) NOT NULL,
                    lastname VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE,
                    money INTEGER NOT NULL,
                    password VARCHAR(255) NOT NULL UNIQUE)""")

    cur.execute("""CREATE TABLE companies(company_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    money INTEGER NOT NULL,
                    owner INTEGER NOT NULL,
                    FOREIGN KEY (owner) REFERENCES players(player_id))""")
    cur.execute("""CREATE TABLE ministers(minister_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        firstname VARCHAR(255) NOT NULL,
                        middlename VARCHAR(255) NOT NULL,
                        lastname VARCHAR(255) NOT NULL,
                        email VARCHAR(255) UNIQUE,
                        cash INTEGER NOT NULL,
                        coin INTEGER NOT NULL,
                        password VARCHAR(255) NOT NULL UNIQUE)""")
    con.commit()


def fill_in_tables(df: pd.DataFrame, ministry_df: pd.DataFrame) -> None:
    for _, row in df.iterrows():
        hashed_pass = sha256(row['password'].encode()).hexdigest()
        if row['grade'] is not np.nan:
            cur.execute("""
                        INSERT INTO players(firstname, middlename, lastname, grade, password, money, company, email, tax_paid, fine)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) 
                        """, (row['firstname'], row['middlename'], row['lastname'], row['grade'], hashed_pass, 0, None, row['email'], 0, 0)
                        )
        else:
            cur.execute("""
                        INSERT INTO teachers(firstname, middlename, lastname, password, money, email)
                        VALUES (?, ?, ?, ?, ?, ?) 
                        """,
                        (row['firstname'], row['middlename'], row['lastname'], hashed_pass, 0, row['email'])
                        )
    for _, row in ministry_df.iterrows():
        hashed_pass = sha256(row['password'].encode()).hexdigest()
        cur.execute("""
                    INSERT INTO ministers(firstname, middlename, lastname, email, password, cash, coin)
                    VALUES (?, ?, ?, ?, ?, ?, ?) 
                    """, (row['firstname'], row['middlename'], row['lastname'], row['email'], hashed_pass, row['cash'], 0,))
    con.commit()


if __name__ == '__main__':

    ids = get_ids(from_file=IDS_FILE)
    df = assign_passwords(from_table=TABLE_FILE, to_table=table_with_passwords, passwords=ids)
    ministry_df = assign_passwords(
        from_table=MINISTRY_TABLE_FILE,
        to_table=ministry_table_with_passwords,
        passwords=ids[len(df):]
    )
    create_tables()
    fill_in_tables(df, ministry_df)
    logger.info('database created!')
