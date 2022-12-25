import smtplib
from email.message import EmailMessage
import ssl
import pandas as pd
import numpy as np
from app import logger
from create_db import table_with_passwords, ministry_table_with_passwords


CLIENT_URL = 'https://blueflyingpanda.github.io/PaymentSite/'
SUBJECT = 'The Economic Game Registration'
REGISTRATION_TEMPLATE = f"""
Welcome to The Economic Game!

You received this message, because you were registered to the game.
Go to your account by following the link: {CLIENT_URL}

Your passcode is %s
Tell your passcode no-one!
"""
SIGNATURE = f"""
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For support reply to this message

Best Regards,
The Economic Game Development Team
"""


class MailSender:
    port = 465
    context = ssl.create_default_context()

    def __init__(self, credentials_file: str, signature: str = ''):

        with open(credentials_file, "r") as f:
            file = f.readlines()
            self.user = file[0].strip()
            self.password = file[1].strip()

        self.signature = signature

    def send_mail(self, to_receiver: str, subject: str = '', text: str = ''):
        message = EmailMessage()
        message.set_content(f"{text}\n\n{self.signature}")

        message['Subject'] = subject
        message['From'] = self.user
        message['To'] = to_receiver

        with smtplib.SMTP_SSL("smtp.mail.ru", self.port, context=self.context) as server:
            server.login(self.user, self.password)
            server.send_message(message)

    def send_mails(self, df: pd.DataFrame) -> int:
        count = 0
        for i, row in df.iterrows():
            if row['email'] is not np.nan and not row['sent']:
                self.send_mail(to_receiver=row['email'], subject=SUBJECT, text=REGISTRATION_TEMPLATE % (row['password'],))
                df.at[i, 'sent'] = 1
                count += 1
                logger.debug(f'Email sent to {row["lastname"]} {row["firstname"]} {row["middlename"]} ({row["email"]})')
        return count


if __name__ == '__main__':
    ms = MailSender('credentials.txt', signature=SIGNATURE)
    df = pd.read_excel(table_with_passwords, engine='openpyxl')
    count = ms.send_mails(df)
    df.to_excel(table_with_passwords, engine='openpyxl')
    ministry_df = pd.read_excel(ministry_table_with_passwords, engine='openpyxl')
    count += ms.send_mails(ministry_df)
    ministry_df.to_excel(ministry_table_with_passwords, engine='openpyxl')
    logger.info(f"{count} emails were sent")
