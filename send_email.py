#!/usr/bin/env python

# ---------------------------------------------------------------------------- #
# Developer: Andrew Kirfman                                                    #
# Project: CSCE-483 Smart Greenhouse                                           #
#                                                                              #
# File: ./email.py                                                             #
# ---------------------------------------------------------------------------- #

# ---------------------------------------------------------------------------- #
# Standard Library Includes                                                    #
# ---------------------------------------------------------------------------- #

import logging
import smtplib
from email.mime.text import MIMEText

# ---------------------------------------------------------------------------- #
# Console/File Logger                                                          #
# ---------------------------------------------------------------------------- #

print_logger = logging.getLogger(__name__)
print_logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------- #
# Email Interface                                                              #
# ---------------------------------------------------------------------------- #

# This file must contain the email of the account followed by the password
# on a new line.
ADMIN_EMAIL = "./configuration/admin_email.txt"
EMAIL_LIST = "./configuration/users_to_email.txt"


def send_email(subject, message):
    # Read in the admin email information
    admin_file = open(ADMIN_EMAIL, "r")
    admin_account = admin_file.readline().strip()
    admin_password = admin_file.readline().strip()

    msg = MIMEText(str(message))

    # Read in the list of people who want these emails
    recipient_file = open(EMAIL_LIST, "r")
    recipients = recipient_file.readlines()

    for recipient in recipients:
        recipient = recipient.strip()

        # me == the sender's email address
        # you == the recipient's email address
        msg['Subject'] = subject
        msg['From'] = admin_account
        msg['To'] = str(recipient)

        # Send the message via our own SMTP server, but don't include the
        # envelope header
        s = smtplib.SMTP('smtp.gmail.com:587')
        s.ehlo()
        s.starttls()

        s.login(admin_account.replace("@gmail.com", ""), admin_password)
        s.sendmail(admin_account, [str(recipient)], msg.as_string())
        s.quit()
