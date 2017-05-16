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

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.MIMEImage import MIMEImage
from urllib2 import HTTPError

sys.path.append("./yahoo_finance")
sys.path.append("./RobinhoodPython")
sys.path.append(".")

import matplotlib.pyplot as plt 
import pandas
from yahoo_finance_historical_data_extract import YFHistDataExtr

from yahoo_finance import Share, YQLResponseMalformedError

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

def save_stock_chart(ticker_symbol):
    # Delete the old bands image for this picture
    os.system("rm ./static/pictures/%s.png" % ticker_symbol)

    data_ext = YFHistDataExtr()
    data_ext.set_interval_to_retrieve(400)#in days
    data_ext.set_multiple_stock_list([str(ticker_symbol)])
    data_ext.get_hist_data_of_all_target_stocks()
    # convert the date column to date object
    data_ext.all_stock_df['Date'] =  pandas.to_datetime( data_ext.all_stock_df['Date'])
    temp_data_set = data_ext.all_stock_df.sort('Date',ascending = True ) #sort to calculate the rolling mean

    temp_data_set['20d_ma'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=5)
    temp_data_set['50d_ma'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=50)
    temp_data_set['Bol_upper'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=80) + 2* pandas.rolling_std(temp_data_set['Adj Close'], 80, min_periods=80)
    temp_data_set['Bol_lower'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=80) - 2* pandas.rolling_std(temp_data_set['Adj Close'], 80, min_periods=80)
    temp_data_set['Bol_BW'] = ((temp_data_set['Bol_upper'] - temp_data_set['Bol_lower'])/temp_data_set['20d_ma'])*100
    temp_data_set['Bol_BW_200MA'] = pandas.rolling_mean(temp_data_set['Bol_BW'], window=50)#cant get the 200 daa
    temp_data_set['Bol_BW_200MA'] = temp_data_set['Bol_BW_200MA'].fillna(method='backfill')##?? ,may not be good
    temp_data_set['20d_exma'] = pandas.ewma(temp_data_set['Adj Close'], span=20)
    temp_data_set['50d_exma'] = pandas.ewma(temp_data_set['Adj Close'], span=50)
    data_ext.all_stock_df = temp_data_set.sort('Date',ascending = False ) #revese back to original

    data_ext.all_stock_df.plot(x='Date', y=['Adj Close','20d_ma','50d_ma','Bol_upper','Bol_lower' ])

    plt.savefig('./static/pictures/%s.png' % ticker_symbol)


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
        try:
            save_stock_chart(ticker)
        except Exception:
            pass
        
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
