#!/usr/bin/env python

# -------------------------------------------------------------------------- #
# Developer: Andrew Kirfman                                                  #
# Project: Financial Application                                             #
#                                                                            #
# File: ./investment_aggregator_emailer.py                                   #
# -------------------------------------------------------------------------- #

# -------------------------------------------------------------------------- #
# System Includes                                                            #
# -------------------------------------------------------------------------- #

import os
import re
import sys
import time
import datetime
import copy
import shutil
import json

# -------------------------------------------------------------------------- #
# Custom Includes                                                            #
# -------------------------------------------------------------------------- #


sys.path.append("./yahoo_finance")
sys.path.append("./RobinhoodPython")
sys.path.append("./HTTP_Request_Randomizer")
sys.path.append(".")



import pandas
from yahoo_finance_historical_data_extract import YFHistDataExtr
from yahoo_finance import Share
from http.requests.proxy.requestProxy import RequestProxy
from bs4 import BeautifulSoup

import yahoo_finance
import matplotlib.pyplot as plt
import time
import copy

from send_email import send_email
from email.mime.text import MIMEText
from multiprocessing.dummy import Pool as ThreadPool
from urllib2 import HTTPError

from robinhood import RobinhoodInstance

STOCK_FILE = "./stock_list.txt"
FILTERED_STOCK_FILE = "./filtered_stock_list.txt"
SPECIAL_CHAR_LIST = ['+', '*', '-', '^', '_', '#']
NUM_THREADS = 1
LOW_VOLUME_LIMIT = 1000000

# PROXY SERVER GLOBAL VARIABLE --> Move this when you move the historical data to another module
PROXY_SERVER = None

HISTORICAL_DIRECTORY = "./historical_data"
DIVIDEND_DIRECTORY = "./dividend_data"


# The yahoo finance library uses some files to save temp data.  Construct
# them here if they do not already exist.
try:
    os.makedirs("./data")
except OSError:
    pass

try:
    os.makedirs("./data/temp")
except OSError:
    pass

try:
    os.makedirs("./data/raw_stock_data")
except OSError:
    pass

try:
    os.makedirs("./static/pictures")
except OSError:
    pass

try:
    #os.system("rm -rf %s" % HISTORICAL_DIRECTORY)
    os.makedirs(HISTORICAL_DIRECTORY)
except OSError:
    pass

try:
    #os.system("rm -rf %s" % DIVIDEND_DIRECTORY)
    os.makedirs(DIVIDEND_DIRECTORY)
except OSError:
    pass

def read_ticker_historical(ticker_symbol):
    URL = "https://finance.yahoo.com/quote/%s/history/" % ticker_symbol
    response = None

    # Loop until you get a valid response
    while True:
        try:
            response = PROXY_SERVER.generate_proxied_request(URL, req_timeout=5)
        except Exception as e:
            print "Exception: %s %s" % (ticker_symbol, str(e))
            return

        if response is None:
            continue

        if response.__dict__['status_code'] == 200:
            break

    response_soup = BeautifulSoup(response.text, 'html5lib')

    # Find all rows in the historical data.
    response_soup = response_soup.find_all("tr")
    response_soup = response_soup[2:]

    json_history_file = open("%s/%s.json" % (HISTORICAL_DIRECTORY, ticker_symbol), "w")
    json_dividend_file = open("%s/%s_dividend.json" % (DIVIDEND_DIRECTORY, ticker_symbol), "w")

    historical_data = {
            'Date'      : [],
            'Open'      : [],
            'High'      : [],
            'Low'       : [],
            'Close'     : [],
            'Adj Close' : [],
            'Volume'    : []
            }

    dividend_data = {
            'Date'      : [],
            'Amount'    : []
            }


    for response in response_soup:
        filtered_response = response.find_all("td")

        if len(filtered_response) == 7:

            # Date
            historical_data["Date"].append(filtered_response[0].text)

            # Open
            historical_data["Open"].append(filtered_response[1].text)

            # High
            historical_data["High"].append(filtered_response[2].text)

            # Low
            historical_data["Low"].append(filtered_response[3].text)

            # Close
            historical_data["Close"].append(filtered_response[4].text)

            # Adj Close
            historical_data["Adj Close"].append(filtered_response[5].text)
        elif len(filtered_response) == 2:

            # Date
            dividend_data["Date"].append(filtered_response[0].text)

            # Dividend Amount
            amount = filtered_response[1].text.replace(" Dividend", "")
            dividend_data["Amount"].append(amount)
        else:
            continue

    json_history_file.write(json.dumps(historical_data))
    json_dividend_file.write(json.dumps(dividend_data))

    json_history_file.close()
    json_dividend_file.close()


def get_historical_data(threads = 200):
    global PROXY_SERVER

    PROXY_SERVER = RequestProxy()

    stock_file = open(FILTERED_STOCK_FILE, "r")

    candidates_to_test = []

    pool = ThreadPool(threads)

    for ticker in stock_file.readlines():
        candidates_to_test.append(ticker.strip())

    #for ticker in candidates_to_test:
    #    read_ticker_historical(ticker)

    pool.map(read_ticker_historical, candidates_to_test)










    pass

def calculate_bands(ticker_symbol):
    # Read in the ticker data from the json history file.
    json_file = open("%s/%s.json" % (HISTORICAL_DIRECTORY, ticker_symbol))

    # Convert the read in data into a dictionary
    stock_json = json_file.read()
    stock_json = json.loads(stock_json)

    stock_json["Date"] = pandas.to_datetime(stock_json["Date"])

    # Data has to be a pandas dataframe in order to be operated on
    stock_json["Adj Close"] = pandas.DataFrame(data=stock_json["Adj Close"])


    # Calculate 5 day moving average
    stock_json['5d_ma'] = pandas.rolling_mean(stock_json['Adj Close'][::-1], window=5)

    #stock_json["5d_ma"] = stock_json["Adj Close"].rolling(window=5, center=False).mean()

    # Calculate the lower bollinger band (this is the only one that we care about)
    stock_json["Bol_lower"] = pandas.rolling_mean(stock_json["Adj Close"].iloc[::-1], window=80) \
            - 2 * pandas.rolling_std(stock_json["Adj Close"].iloc[::-1], 80, min_periods=80)

    # Close the json history file
    json_file.close()

    return stock_json['Adj Close'][::-1][0], stock_json['Bol_lower'][::-1][0], stock_json['5d_ma'][::-1][0]


def filter_candidates():
    """
    Most of the stocks in the list imported from the Robinhood API are "bad"
    in that you cannot calculate the Bollinger Bands for them.  Filter the list
    in order to remove the bad candidates.
    """

    try:
        if not os.path.exists(STOCK_FILE):
            RobinhoodInstance.get_all_instruments()
    except Exception:
        # TODO: Fix the exception handing
        print "Something bad happened!"
        sys.exit(1)

    stock_file = open(STOCK_FILE, "r")
    filtered_stock_file = open(FILTERED_STOCK_FILE, "w")

    for stock_ticker in stock_file.readlines():
        print "Testing: %s" % stock_ticker
        stock_ticker = stock_ticker.strip()
        for special_char in SPECIAL_CHAR_LIST:
            stock_ticker = stock_ticker.replace(special_char, "")

        # Get the bollinger band history along with the 5 day moving average
        try:
            close, lower_band, five_day_ma = calculate_bands(stock_ticker)
        except Exception as e:
            print "Could not test ticker: %s" % stock_ticker
            print "Error: %s" % str(e)
            continue

        # If I get bad data, just continue to the next stock
        if len(close) < 5 or len(lower_band) < 5 or len(five_day_ma) < 5:
            print "Could not test ticker: %s" % stock_ticker
            continue

        print "Adding: %s" % stock_ticker
        filtered_stock_file.write("%s\n" % stock_ticker)


def find_all_good_candidates():
    # First, open the list of all publicly traded stocks.  If it does
    # not exist, create it.

    # TODO: If the file is old (i.e. more than 30 days), recreate it anyway.

    try:
        if not os.path.exists(STOCK_FILE):
            RobinhoodInstance.get_all_instruments()
            filter_candidates()
    except Exception:
        # TODO: Improve exception handling
        print "Something bad happened!"
        sys.exit(1)

    stock_file = open(FILTERED_STOCK_FILE, "r")

    good_candidates = []

    candidate_test = []

    pool = ThreadPool(NUM_THREADS)

    results = []

    """
    for ticker in stock_file.readlines():
        results.append(test_ticker(ticker))

    results = [x for x in results if x is not None]
    """

    results = pool.map(test_ticker, stock_file.readlines())

    results = [x for x in results if x is not None]

    return results


def test_ticker(stock_ticker):
    print "Testing: %s" % stock_ticker
    stock_ticker = stock_ticker.strip()
    for special_char in SPECIAL_CHAR_LIST:
        stock_ticker = stock_ticker.replace(special_char, "")

    # Get the bollinger band history along with the 5 day moving average
    try:
        close, lower_band, five_day_ma = calculate_bands(stock_ticker)
    except Exception as e:
        print "Could not test ticker: %s" % stock_ticker
        print "Error: %s" % str(e)
        return None

    # If I get bad data, just continue to the next stock
    if len(close) < 5 or len(lower_band) < 5 or len(five_day_ma) < 5:
        print "Could not test ticker: %s" % stock_ticker
        return None

    last_5_days_5_day_ma = []
    last_5_days_bb = []
    last_5_days_close = []

    for i in range(0, 5):
        last_5_days_5_day_ma.append(float(five_day_ma[i]))
        last_5_days_bb.append(float(lower_band[i]))
        last_5_days_close.append(float(close[i]))

    # Condition 1: Has the stock price at close been below the lower bollinger band
    # at market close within the last 5 days
    for i in range(0, 5):

        if last_5_days_close[i] < last_5_days_bb[i]:

            print "Hello World!"

            # Condition 2: Has the current stock price been above the 5 day moving average sometime in the last 3 days
            for i in range(0, 3):
                if last_5_days_close[i] > last_5_days_5_day_ma[i]:
                    print "BB:GoodCandidate"
                    return stock_ticker

            # If we get here, then the stock is not a candidate
            print "BB:BadCandidate"
            return None

    # Getting here also means that this was a bad candidate
    print "BB:BadCandidate"
    return None

def filter_good_candidates(good_candidates):
    """
    Filter all of the matching candidates by certain parameters.  Right now, specifically
    filter out all low volume stocks.  Low volume limit is 500,000/day.  Could be adjusted
    """

    filtered_tickers = []

    for ticker in good_candidates:
        # Filter duplicates.  This happens from time to time
        if ticker in filtered_tickers:
            continue

        print "ticker: %s" % ticker

        # Try to load the share object.  If you can't after a certain
        # number of retries, just continue and skip the ticker
        retries = 0
        failure = False
        while True:

            try:
                time.sleep(0.25)
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

        # Filter by volume
        average_volume = share_object.get_avg_daily_volume()

        # If the average volume can't be found, just continue
        try:
            int(average_volume)
        except TypeError:
            continue

        if int(average_volume) >= LOW_VOLUME_LIMIT:
            filtered_tickers.append(ticker)

        # Add any other filtering conditions here!!!

    return filtered_tickers



if __name__ == "__main__":

    # Uncomment the rm lines at the beginning of the module
    #get_historical_data(100)

    #sys.exit(1)

    #read_ticker_historical("XOM")

    good_candidates = find_all_good_candidates()

    print "Here"
    import code; code.interact(local=locals())

    #filtered_good_candidates = filter_good_candidates(good_candidates)

    # Now, we build the email message to send
    send_email("Investment Aggregator Stock Update", filtered_good_candidates)


    import code; code.interact(local=locals())
















