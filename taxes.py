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

FINE = 50
DELAY = 60
ERASE_HOURS = ["10:30", "11:30", "12:30", "13:30"]

def update_db():
    """set tax_paid to False, set fine for not paid tax"""
    with sqlite3.connect("payments.sqlite") as con:
        cur = con.cursor()
        cur.execute("UPDATE players SET fine= CASE WHEN tax_paid=0 THEN fine + ? ELSE fine END", (FINE,))
        cur.execute("UPDATE players SET tax_paid=0")
        
        cur.execute("UPDATE companies SET fine= CASE WHEN tax_paid=0 THEN fine + tax ELSE fine END WHERE private=1")
        cur.execute("UPDATE companies SET tax_paid=0 WHERE private=1")
        
        con.commit()
    logger.info('ПЕРИОДИЧЕСКОЕ ОБНОВЛЕНИЕ БАЗЫ ДАННЫХ ПРОИЗВЕДЕНО УСПЕШНО!')

if __name__ == '__main__':
    offset = datetime.timedelta(hours=3)
    msk = datetime.timezone(offset, name='МСК')
    
    while True:
        hour = datetime.datetime.now(msk).hour
        minute = datetime.datetime.now(msk).minute
        timenow = f"{hour}:{minute}"
        if timenow in ERASE_HOURS:
            update_db()
            print("Timesleepped on 55 minutes")
            time.sleep(DELAY * 55)
        else:
            print("Timesleepped on 55 seconds")
            time.sleep(55)