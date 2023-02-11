import sqlite3
import logging
import time
from datetime import datetime, timedelta


LOG_FILE = 'tax.log'
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger('tax_logger')

START_HOUR = 10
START_MINUTE = 30
PERIOD_IN_HOURS = 1
DELAY = 60

TEACHER_SALARY = 30
GENERAL_TAX = 0.1


def update_db():
    """set tax_paid to False, set fine for not paid tax"""
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("UPDATE players SET fine= CASE WHEN tax_paid=0 THEN fine + 10 ELSE fine END")
        cur.execute("UPDATE players SET tax_paid=0")
        cur.execute("UPDATE companies SET fine= CASE WHEN tax_paid=0 THEN fine + revenue/100*tax ELSE fine END WHERE private=1")
        cur.execute("UPDATE companies SET tax_paid=0 WHERE private=1")
        cur.execute("UPDATE companies SET revenue=profit WHERE private=1")
        cur.execute("UPDATE companies SET profit=0 WHERE private=1")
        con.commit()
    logger.info('Database updated!')


if __name__ == '__main__':
    """works only if script was started before 9:30 AM"""
    pay_time = datetime.now().replace(hour=START_HOUR, minute=START_MINUTE, second=0)

    while True:
        if datetime.now() > pay_time:
            pay_time += timedelta(hours=PERIOD_IN_HOURS)
            update_db()
            time.sleep((DELAY * 55) * PERIOD_IN_HOURS)  # optimization to reduce cpu usage
        time.sleep(DELAY)
