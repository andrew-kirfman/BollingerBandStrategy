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


sys.path.append("./YahooFinanceHistoricalDataExtractor")
sys.path.append("./RobinhoodPython")
sys.path.append("./HTTP_Request_Randomizer")
sys.path.append(".")



import pandas
from yahoo_finance_historical_data_extractor import YFHistoricalDataExtract
from yahoo_finance_historical_data_extractor import BadTickerFile, CannotCreateDirectory
from yahoo_finance import Share
from http.requests.proxy.requestProxy import RequestProxy
from bs4 import BeautifulSoup

import yahoo_finance
import matplotlib.pyplot as plt
import time

from send_email import send_email
from email.mime.text import MIMEText
from multiprocessing.dummy import Pool as ThreadPool
from urllib2 import HTTPError

from robinhood import RobinhoodInstance

STOCK_FILE = "./stock_list.txt"
FILTERED_STOCK_FILE = "./filtered_stock_list.txt"
SPECIAL_CHAR_LIST = ['+', '*', '-', '^', '_', '#']
NUM_THREADS = 10
LOW_VOLUME_LIMIT = 1000000

# PROXY SERVER GLOBAL VARIABLE --> Move this when you move the historical data to another module
PROXY_SERVER = None

HISTORICAL_DIRECTORY = "./historical_data"
DIVIDEND_DIRECTORY = "./dividend_data"


# Keep this one here!!!
try:
    os.makedirs("./static/pictures")
except OSError:
    pass

class BollingerBandStrategy(object):
    """
    Class to assist in determining whether or not stocks fit my dad's strategy.

    This strategy is as follows: If the stock price has dropped below the lower bollinger
    band within the last 5 days and the most recent close is above the 5-day moving average.

    """

    def __init__(self, data_storage_dir = "./historical_stock_data", ticker_file = "./stock_list.txt", \
        filtered_ticker_file = "./filtered_stock_list.txt", num_threads=10):
        """
        
        """
        
        self.stock_dir = data_storage_dir
        self.stock_ticker_file = ticker_file
        self.filtered_stock_ticker_file = filtered_ticker_file
        self.maximum_threads = num_threads
        

    def calculate_bands(self, ticker_symbol):
        # Read in the ticker data from the json history file.
        json_file = open("%s/%s.json" % (self.stock_dir, ticker_symbol))

        # Convert the read in data into a dictionary
        stock_json = json.loads(json_file.read())

        # Close the json history file
        json_file.close()

        stock_json["Date"] = pandas.to_datetime(stock_json["Date"])

        # Data has to be a pandas dataframe in order to be operated on
        stock_json["Adj Close"] = pandas.DataFrame(data=stock_json["Adj Close"])


        # Calculate 5 day moving average
        stock_json['5d_ma'] = pandas.rolling_mean(stock_json['Adj Close'][::-1], window=5)

        #stock_json["5d_ma"] = stock_json["Adj Close"].rolling(window=5, center=False).mean()

        # Calculate the lower bollinger band (this is the only one that we care about)
        stock_json["Bol_lower"] = pandas.rolling_mean(stock_json["Adj Close"].iloc[::-1], window=80) \
                - 2 * pandas.rolling_std(stock_json["Adj Close"].iloc[::-1], 80, min_periods=80)

        return stock_json['Adj Close'][::-1][0], stock_json['Bol_lower'][::-1][0], stock_json['5d_ma'][::-1][0]


    def filter_candidates(self):
        """
        Most of the stocks in the list imported from the Robinhood API are "bad"
        in that you cannot calculate the Bollinger Bands for them.  Filter the list
        in order to remove the bad candidates.
        """

        try:
            if not os.path.exists(self.stock_ticker_file):
                RobinhoodInstance.get_all_instruments(self.stock_ticker_file)
        except Exception as e:
            print "[Error]: %s" % str(e)
            raise

        stock_file = open(self.stock_ticker_file, "r")
        filtered_stock_file = open(self.filtered_stock_ticker_file, "w")

        for stock_ticker in stock_file.readlines():
            print "Testing: %s" % stock_ticker
            stock_ticker = stock_ticker.strip()
            for special_char in SPECIAL_CHAR_LIST:
                stock_ticker = stock_ticker.replace(special_char, "")

            # Get the bollinger band history along with the 5 day moving average
            try:
                close, lower_band, five_day_ma = self.calculate_bands(stock_ticker)
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


    def find_all_good_candidates(self):
        """
        First, open the list of all publicly traded stocks.  If it does 
        not exist, create it. 
        """
        
        try:
            if not os.path.exists(self.stock_ticker_file):
                RobinhoodInstance.get_all_instruments()
                filter_candidates()
        except Exception as e:
            print "[Error]: %s" % str(e)
            raise

        stock_file = open(self.filtered_stock_ticker_file, "r")

        pool = ThreadPool(self.maximum_threads)
        results = pool.map(self.test_ticker, stock_file.readlines())
        
        stock_file.close()

        return [x for x in results if x is not None]


    def test_ticker(self, stock_ticker):
        print "Testing: %s" % stock_ticker
        stock_ticker = stock_ticker.strip()
        for special_char in SPECIAL_CHAR_LIST:
            stock_ticker = stock_ticker.replace(special_char, "")

        # Get the bollinger band history along with the 5 day moving average
        try:
            close, lower_band, five_day_ma = self.calculate_bands(stock_ticker)
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

    def filter_good_candidates(self, good_candidates):
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
    #yahoo_fin = YFHistoricalDataExtract(FILTERED_STOCK_FILE, threads=100, clear_existing=False)
	
    #yahoo_fin.get_historical_data()

    bollinger_band_strategy = BollingerBandStrategy(num_threads = 100)

    good_candidates = bollinger_band_strategy.find_all_good_candidates()

    filtered_good_candidates = bollinger_band_strategy.filter_good_candidates(good_candidates)

    # Now, we build the email message to send
    send_email("Investment Aggregator Stock Update", filtered_good_candidates)


    import code; code.interact(local=locals())
















