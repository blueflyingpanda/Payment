import sqlite3
import logging
import time
import datetime

LOG_FILE = 'history.log'
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger('rest_logger')

MINISTER_SALARY = 100
TAX = 10
DELAY = 60
ERASE_HOURS = [9, 10, 11, 12, 13, 14, 15, 16]

def update_db():
    """set tax_paid to False, set fine for not paid tax"""
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("UPDATE players SET fine= CASE WHEN tax_paid=0 THEN fine + ? ELSE fine END", (TAX,))
        cur.execute("UPDATE players SET tax_paid=0")
        
        cur.execute("UPDATE companies SET fine= CASE WHEN tax_paid=0 THEN fine + revenue/100*tax ELSE fine END WHERE private=1")
        cur.execute("UPDATE companies SET tax_paid=0 WHERE private=1")
        
        cur.execute("UPDATE companies SET revenue= CASE WHEN profit < 500 THEN revenue ELSE profit END WHERE private=1")
        cur.execute("UPDATE companies SET profit=0 WHERE private=1")
        
        cur.execute("UPDATE ministers SET money=money+?", (MINISTER_SALARY,))
        
        con.commit()
    logger.info('ПЕРИОДИЧЕСКОЕ ОБНОВЛЕНИЕ БАЗЫ ДАННЫХ ПРОИЗВЕДЕНО УСПЕШНО!')

if __name__ == '__main__':
    offset = datetime.timedelta(hours=3)
    msk = datetime.timezone(offset, name='МСК')
    
    while True:
        hour = datetime.datetime.now(msk).hour
        minute = datetime.datetime.now(msk).minute
        if hour in ERASE_HOURS and minute == 0:
            update_db()
            print("Timesleepped on 60 minutes")
            time.sleep(DELAY * 55)
        else:
            print("Timesleepped on 55 seconds")
            time.sleep(55)