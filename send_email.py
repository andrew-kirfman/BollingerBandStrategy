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

import os
import logging
import smtplib
import time
import sys
import json

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.MIMEImage import MIMEImage
from urllib2 import HTTPError

sys.path.append("./RobinhoodPython")
sys.path.append(".")

import matplotlib.pyplot as plt
import pandas

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

try:
    os.makedirs("./static")
except Exception:
    pass

try:
    os.makedirs("./static/pictures")
except Exception:
    pass

def save_stock_chart(ticker_symbol, data_dir = "./historical_stock_data"):
    # Delete the old bands image for this picture
    os.system("rm ./static/pictures/%s.png" % ticker_symbol)

    data_file = open("%s/%s.json" % (data_dir, ticker_symbol), "r")
    stock_json = json.loads(data_file.read())

    # Close the json history file
    data_file.close()

    stock_json["Date"] = pandas.to_datetime(stock_json["Date"])

    # Data has to be a pandas dataframe in order to be operated on
    stock_json["Adj Close"] = pandas.DataFrame(data=stock_json["Adj Close"])

    # Calculate 5 day moving average
    stock_json['5d_ma'] = pandas.rolling_mean(stock_json['Adj Close'][::-1], window=5)

    #stock_json["5d_ma"] = stock_json["Adj Close"].rolling(window=5, center=False).mean()

    # Calculate the lower bollinger band (this is the only one that we care about)
    stock_json["Bol_lower"] = pandas.rolling_mean(stock_json["Adj Close"].iloc[::-1], window=80) \
            - 2 * pandas.rolling_std(stock_json["Adj Close"].iloc[::-1], 80, min_periods=80)

    stock_json["Bol_upper"] = pandas.rolling_mean(stock_json["Adj Close"].iloc[::-1], window=80) \
            + 2 * pandas.rolling_std(stock_json["Adj Close"].iloc[::-1], 80, min_periods=80)

    stock_json['50d_ma'] = pandas.rolling_mean(stock_json['Adj Close'][::-1], window=50)
    
    fig = plt.figure(figsize=(14,7))
    
    ax = fig.add_subplot(111)

    ax.plot(stock_json["Date"], list(stock_json["Adj Close"].values.flatten()))
    ax.plot(stock_json["Date"], stock_json["5d_ma"][::-1])
    ax.plot(stock_json["Date"], stock_json["Bol_lower"][::-1])
    ax.plot(stock_json["Date"], stock_json["Bol_upper"][::-1])
    ax.plot(stock_json["Date"], stock_json["50d_ma"][::-1])

    fig.autofmt_xdate()

    plt.savefig('./static/pictures/%s.png' % ticker_symbol)

    plt.close("All")


def send_email(subject, valid_tickers):
    # Read in the admin email information
    admin_file = open(ADMIN_EMAIL, "r")
    admin_account = admin_file.readline().strip()
    admin_password = admin_file.readline().strip()

    # Read in the list of people who want these emails
    recipient_file = open(EMAIL_LIST, "r")
    recipients = recipient_file.readlines()

    # Build the message to send to each user
    html = "<head>"
    html = html + "<h2>Bollinger Band Candidates</h2>"
    html = html + "<br>"

    figure_counter = 1

    for ticker in valid_tickers:
        print "Ticker: %s" % ticker

        # Try to load the share object.  If you can't after a certain
        # number of retries, just continue and skip the ticker
        retries = 0
        failure = False
        while True:

            try:
                time.sleep(1)
                share_object = Share(ticker)
            except Exception:
                if retries > 5:
                    failure = True
                    break

                retries = retries + 1
                continue

            break

        if failure is True:
            continue

        # Try to save the image
        retries = 0
        failures = False
        while True:

            try:
                save_stock_chart(ticker)
            except Exception:
                if retries > 5:
                    failure = True
                    break

                retries = retries + 1
                continue

            break

        html = html + "<b>Ticker Symbol: %s</b>" % ticker
        html = html + "<ul>"
        html = html + "    <li>Price: %s</li>" % share_object.get_price()
        html = html + "    <li>Market Cap: %s</li>" % share_object.get_market_cap()
        html = html + "    <li>Dividend Yield: %s</li>" % share_object.get_dividend_yield()
        html = html + "    <li>P/E Ratio: %s</li>" % share_object.get_price_earnings_ratio()
        html = html + "    <li>EPS Estimate: %s</li>" % share_object.get_EPS_estimate_next_quarter()
        html = html + "    <li>Average Volume: %s</li>" % share_object.get_avg_daily_volume()
        html = html + "</ul>"
        html = html + "<br>"
        html = html + "<ul>"
        html = html + "    <li>Year High: %s</li>" % share_object.get_year_high()
        html = html + "    <li>Year Low: %s</li>" % share_object.get_year_low()
        html = html + "</ul>"
        html = html + "<b>Stock Chart</b>"

        html = html + '<img src="cid:image%s" style="height: 600px;">' % figure_counter


        html = html + "<br><br>"

        figure_counter = figure_counter + 1


    html = html + "</head>"

    for recipient in recipients:
        recipient = recipient.strip()

        msgRoot = MIMEMultipart('related')
        msgRoot['Subject'] = subject
        msgRoot['From'] = admin_account
        msgRoot['To'] = str(recipient)

        msgAlternative = MIMEMultipart('alternative')
        msgRoot.attach(msgAlternative)


        msgAlternative.attach(MIMEText(html, 'html'))

        print html
        
        import code; code.interact(local=locals())

        # Try to attach an image
        figure_counter = 1
        for ticker in valid_tickers:
            try:
                fp = open("./static/pictures/%s.png" % ticker, "rb")
            except Exception:
                figure_counter = figure_counter + 1
                continue

            msgImage = MIMEImage(fp.read())

            msgImage.add_header("Content-ID", "<image%s>" % figure_counter)
            msgRoot.attach(msgImage)

            figure_counter = figure_counter + 1

            fp.close()

        # Send the message via our own SMTP server, but don't include the
        # envelope header
        s = smtplib.SMTP('smtp.gmail.com:587')
        s.ehlo()
        s.starttls()

        s.login(admin_account.replace("@gmail.com", ""), admin_password)
        s.sendmail(admin_account, [str(recipient)], msgRoot.as_string())
        s.quit()
