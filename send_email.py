import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv

load_dotenv('environment.env')

def email_alert(message):
    from_address = os.getenv('from_address')
    from_password = os.getenv('from_password')
    to_email = os.getenv('to_email')

    # instance of MIMEMultipart
    msg = MIMEMultipart()

    msg['From'] = from_address
    msg['To'] = to_email

    date_ = date.today()
    msg['Subject'] = f"Webcam FTP Error {date_.month}/{date_.day}"    

    # attach the body with the msg instance
    msg.attach(MIMEText(message, 'plain'))

    # creates SMTP session and start ttls
    s = smtplib.SMTP('smtp.gmail.com', 587)
    s.starttls()

    s.login(from_address, from_password) # Authentication

    text = msg.as_string() # Converts the Multipart msg into a string

    # send the mail and terminate
    s.sendmail(from_address, to_email, text)
    s.quit()

    print('email sent')
