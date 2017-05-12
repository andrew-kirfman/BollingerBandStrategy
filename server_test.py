#!/usr/bin/env python

# ---------------------------------------------------------------------------- #
# Developer: Andrew Kirfman                                                    #
# Project: CSCE-470 Project Task #3                                            #
#                                                                              #
# File: ./server_test.py                                                       #
# ---------------------------------------------------------------------------- #

# ---------------------------------------------------------------------------- #
# Standard Library Includes                                                    #
# ---------------------------------------------------------------------------- #

import tornado.ioloop
import tornado.web
import tornado.websocket
import os
import sys
import logging
import copy
from tornado.options import define, options, parse_command_line
import MySQLdb
import smtplib
from email.mime.text import MIMEText
from yahoo_finance import Share

# Local file for interacting with the solr data index
sys.path.append(".")
import solr_search
from dividend_stripper import strip_dividends
from bollinger_bands import calculate_bands

import requests
from http.requests.proxy.requestProxy import RequestProxy
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------- #
# Global Variables                                                             #
# ---------------------------------------------------------------------------- #

TICKER_FILE="../task_1/google_search_program/publicly_traded_stocks.txt"

current_solr_object = None

try:
    os.makedirs("./static/pictures")
except Exception:
    pass

# UPDATE THE DATABASE UPDATE THE DATABASE UPDATE THE DATABASE!!!




# Current Database Parameters
DB_HOST="127.0.0.1"
DB_USER="root"
DB_PASSWD="drew11"
DB_PRIMARY_DATABASE=""

# Maintain a global object for interacting with the database
current_stock_database = None

# Maintain a global object for interacting with the list of publicly traded stocks
current_stock_list = None

# Email address for the server admin
ADMIN_EMAIL = "andrew.kirfman@tamu.edu"

# ---------------------------------------------------------------------------- #
# Command Line Arguments                                                       #
# ---------------------------------------------------------------------------- #

# Import Command Line Arguments
define("port", default=8888, help="Run on the given port", type=int)
define("logger", default="", help="Define the current logging level", type=str)

# ---------------------------------------------------------------------------- #
# Console/File Logger                                                          #
# ---------------------------------------------------------------------------- #

print_logger = logging.getLogger('stock_console_log')

# Set this variable if you want to use the req_proxy library
use_proxy = False

# I'm pretty sure that Python will get mad if I do not forward declare this variable
req_proxy = None

if use_proxy is False:
    import requests
else:
    req_proxy = RequestProxy()

# ---------------------------------------------------------------------------- #
# Database Call Level Interface                                                #
# ---------------------------------------------------------------------------- #

class stock_database:
    def __init__(self):
        self.initialized = False
        self.database_object = None

        print_logger.debug("Database object initialized successfully.")


    def connect(self):
        print_logger.debug("Connecting to database: %s" % DB_PRIMARY_DATABASE)
        self.database_object = MySQLdb.connect(host=DB_HOST, user=DB_USER, passwd=DB_PASSWD)

        # Attempt to use the existing greenhouse database
        current_pointer = self.database_object.cursor()

        try:
            current_pointer = self.database_object.cursor()
            result = current_pointer.execute("USE %s;" % DB_PRIMARY_DATABASE)

            print_logger.debug("Greenhouse database used successfully.")
        except Exception as e:
            print_logger.debug("Greenhouse database use failed.  Attempting to create.")

            # The database doesn't exist, create it
            try:
                current_pointer = self.database_object.cursor()
                result = current_pointer.execute("CREATE DATABASE %s;" % DB_PRIMARY_DATABASE)

                print_logger.debug("Created the greenhouse database.")

                current_pointer = self.database_object.cursor()
                result = current_pointer.execute("USE %s" % DB_PRIMARY_DATABASE)

                print_logger.debug("Greenhouse database used successfully.")
            except Exception as e:
                print_logger.error("Could not create or use the greenhouse database.")
                sys.exit(1)

        # Database object is now up and running
        print_logger.debug("Connected to database successfully.")
        self.initialized = True

    def disconnect(self):
        # Close the cursor first
        self.database_object.cursor().close()

        # Close the database object
        self.database_object.close()

        # The database objet is no longer initialized
        self.initialized = False

        print_logger.debug("Successfully disconnected from the database.")

    def issue_db_command(self, cmd, silent = False):
        """
        Issue a generic command denoted by cmd to the database.  Performs basic
        error checking and loggs the result.  Returns the result of the command
        False if it failed.
        """

        print_logger.debug("Issuing command: %s" % str(cmd))

        if self.initialized is False:
            print_logger.error("Database not initialized.")
            return

        current_pointer = self.database_object.cursor()

        try:
            # Execute the command
            result = current_pointer.execute(cmd)

            self.database_object.commit()

            return current_pointer.fetchall()
        except Exception as e:
            if silent == False:
                print_logger.error("Could not execute command: ")
                print_logger.error("  - Error Message: %s" % str(e[1]))
                print_logger.error("  - Failed Command: %s" % str(cmd))
            else:
                print_logger.debug("Could not execute command: ")
                print_logger.debug("  - Error Message; %s" % str(e[1]))
                print_logger.debug("  - Failed Command: %s" % str(cmd))

            return False

    def check_tables(self):
        """
        Make sure that every table in the database is where it should be.
        If there are any problems, rerun the commands
        """

        print_logger.debug("Checking tables for consistency.")

        pass

# ---------------------------------------------------------------------------- #
# Testing Functions                                                            #
# ---------------------------------------------------------------------------- #

def clean_tables():
    """
    This function wipes out all of the existing tables in the database.
    """

    pass

# ---------------------------------------------------------------------------- #
# Email Interface                                                              #
# ---------------------------------------------------------------------------- #

# Our account login information
# Address: greenhouse.reporter@gmail.com
# Password: TeamGreenThumb (case sensitive)

def send_email(message, recepient):
    msg = MIMEText(str(message))

    # me == the sender's email address
    # you == the recipient's email address
    msg['Subject'] = "Greenhouse Error Report"
    msg['From'] = "greenhouse.reporter@gmail.com"
    msg['To'] = str(recepient)

    # Send the message via our own SMTP server, but don't include the
    # envelope header
    s = smtplib.SMTP('smtp.gmail.com:587')
    s.ehlo()
    s.starttls()
    s.login("greenhouse.reporter", "TeamGreenThumb")
    s.sendmail("greenhouse.reporter@gmail.com", [str(recepient)], msg.as_string())
    s.quit()

# ---------------------------------------------------------------------------- #
# Ticker Data                                                                  #
# ---------------------------------------------------------------------------- #

class ticker_data:
    def __init__(self):
        # Read in the file
        f = open(TICKER_FILE, "r")

        self.stock_dict = {}

        for line in f.readlines():
            line = line.split(",")

            # Sometimes, the line lengths don't come out quite right.  If that
            # is the case, just skip to the next line.
            if len(line) != 3:
                continue

            self.stock_dict.update({line[1] : (line[0], line[2])})

    def is_valid_stock(self, ticker_symbol):

        # Make sure that the symbol is upper case
        ticker_symbol = ticker_symbol.upper()

        # Check to see if it is in the stock dictionary
        if ticker_symbol in self.stock_dict.keys():
            return True
        else:
            return False


    def update_traded_stocks(self):
        """
        <stub>: This function should call the program which updates the current
        list of publicly traded stocks.  Update this sometime in the future.
        """

        pass

# ---------------------------------------------------------------------------- #
# Scraper for company news                                                     #
# ---------------------------------------------------------------------------- #

def update_descriptions():
    if use_proxy is True:
        global req_proxy

    for root, dirname, filenames in os.walk("../task_1/google_search_program/cleaned_data"):
        if dirname != []:
            for ticker in dirname:
                desc_link = "http://www.reuters.com/finance/stocks/companyProfile?symbol="\
                    + str(ticker) + "&rpc=66"

                request = None

                while request is None:

                    if use_proxy is True:
                        request = req_proxy.generate_proxied_request(desc_link)
                    else:
                        request = requests.get(desc_link)

                    if request is not None:
                        if request.status_code != 200:
                            request = None

                request_soup = BeautifulSoup(request.text, "html5lib")

                if len(request_soup.find_all("div", { "class" : "moduleBody" })) < 2:
                    continue

                company_description = request_soup.find_all("div", { "class" : "moduleBody" })[1]

                # Sometimes, an extra div sticks around.  Just get rid of it if it is there
                bad_parts = company_description.find_all("div")

                if len(bad_parts) > 0:
                    company_description = str(company_description).replace(str(bad_parts[0]), "")

                # Actually write the company description to a file
                print "Writing: %s" % (ticker)
                f = open("../task_1/google_search_program/cleaned_data/%s/company_description" % ticker, "w+")
                f.seek(0)
                f.write(str(company_description))
                f.close()

def update_description_oneoff(ticker):
    if use_proxy is True:
        global req_proxy

    print "Executing oneoff description grab from reuters.com"

    desc_link = "http://www.reuters.com/finance/stocks/companyProfile?symbol="\
        + str(ticker) + "&rpc=66"

    request = None

    while request is None:
        if use_proxy is True:
            request = req_proxy.generate_proxied_request(desc_link)
        else:
            request = requests.get(desc_link)

        if request is not None:
            if request.status_code != 200:
                request = None

    request_soup = BeautifulSoup(request.text, "html5lib")

    if len(request_soup.find_all("div", { "class" : "moduleBody" })) < 2:
        return "<div class=\"moduleBody\">No Description Found</div>"

    company_description = request_soup.find_all("div", { "class" : "moduleBody" })[1]

    # Sometimes, an extra div sticks around.  Just get rid of it if it is there
    bad_parts = company_description.find_all("div")

    if len(bad_parts) > 0:
        company_description = str(company_description).replace(str(bad_parts[0]), "")

    # Actually write this description to a file so it doesn't take so long to get later
    if not os.path.exists("../task_1/google_search_program/cleaned_data/%s" % ticker):
        os.makedirs("../task_1/google_search_program/cleaned_data/%s" % ticker)

    f = open("../task_1/google_search_program/cleaned_data/%s/company_description" % ticker, "w+")
    f.seek(0)
    f.write(str(company_description))
    f.close()

    return str(company_description)


def get_company_title_proxied(ticker):
    if use_proxy is True:
        global req_proxy

    print "Executing oneoff description grab from reuters.com"

    try:
        desc_link = "http://www.reuters.com/finance/stocks/companyProfile?symbol="\
            + str(ticker) + "&rpc=66"

        request = None

        while request is None:
            if use_proxy is True:
                request = req_proxy.generate_proxied_request(desc_link)
            else:
                request = requests.get(desc_link)

            if request is not None:
                if request.status_code != 200:
                    request = None

        request_soup = BeautifulSoup(request.text, "html5lib")

        company_name = request_soup.find_all("div", { "id" : "sectionTitle" })[0].text.strip().split(":")[1]

        # Write this to a file so that it doesn't take so long to get next time
        if not os.path.exists("../task_1/google_search_program/cleaned_data/%s" % ticker):
            os.makedirs("../task_1/google_search_program/cleaned_data/%s" % ticker)

        f = open("../task_1/google_search_program/cleaned_data/%s/company_info" % ticker, "w+")
        f.seek(0)
        f.write(str(company_name) + ",")
        f.close()

        return company_name
    except Exception:
        return "(%s) Name Not Found" % ticker



# ---------------------------------------------------------------------------- #
# Static Handlers                                                              #
# ---------------------------------------------------------------------------- #

class MainScreenHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        self.render("./main_screen.html")

class TickerHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        self.render("./ticker_screen.html")

class StrategiesHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        self.render("./investing_strategies.html")

class TipsHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        self.render("./investing_tips.html")

# ---------------------------------------------------------------------------- #
# Websocket Handlers                                                           #
# ---------------------------------------------------------------------------- #

class TickerWsHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, _):
        return True

    def open(self, _):
        pass

    def on_message(self, message):
        print_logger.debug("Received message: %s" % (message))

        self.write_message("Test Message")

        if "ValidateTicker" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed ticker validation request")
                self.write_message("ValidationFailed:Malformed")
                return

            ticker = message[1]

            # The file I have stored didn't end up being a good validation
            # option as it does not contain a complete list of all
            # securities.  I have to acquire the data from yahoo
            # finance anyway, so just use that.  The Share function
            # call will throw a NameError exception if the ticker doesn't exist
            # isValid = current_stock_list.is_valid_stock(ticker)

            isValid = True
            try:
                test = Share(str(ticker))

                if test.get_price() is None:
                    isValid = False
            except NameError:
                isValid = False

            if isValid:
                self.write_message("ValidationSucceeded:%s" % ticker)
                print_logger.debug("Ticker was valid")
            else:
                self.write_message("ValidationFailed:%s" % ticker)
                print_logger.debug("Ticker was bad")

            return

        elif "GetCompanyName" in message:
            print_logger.debug("You got here")
            message = message.split(":")
            company_ticker = message[1]
            company_name = ""
            try:
                company_info="../task_1/google_search_program/cleaned_data/" + company_ticker + "/company_info"
                company_name = " "

                f = open(company_info, "r")
                line = f.readlines()
                company_name = line[0].split(",")
                company_name = company_name[0]
                company_name = company_name.title()

                if '(' not in company_name:
                    company_name = company_name + " (%s)" % company_ticker
            except Exception:
                company_name = get_company_title_proxied(company_ticker)


            self.write_message("CompanyName:%s" % company_name)

        elif "ExecuteQuery" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed input query")
                self.write_message("QueryResult:Error")

            data = current_solr_object.issue_query(str(message[1]))

            data = current_solr_object.recover_links(data)

            final_string = "QueryResult"

            for link in data:
                final_string = final_string + ":" + str(link)

            self.write_message(final_string)

        elif "GetStockData" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed Message from Client")
                return

            ticker = message[1]

            # Get ticker information
            share_data = Share(ticker)
            price = share_data.get_price()
            percent_change = share_data.get_change()
            previous_close = share_data.get_prev_close()
            open_price = share_data.get_open()
            volume = share_data.get_volume()
            pe_ratio = share_data.get_price_earnings_ratio()
            peg_ratio = share_data.get_price_earnings_growth_ratio()
            market_cap = share_data.get_market_cap()
            book_value = share_data.get_price_book()
            average_volume = share_data.get_avg_daily_volume()
            dividend_share = share_data.get_dividend_share()
            dividend_yield = share_data.get_dividend_yield()
            earnings_per_share = share_data.get_earnings_share()
            ebitda = share_data.get_ebitda()
            fifty_day_ma = share_data.get_50day_moving_avg()
            days_high = share_data.get_days_high()
            days_low = share_data.get_days_low()
            year_high = share_data.get_year_high()
            year_low = share_data.get_year_low()
            two_hundred_day_ma = share_data.get_200day_moving_avg()

            # Build a string to send to the server containing the stock data
            share_string = "price:" + str(price) + "|"\
                         + "percentChange:" + str(percent_change) + "|"\
                         + "previousClose:" + str(previous_close) + "|"\
                         + "openPrice:" + str(open_price) + "|"\
                         + "volume:" + str(volume) + "|"\
                         + "peRatio:" + str(pe_ratio) + "|"\
                         + "pegRatio:" + str(peg_ratio) + "|"\
                         + "marketCap:" + str(market_cap) + "|"\
                         + "bookValue:" + str(book_value) + "|"\
                         + "averageVolume:" + str(average_volume) + "|"\
                         + "dividendShare:" + str(dividend_share) + "|"\
                         + "dividendYield:" + str(dividend_yield) + "|"\
                         + "earningsPerShare:" + str(earnings_per_share) + "|"\
                         + "ebitda:" + str(ebitda) + "|"\
                         + "50DayMa:" + str(fifty_day_ma) + "|"\
                         + "daysHigh:" + str(days_high) + "|"\
                         + "daysLow:" + str(days_low) + "|"\
                         + "yearHigh:" + str(year_high) + "|"\
                         + "yearLow:" + str(year_low) + "|"\
                         + "200DayMa:" + str(two_hundred_day_ma) + "|"

            self.write_message("StockData;%s" % (share_string))
            print_logger.debug("Sending Message: StockData;%s" % (share_string))
        elif "GetCompanyDesc" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed Message from Client")
                return

            ticker = message[1]

            # Read in the company description
            description = ""
            try:
                f = open("../task_1/google_search_program/cleaned_data/%s/company_description" % str(ticker), "r")
                description = f.read()
            except Exception:
                # If the file does not exist, get the data manually
                description = update_description_oneoff(ticker)

            self.write_message("CompanyDescription:%s" % str(description))
        elif "GetCompanyDividend" in message and "Record" not in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed Message from Client")
                return

            ticker = message[1]

            # Grab the dividend data from dividata.com
            dividend_url = "https://dividata.com/stock/%s/dividend" % ticker

            # This should potentially be a
            dividend_data = requests.get(dividend_url)
            dividend_soup = BeautifulSoup(dividend_data.text, 'html5lib')

            if len(dividend_soup.find_all("table")) > 0:
                dividend_soup = dividend_soup.find_all("table")[0]
            else:
                dividend_soup = "<h3>No dividend history found.</h3>"

            # Send this div up to the server
            self.write_message("DividendHistoryData:" + str(dividend_soup))
        elif "GetCompanyDividendRecord" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed Message from Client")
                return

            ticker = message[1]

            # Get the dividend record html for the table and send it up
            dividend_record = strip_dividends(ticker, req_proxy)

            print_logger.debug("Writing message: " + str(dividend_record))
            self.write_message("DividendRecord:" + str(dividend_record))
        elif "GetBollinger" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed Message from Client")
                return

            ticker = message[1]

            # Get the bollinger band history along with the 5 day moving average
            close, lower_band, five_day_ma = calculate_bands(ticker)

            last_5_days_5_day_ma = []
            last_5_days_bb = []
            last_5_days_close = []
            for i in range(0, 5):
                last_5_days_5_day_ma.append(five_day_ma[i])
                last_5_days_bb.append(lower_band[i])
                last_5_days_close.append(close[i])

            condition_1 = False
            condition_2 = False

            # Condition 1: Has the stock price at close been below the lower bollinger band
            # at market close within the last 5 days
            for i in range(0, 5):
                if last_5_days_close[i] < last_5_days_bb[i]:
                    condition_1 = True

            # Condition 2: Has the current stock price been above the 5 day moving average sometime in the last 3 days
            for i in range(0, 3):
                if last_5_days_close[i] > last_5_days_5_day_ma[i]:
                    condition_2 = True

            if condition_1 is True and condition_2 is True:
                self.write_message("BB:GoodCandidate")
            else:
                self.write_message("BB:BadCandidate")
        elif "GetSentiment" in message:
            message = message.split(":")

            if len(message) != 2:
                print_logger.error("Malformed Message from Client")
                return

            ticker = message[1]

            # Lists of sentiment based words
            good_words = ["buy", "bull", "bullish", "positive", "gain", "gains", "up"]
            bad_words = ["sell", "bear", "bearish", "negative", "loss", "losses", "down"]

            DATA_DIRECTORY = "../task_1/google_search_program/cleaned_data/%s" % ticker.upper()


            positive_file_stats = []
            negative_file_stats = []
            positive_files = 0
            negative_files = 0

            neutral_files = 0

            trump_count = 0

            files_examined = 0

            for root, dirs, files in os.walk(DATA_DIRECTORY):
                path = root.split(os.sep)
                print((len(path) - 1) * '---', os.path.basename(root))

                for file in files:

                    if "article" in file:
                        f = open('/'.join(path) + '/' + file)

                        title = f.readline()

                        article_text = " ".join(f.readlines())

                        if article_text.count("trump") > 0:
                            trump_count = trump_count + 1

                        positive_word_count = 0
                        negative_word_count = 0

                        files_examined = files_examined + 1

                        for word in good_words:
                            if word in article_text:
                                positive_word_count = positive_word_count + article_text.count(word)
                                print "Word: %s, %s" % (word, article_text.count(word))


                        for word in bad_words:
                            if word in article_text:
                                negative_word_count = negative_word_count + article_text.count(word)

                        if positive_word_count > negative_word_count:
                            positive_ratio = float(positive_word_count) / float(negative_word_count + positive_word_count)

                            if positive_ratio > 0.7:
                                positive_files = positive_files + 1

                                positive_file_stats.append((positive_word_count, negative_word_count))
                            else:
                                neutral_files = neutral_files + 1

                        elif positive_word_count == negative_word_count:
                            neutral_files = neutral_files + 1

                        else:
                            negative_ratio = float(negative_word_count) / float(negative_word_count + positive_word_count)

                            if negative_ratio > 0.7:
                                negative_files = negative_files + 1

                                negative_file_stats.append((positive_word_count, negative_word_count))
                            else:
                                neutral_files = neutral_files + 1

            print_logger.debug("Sentiment:" + str(positive_files) + ":" + str(negative_files) +\
                ":" + str(neutral_files) + ":" + str(trump_count) + ":" + str(files_examined))

            self.write_message("Sentiment:" + str(positive_files) + ":" + str(negative_files) +\
                ":" + str(neutral_files) + ":" + str(trump_count) + ":" + str(files_examined))




        # May need to add more functionality here. Don't know

# ---------------------------------------------------------------------------- #
# Generic File Handler                                                         #
# ---------------------------------------------------------------------------- #

class ProgramFileHandler(tornado.web.StaticFileHandler):
    def initialize(self, path):
        self.dirname, self.filename = os.path.split(path)
        super(ProgramFileHandler, self).initialize(self.dirname)

    def get(self, path=None, include_body=True):
        program_file = str(self.dirname) + '/' + str(self.filename) + '/' + str(path)
        super(ProgramFileHandler, self).get(program_file, include_body)

# ---------------------------------------------------------------------------- #
# Master Handler List                                                          #
# ---------------------------------------------------------------------------- #


settings = { }
handlers = [
    (r'/', MainScreenHandler),
    (r'/ws_ticker(.*)', TickerWsHandler),
    (r'/ticker', TickerHandler),
    (r'/investing_tips', TipsHandler),
    (r'/investing_strategies', StrategiesHandler),
    (r'/(.*)', ProgramFileHandler, {'path' : './'})
    ]

# ---------------------------------------------------------------------------- #
# Initialization Commands                                                      #
# ---------------------------------------------------------------------------- #

app = tornado.web.Application(handlers, **settings)

if __name__ == '__main__':
    #update_descriptions()

    parse_command_line()
    app.listen(options.port)

    # Set the logger verbosity
    if options.logger == "qq":
        print_logger.setLevel(logging.CRITICAL)
    elif options.logger == "q":
        print_logger.setLevel(logging.ERROR)
    elif options.logger == "":
        print_logger.setLevel(logging.WARNING)
    elif options.logger == "v":
        print_logger.setLevel(logging.INFO)
    elif options.logger == "vv":
        print_logger.setLevel(logging.DEBUG)
    else:
        print_logger.setLevel(logging.WARNING)

    # Load the current list of publicly traded stocks
    current_stock_list = ticker_data()

    # Initialize the solr object
    current_solr_object = solr_search.solr_search()

    # Update the database code at a later date

    # Initialize the database object
    #current_greenhouse_database = greenhouse_database()

    # Connect to the database
    #current_greenhouse_database.connect()

    # REMOVE THIS LATER
    #clean_tables()

    # Make sure all of the tables are where they should be.
    #current_greenhouse_database.check_tables()



    tornado.ioloop.IOLoop.instance().start()
