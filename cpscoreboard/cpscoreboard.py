import argparse
import inflect
import logging
import os
import random
from random import randrange
import requests
import time

from bs4 import BeautifulSoup
import matplotlib
matplotlib.use('Agg')   # Used as a workaround for hosting on headless server
import matplotlib.pyplot as plt
import pandas as pd
import tweepy

from team import Team


class CPTableParser:
    ''' Retrieves the HTML scoreboard provided by the website and
    storees it as a pandas dataframe'''

    def parse_url(self, url):

        try:
            response = requests.get(url)

        except requests.exceptions.RequestException as e:
            logging.warning('No response from {} ({}).'.format(url, e))
            logging.debug(e)
            return []

        # Accumulate the responses (e.g., for simulation and debugging)
        # if (logging.getLogger().getEffectiveLevel() == 10):
        if (logging.getLogger().getEffectiveLevel() > 0):
            if not os.path.exists('./pages'):
                os.makedirs('./pages')

            fname = './pages/cpscore_' + time.strftime('%Y-%b-%d_%H%M', time.localtime()) + '.php'
            page = open(fname, 'w')
            page.write(response.text)
            page.close()

        soup = BeautifulSoup(response.text, 'lxml')

        return [(0, self.parse_html_table(table)) for table in
                soup.find_all('table')]

    def parse_html_table(self, table):
        n_columns = 0
        n_rows = 0
        column_names = []

        # Find number of rows, columns, and column titles
        for row in table.find_all('tr'):

            # Determine the number of rows in the table
            td_tags = row.find_all('td')
            if len(td_tags) > 0:
                n_rows += 1
                if n_columns == 0:
                    # Set the number of columns for our table
                    n_columns = len(td_tags)

            # Handle column names if we find them
            th_tags = row.find_all('th')
            if len(th_tags) > 0 and len(column_names) == 0:
                for th in th_tags:
                    column_names.append(th.get_text())

        # Safeguard on Column Titles
        if len(column_names) > 0 and len(column_names) != n_columns:
            raise Exception("Column titles do not match the number of columns")

        columns = column_names if len(column_names) > 0 \
            else range(0, n_columns)

        df = pd.DataFrame(columns=columns,
                          index=range(0, n_rows))
        row_marker = 0
        for row in table.find_all('tr'):
            column_marker = 0
            columns = row.find_all('td')
            for column in columns:
                df.iat[row_marker, column_marker] = column.get_text()
                column_marker += 1
            if len(columns) > 0:
                row_marker += 1

        # Convert numberical columns to integers if possible
        for col in df:
            try:
                df[col] = df[col].astype(int)
            except ValueError:
                pass

        return df




def addplaces(tbl):
    # add the overall place as a column so that each row can be tracked
    # without depending on the context of the table index
    tbl['OverallPlace'] = [i for i in tbl.index]

    d = {}
    row = 1     # rows are 1-indexed because tbl[0] is the header row

    tbl['StatePlace'] = pd.Series([], dtype=object)
    for i in tbl['State']:   # add a column for place within states
        if i in d:
            d[i] += 1
        else:
            d[i] = 1
        tbl.loc[row, 'StatePlace'] = d[i]
        row += 1

    return (d, tbl)

def addalias(fname, tbl):
    ''' Reads and parses the lookup file and returns the contents as a dictionary.'''
    f = open(fname, 'r')
    dict = {}

    for line in f:
        if line[0] == '#':
            continue

        s = line.strip().split(',')

        if s[0] in dict:
            logging.error("Duplicate alias for team {} ({}). The existing alias {} is in use.".format(s[0], s[1], dict[s[0]]))
        try:
            dict[s[0]] = s[1]
        except IndexError:
            logging.error('Error in alias file. There is no alias provided for {}'.format(s[0]))

    f.close()

    tbl['TeamName'] = tbl['TeamNumber'].map(dict).fillna('')

    return tbl

def readteam(fname):
    ''' Reads and parses the team file, and returns the contents as a list.'''

    t = []
    with open(fname) as f:
        for line in f:
            s = line.strip()
            if s[0] != '#':
                t.append(s)
    return t

def tweet(api, s, img=None):
    if not api:
        logging.info('{}'.format(s))

    else:
        if img:
            if not(img.endswith('.png')):
                img = img + '.png'

            try:
                api.update_with_media(img, status=s)
            except tweepy.error.TweepError as e:
                logging.error(e)

        else:
            try:
                api.update_status(status=s)
            except tweepy.error.TweepError as e:
                logging.error(e)

def report(tbl, ofile, teamfile = None, st = None, n = 10):
    ''' Generates a table of the team's standings.'''

    # [TODO] The local standings were posting as top-10; need to overhaul how the report type is selected.
    t = []
    if teamfile:
        t = readteam(teamfile)
        subtbl = tbl[tbl['TeamName'] != '']     ## TeamFile teams will be the only ones with an associated alias

    if st:
        subtbl = tbl[tbl['State'] == st]

    if n:
        subtbl = tbl.head(n)

    subtbl = subtbl[['TeamNumber', 'TeamName', 'OverallPlace', 'StatePlace', 'State', 'CurrentScore', 'PlayTime']]

    # Rename columns for presentation
    subtbl.rename(columns={'OverallPlace': 'Place (National)'}, inplace=True)
    subtbl.rename(columns={'StatePlace': 'Place (State)'}, inplace=True)
    subtbl.rename(columns={'TeamNumber': 'Team'}, inplace=True)
    subtbl.rename(columns={'TeamName': 'Name'}, inplace=True)
    subtbl.rename(columns={'CurrentScore': 'Score'}, inplace=True)
    subtbl.rename(columns={'PlayTime': 'Elapsed Time'}, inplace=True)

    fig, ax = plt.subplots()
    fig.patch.set_visible(False)

    ax.axis('off')
    ax.axis('tight')

    if len(subtbl.index) == 0:
        logging.error('Error in query. There are no teams on the board for {}'.format(st))
    else:
        df = subtbl
        table = ax.table(cellText=df.values, colLabels=df.columns, loc='center')

        # Highlight the teamfile teams in yellow
        cols = len(df.columns)

        for key, cell in table.get_celld().items():
            if cell.get_text().get_text() in t:
                for i in range(0, cols):
                    table._cells[(key[0], i)].set_color('yellow')
                    table._cells[(key[0], i)].set_edgecolor('black')

    if not(ofile.endswith('.png')):
        ofile = ofile + '.png'

    plt.savefig(ofile, aspect='auto', dpi = 800)

##############################################################################

def main():

    # Prep: Parse arguments for input
    parser = argparse.ArgumentParser(description='CyberPatriot Scorebot')

    parser.add_argument('url', help='URL to the Scoreboard')
    parser.add_argument('team', help="Text file of team numbers to track (one per line")
    parser.add_argument('-a', '--alias', help="CSV file of team numbers and name aliases.")
    parser.add_argument('-k', '--keys',
                        help="Twitter API Keys (separated by space): ConsumerKey SecretKey AccessToken AccessSecret)",
                        nargs=4)
    parser.add_argument('-r', '--refresh', help="Refresh Interval (default: 60 seconds)")
    parser.add_argument('-o', '--output',
                        help="File name for output journal (default: scoreboard.txt in current directory)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Enable verbose logging (e.g., for troubleshooting).")
    args = parser.parse_args()

    # Positional arguments (mandatory)
    url = args.url
    tfile = args.team

    # Optional arguments
    if args.alias:
        afile = args.alias
    else:
        afile = None

    if args.keys:
        consumer_key = args.keys[0]
        consumer_secret = args.keys[1]
        access_token = args.keys[2]
        access_token_secret = args.keys[3]

        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(access_token, access_token_secret)
        api = tweepy.API(auth)
    else:
        api = None

    if args.refresh:
        refresh = args.refresh
    else:
        refresh = 60

    if args.output:
        ofile = args.output
    else:
        ofile = 'scoreboard.log'

    if args.verbose:
        loglev = logging.DEBUG
    else:
        loglev = logging.INFO

    # ## DIAGNOSTIC VARIABLES
    # # url = 'http://54.243.195.23/index.php?division=Middle%20School'
    # # url = 'http://scoreboard.uscyberpatriot.org/index.php?division=Middle%20School'
    # url = 'http://127.0.0.1/testpage.php'
    # afile = 'lookups'
    # tfile = 'team'
    # ofile = 'scoreboard.txt'

    # Prep: Set up logging
    loops = 0
    logging.basicConfig(filename=ofile,
                        format='[%(asctime)s] %(levelname)s %(funcName)20s(): %(message)s',
                        datefmt= "%Y-%m-%d %H:%M.%S",
                        level=loglev)
    logging.info('-' * 80)
    logging.info('Log opened.')
    logging.info('-' * 80)

    if api:  # Don't output the actual keys in the log file; just whether they were provided.
        tw = 'TRUE'
    else:
        tw = 'FALSE'

    logging.info('Scoreboard launched in {} mode with the following arguments:\n\t'
                  'URL:\t\t{}\n\t'
                  'TEAM FILE:\t{}\n\t'
                  'ALIAS FILE:\t{}\n\t'
                  'TWITTER KEYS:\t{}\n\t'
                  'REFRESH INT:\t{}\n\t'
                  .format(logging.getLevelName(logging.getLogger().getEffectiveLevel()),
                          args.url, args.team, args.alias, tw, args.refresh))

    # Prep: Initialize variables
    tracker = {}  # Dictionary of Team objects, identified by 'TeamNumber'
    ords = inflect.engine()

    t = 15  # Time interval for posting a place report (default is 15 minutes +/- 10%)
    tstamp = time.time()
    next = tstamp + randrange(t - (t * .1), t + (t * .1))       # [TODO] This might produce an error; consider another approach.
    imgfile = 'report'  # File name for the table image used in the place report

    topn = 10   # top n teams for the topn report

    launchtime = time.time()
    tweets = 0

    # Play-by-play tweets should start at about the 2/3 mark; about 4 hours (14,400 seconds) for a 6-hour round.
    # The result is a status update about every 3-5, or about 24-40 tweets in a 2-hour period.
    # [TODO] Instead of hard-coding, configure the redzone to be at the 4 hour mark of the earliest team to start.
    redzone = time.time() + 30

    # Start monitoring the website
    # [TODO] Change the twitter profile pic to CP when the competition starts.
    # [TODO] Tweet an opening remark, such as the date, time, school, and URL of the official scoreboard

    # [TODO] Extract reusable functions out to cpsbimports.py

    while True:
        # Retrieve new table from the web page every refresh interval (default 60 seconds)
        table = []
        cb = CPTableParser()

        # Handle the condition when the site is not providing a score table
        try:
            response = time.time()
            table = cb.parse_url(url)[0][1]  # Extract the table from the tuple

        except IndexError as e:
            delay = (10*random.random()) * (time.time() - response)
            if delay < 1 or delay > 60:
                delay = refresh*random.random()
            logging.warning('No score table returned in {0}. Retrying in {1:.2f} seconds.'.format(url, delay))
            time.sleep(delay)
            continue

        # Extracts the header names from the first row & removes the first row
        table.columns = list(table.iloc[0])
        table = table[1:]

        # Renames the 'unfriendly' titles
        table.rename(columns={'Play Time(HH:MM)': 'PlayTime'}, inplace=True)
        table.rename(columns={'Location/Category': 'State'}, inplace=True)

        # Enrich the table with additional columns (overall place, place by
        # state, aliases from lookup table) and convert the data types
        # (all strings by default) to int, time, etc.
        (states, table) = addplaces(table)

        if afile:
            table = addalias(afile, table)

        table.CurrentScore = pd.to_numeric(table.CurrentScore).fillna(0)
        table.OverallPlace = pd.to_numeric(table.OverallPlace).fillna(0)
        table.StatePlace = pd.to_numeric(table.StatePlace).fillna(0)

        # Extract rows of interest for monitoring (managed by a class) and update the class object with each refresh
        f = readteam(tfile)

        for s in f:
            cell = table[table['TeamNumber'].str.match(s)]

            if len(cell):
                l = cell.iloc[0]['State']
                if s in tracker:
                    tracker[s].updatestats(cell)

                    tm = tracker[s]
                    # [TODO] tweet a one-time announcement when the team's PlayTime passes the 5 hour mark (tm.timewarning = False --> None)
                    # this should be controlled in the Team class that sets a flag property.

                    if time.time() > redzone and tm.post:  # Only post play-by-plays later in the round.
                        #	Add a time tag if the update does not include a positive score
                        if tm.scoreDiff <= 0 and tm.live:
                            timediff = time.time() - tm.lastScore

                            if timediff < 60:
                                lasttime = time.strftime("%S seconds",time.gmtime(timediff))
                            else:
                                lasttime = time.strftime("%M minutes",time.gmtime(timediff))

                            tm.message = tm.message + 'The last positive score was about {} ago. '.format(lasttime)

                        else if not tm.live:
                            tm.message = tm.message + 'There are {} teams competing ({} in {}). '.format(
                                time.strftime("%I:%M%p", time.localtime()),
                                len(table.index),
                                len(table[table['State'] == l].index), l)

                        logging.info(tm.message)
                        tweet(api, tracker[s].message)  # [TODO] Use threading to announce team updates (see below).
                        tm.post = False

                else:
                    tracker[s] = Team(cell)

                    if cell.iloc[0]['TeamName']:
                        name = '(' + cell.iloc[0]['TeamName'] + ')'
                    else:
                        name = ''

                    tweet(api,
                          'Team {} {} is on the board at {} with {} points. They are in {} place in {}. '.format(cell.iloc[0]['TeamNumber'],
                                name,
                                time.strftime("%I:%M %p", time.localtime()),
                                cell.iloc[0]['CurrentScore'],
                                ords.ordinal(cell.iloc[0]['StatePlace']), l))
            else:
                logging.info('Team {} is not on the scoreboard'.format(s))

        if (time.time() > next) and tm.live:
            # [TODO] Weight the updates to have more "State" and "Local" updates (#1 and #2)
            # [TODO] Incorporate a link to the actual scoreboard in the announcement.
            r = random.randint(1, 3)

            str = 'As of {}, there are {} teams competing overall, and {} teams in {}. '.format(
                time.strftime("%I:%M%p", time.localtime()),
                len(table.index),
                len(table[table['State'] == l].index), l)

            if r == 1:
                str = str + 'Local standings: '
                logging.debug('posted report: alias teams')
                report(table, imgfile, teamfile = tfile)  # Just the teams in the alias file (tfile gets highlighted)

            elif r == 2:
                str = str + 'State standings: '
                logging.debug('posted report: state teams')
                report(table, imgfile, teamfile = tfile, st=l)  # Show the teams in the state (most frequent in alias file)

            elif r == 3:
                str = str + 'Top standings: '
                logging.debug('posted report: top {} teams'.format(topn))
                report(table, imgfile, teamfile = tfile, n=topn)  # Show the top n teams

            tweet(api, str, imgfile)
            next = time.time() + randrange(t - (t * .1), t + (t * .1)) # [TODO] This might produce an error; consider another approach.

        for s in tracker:
            tm = tracker[s]
            if tm.live == False:
                str = 'Time is almost up for team {} ({}). Place changes will still be posted as a result of other teams competing'.format(
                    tm.series.iloc[0]['TeamName'], tm.series.iloc[0]['TeamNumber'])
                tm.live = None
                tweet(api, str)

        # [TODO] Use threading to post the team updates (i.e., play-by-play)
        # add s.message to a list
        #   launch threads to tweet all of the messages in the list

        time.sleep(refresh)
        loops += 1

        # [TODO] Detect a (manual) closing. Tweet and/or log an announcement, such as some closing stats.
        # [TODO] Change the twitter profile pic back to the original when the competition ends.

if __name__ == "__main__":
    main()

# [TODO] (LONG TERM) incorporate responses to messages (such as triggering a report)
# [TODO] (LONG TERM) post a notification tweet if the scoring web site goes down.
# [TODO] Thoroughly document the classes, functions, and algorithms.
