import sqlite3
import pandas as pd
import numpy as np
from app import logger
from hashlib import sha256


IDS_FILE = 'ids.txt'
TABLE_FILE = 'economic_game.xlsx'
MINISTRY_TABLE_FILE = 'economic_game_ministers.xlsx'
COMPANY_TABLE_FILE = 'economic_game_companies.xlsx'
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
                    founder INTEGER,
                    tax_paid INTEGER,
                    fine INTEGER,
                    FOREIGN KEY (company) REFERENCES companies(company_id))""")

    cur.execute("""CREATE TABLE teachers(teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firstname VARCHAR(255) NOT NULL,
                    middlename VARCHAR(255) NOT NULL,
                    lastname VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE,
                    subject VARCHAR(255),
                    money INTEGER NOT NULL,
                    company_money INTEGER NOT NULL,
                    password VARCHAR(255) NOT NULL UNIQUE)""")

    cur.execute("""CREATE TABLE companies(company_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    revenue INTEGER NOT NULL,
                    tax INTEGER NOT NULL,
                    private INTEGER NOT NULL,
                    money INTEGER NOT NULL,
                    salary INTEGER NOT NULL)""")

    cur.execute("""CREATE TABLE services(service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                name VARCHAR(255) NOT NULL UNIQUE)""")

    # junction table
    cur.execute("""CREATE TABLE companies_to_services(company_id INTEGER, service_id INTEGER,
                        FOREIGN KEY (company_id) REFERENCES companies(company_id),
                        FOREIGN KEY (service_id) REFERENCES companies(service_id))""")

    cur.execute("""CREATE TABLE ministers(minister_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        firstname VARCHAR(255) NOT NULL,
                        middlename VARCHAR(255) NOT NULL,
                        lastname VARCHAR(255) NOT NULL,
                        email VARCHAR(255) UNIQUE,
                        cash INTEGER NOT NULL,
                        coin INTEGER NOT NULL,
                        password VARCHAR(255) NOT NULL UNIQUE)""")
    con.commit()


def sql_str(values: list):
    return ','.join(values)


def fill_in_tables(df: pd.DataFrame, ministry_df: pd.DataFrame, companies_df: pd.DataFrame) -> None:

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
                        INSERT INTO teachers(firstname, middlename, lastname, password, money, email, subject, company_money)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?) 
                        """,
                        (row['firstname'], row['middlename'], row['lastname'], hashed_pass, 0, row['email'], row['subject'], row['company_money'])
                        )

    for _, row in ministry_df.iterrows():
        hashed_pass = sha256(row['password'].encode()).hexdigest()
        cur.execute("""
                    INSERT INTO ministers(firstname, middlename, lastname, email, password, cash, coin)
                    VALUES (?, ?, ?, ?, ?, ?, ?) 
                    """, (row['firstname'], row['middlename'], row['lastname'], row['email'], hashed_pass, row['cash'], 0,))
    companies_df['founders'] = companies_df['founders'].astype('str')

    for _, row in companies_df.iterrows():
        services = [service.strip() for service in row['services'].split('|')]
        founders = [service.strip() for service in row['founders'].split('|')]
        cur.execute("""
                    INSERT INTO companies(name, revenue, tax, private, salary, money)
                    VALUES (?, ?, ?, ?, ?, 0) 
                    """, (row['name'], row['revenue'], row['tax'], row['private'], row['salary']))
        cur.execute("""SELECT company_id FROM companies WHERE name=?""", (row['name'],))
        company_id = cur.fetchone()[0]
        cur.execute("""UPDATE players SET founder=1, company=? WHERE player_id IN (%s)""" % ','.join('?' for f in founders), (company_id, *founders))
        for service in services:
            cur.execute("""INSERT OR IGNORE INTO services(name) VALUES (?)""", (service,))
            cur.execute("""SELECT service_id FROM services WHERE name=?""", (service,))
            service_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO companies_to_services(company_id, service_id) VALUES (?, ?)""",
                        (company_id, service_id))

    con.commit()


if __name__ == '__main__':
    # cur.execute("""UPDATE players SET founder=1, company=? WHERE player_id IN (9,10)""", (3,))
    # con.commit()
    ids = get_ids(from_file=IDS_FILE)
    df = assign_passwords(from_table=TABLE_FILE, to_table=table_with_passwords, passwords=ids)
    ministry_df = assign_passwords(
        from_table=MINISTRY_TABLE_FILE,
        to_table=ministry_table_with_passwords,
        passwords=ids[len(df):]
    )
    create_tables()
    fill_in_tables(df, ministry_df, pd.read_excel(COMPANY_TABLE_FILE, engine='openpyxl'))
    logger.info('database created!')
