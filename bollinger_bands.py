#!/usr/bin/env python

# -------------------------------------------------------------------------- #
# Developer: Andrew Kirfman                                                  #
# Project: Financial Application                                             #
#                                                                            #
# File: ./bollinger_bands.py                                                 #
# -------------------------------------------------------------------------- #

import os, re, sys, time, datetime, copy, shutil

sys.path.append("./yahoo_finance")
sys.path.append("./RobinhoodPython")
sys.path.append(".")

import pandas
from yahoo_finance_historical_data_extract import YFHistDataExtr
from yahoo_finance import Share
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

def calculate_bands(ticker_symbol):
    data_ext = YFHistDataExtr()
    data_ext.set_interval_to_retrieve(400)#in days
    data_ext.set_multiple_stock_list([str(ticker_symbol)])
    data_ext.get_hist_data_of_all_target_stocks()
    # convert the date column to date object
    data_ext.all_stock_df['Date'] =  pandas.to_datetime( data_ext.all_stock_df['Date'])
    temp_data_set = data_ext.all_stock_df.sort('Date',ascending = True ) #sort to calculate the rolling mean

    temp_data_set['20d_ma'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=5)
    #temp_data_set['50d_ma'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=50)
    #temp_data_set['Bol_upper'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=80) + 2* pandas.rolling_std(temp_data_set['Adj Close'], 80, min_periods=80)
    temp_data_set['Bol_lower'] = pandas.rolling_mean(temp_data_set['Adj Close'], window=80) - 2* pandas.rolling_std(temp_data_set['Adj Close'], 80, min_periods=80)
    #temp_data_set['Bol_BW'] = ((temp_data_set['Bol_upper'] - temp_data_set['Bol_lower'])/temp_data_set['20d_ma'])*100
    #temp_data_set['Bol_BW_200MA'] = pandas.rolling_mean(temp_data_set['Bol_BW'], window=50)#cant get the 200 daa
    #temp_data_set['Bol_BW_200MA'] = temp_data_set['Bol_BW_200MA'].fillna(method='backfill')##?? ,may not be good
    #temp_data_set['20d_exma'] = pandas.ewma(temp_data_set['Adj Close'], span=20)
    #temp_data_set['50d_exma'] = pandas.ewma(temp_data_set['Adj Close'], span=50)
    data_ext.all_stock_df = temp_data_set.sort('Date',ascending = False ) #revese back to original

    return temp_data_set['Adj Close'], temp_data_set['Bol_lower'], temp_data_set['20d_ma']


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
        except Exception:
            print "Could not test ticker: %s" % stock_ticker
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

    results = pool.map(test_ticker, stock_file.readlines())

    return results


def test_ticker(stock_ticker):
    print "Testing: %s" % stock_ticker
    stock_ticker = stock_ticker.strip()
    for special_char in SPECIAL_CHAR_LIST:
        stock_ticker = stock_ticker.replace(special_char, "")

    # Get the bollinger band history along with the 5 day moving average
    try:
        close, lower_band, five_day_ma = calculate_bands(stock_ticker)
    except Exception:
        print "Could not test ticker: %s" % stock_ticker
        return None

    # If I get bad data, just continue to the next stock
    if len(close) < 5 or len(lower_band) < 5 or len(five_day_ma) < 5:
        print "Could not test ticker: %s" % stock_ticker
        return None

    last_5_days_5_day_ma = []
    last_5_days_bb = []
    last_5_days_close = []

    for i in range(0, 5):
        last_5_days_5_day_ma.append(five_day_ma[i])
        last_5_days_bb.append(lower_band[i])
        last_5_days_close.append(close[i])

    # Condition 1: Has the stock price at close been below the lower bollinger band
    # at market close within the last 5 days
    for i in range(0, 5):
        if last_5_days_close[i] < last_5_days_bb[i]:

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
    
    LOW_VOLUME_LIMIT = 500,000

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
    #good_candidates = find_all_good_candidates()

    good_candidates = ['DGLT', 'USAS', 'UUUU', 'VVPR', 'AHPA', 'LVHE', 'OILB',
        'SNES', 'TPIV', 'INSG', 'CDEV', 'OILK', 'CSTR', 'RCOM', 'LSI', 'EUFS',
        'BSWN', 'DMPI', 'HRI', 'TWLO', 'HRI', 'STIE', 'TANNI', 'AAB', 'SRTS',
        'OIIL', 'MLPZ', 'GSM', 'VYGR', 'ASHX', 'PMTS', 'AGI', 'ARWA', 'COLL', 
        'OPGN', 'CHAU', 'CHEK', 'AFTY', 'CAPR', 'CTRV', 'LBIO', 'VNRX', 'SBEU',
        'CPSH', 'PSLV', 'NVX', 'NHF', 'SGYPW', 'WHLRW', 'CAPNW', 'KMI', 'CRMD',
        'CBON', 'PDBC', 'ADMA', 'PRTO', 'SRSC', 'HDLV', 'KRG', 'BRX', 'WPG', 'FRT',
        'LSI', 'BFS', 'UBA', 'REG', 'AKR', 'ACC', 'RPAI', 'SRC', 'CHMI', 'WSR',
        'EDR', 'SPG', 'CYBR', 'TKAI', 'CFRX', 'WHLM', 'CNXT', 'JMEI', 'CCLP',
        'ELP', 'AMAP', 'WES', 'MBT', 'BHP', 'AMID', 'SIM', 'PTR', 'SSN', 'GSH',
        'AB', 'ERJ', 'FANH', 'WBAI', 'PVD', 'JRJC', 'NGL', 'NS', 'ACH', 'CEQP',
        'BBDO', 'VCO', 'VRTV', 'ABY', 'TSE', 'LALT', 'QAT', 'T', 'ARX', 'SIVR',
        'ASNA', 'CDI', 'EFU', 'EFZ', 'FDP', 'TECK', 'BGI', 'BSFT', 'SAND', 'KS',
        'LUNA', 'ALN', 'OESX', 'MAG', 'OTIV', 'MANH', 'HEES', 'EBSB', 'CUPM', 'NDAQ',
        'UHN', 'YPRO', 'UUUU', 'ARRY', 'UCO', 'TXMD', 'BABY', 'HUBB', 'GSC', 'AHC',
        'ASHR', 'RDN', 'HRI', 'EGHT', 'NRG', 'COBO', 'SEA', 'DGII', 'PODD', 'CLDX',
        'SMRT', 'SNSS', 'UGA', 'EMX', 'JAKK', 'CPER', 'DJCI', 'PBH', 'HPHW', 'HP',
        'SGOC', 'QTWWQ', 'VRD', 'AMAG', 'TVIA']

    filtered_good_candidates = filter_good_candidates(good_candidates)

    # Now, we build the email message to send
    send_email("Investment Aggregator Stock Update", filtered_good_candidates)


    import code; code.interact(local=locals())
















