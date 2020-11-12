import argparse
import inflect
import logging
import random
import time

import matplotlib
matplotlib.use('Agg')   # Used as a workaround for hosting on headless server;
                        # DONT MOVE; it must go between these two imports
import matplotlib.pyplot as plt
import tweepy

import cpsbimports as cpfn
from team import Team

def readteam(fname):
    ''' Reads and parses the team file, and returns the contents as a list.'''

    t = []
    try:
        with open(fname) as f:
            for line in f:
                s = line.strip()
                if (s!='\n') and (s[0] != '#'):
                    t.append(s)
    except e:
        logging.error(e)

    return t

def minplace(lstTeam):
    l = []
    for i in lstTeam:
        l.append(lstTeam[i].series.iloc[0]['OverallPlace'])
    return min(l)

def mintime(lstTeam):
    l = []
    for i in lstTeam:
        l.append(lstTeam[i].series.iloc[0]['PlayTime'])
    if l:
        return min(l)
    else:
        return "00:00:00"

def maxtime(lstTeam):
    l = []
    for i in lstTeam:
        l.append(lstTeam[i].series.iloc[0]['PlayTime'])
    if l:
        return max(l)
    else:
        return "00:00:00"

def stillalive(lstTeam):
    l = 0
    for i in lstTeam:
        if lstTeam[i].live:
            l += 1
    if l > 0:
        return True
    else:
        return False

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

def report(tbl, ofile, teamfile = None, st = None, n = None):
    ''' Generates a table of the team's standings.'''
    # teamfile: determines which teams get highlighted (generally the ones being tracked)
    #           by itself returns a list of the teams with an alias, which are the local teams
    # st:

    t = []
    subtbl = []
    if teamfile:
        t = readteam(teamfile)
        subtbl = tbl[tbl['TeamName'] != '']     # Teamfile teams highlighted
                                                # filter by the ones with an associated alias (local teams)
    if st:
        subtbl = tbl[tbl['State'] == st]        # filter by state

    if n:
        subtbl = tbl.head(n)  # Assume that the presence of n indicates "top n"

    if (not teamfile) and (not st) and (not n):
        subtbl = tbl.head(25)       # if no parameters are specified, give the top 25 with no highlights

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
    parser.add_argument('team', help="Text file of team numbers to track (one per line).")
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
        refresh = int(args.refresh)
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

    # t = 1*60 # Diagnostic setting
    t = 15*60  # Time interval for posting a place report (default is 15 minutes +/- 10%)
    tstamp = time.time()
    next = tstamp + random.uniform(t - (t * .1), t + (t * .1))
    imgfile = 'report'  # File name for the table image used in the place report

    topn = 10   # top n teams for the topn report

    launchtime = time.time()
    tweets = 0

    # Start monitoring the website
    # [TODO] Change the twitter profile pic to CP when the competition starts.
    # [TODO] Tweet an opening remark, such as the date, time, school, and URL of the official scoreboard

    while True:
        # Retrieve new table from the web page every refresh interval (default 60 seconds)
        table = []
        cb = cpfn.CPTableParser()

        table = cpfn.getmaintable(url, afile)  # Extract the table from the tuple

        # Extract rows of interest for monitoring (managed by a class) and update the class object with each refresh
        f = readteam(tfile)

        for s in f:
            cell = table[table['TeamNumber'].str.match(s)]

            if len(cell):
                l = cell.iloc[0]['State']
                if s in tracker:
                    tracker[s].updatestats(cell)

                    tm = tracker[s]
                    if tm.timewarning == False:
			#[TODO] Logic error (possibly in team.py)
                        str = 'Less than one hour remaining in the competition for {} ({}).'.format(
                            tm.series.iloc[0]['TeamName'],
                            tm.series.iloc[0]['TeamNumber'])
                        tm.timewarning = None
                        tweet(api, str)

                    if redzone and tm.post:  # Only post play-by-plays later in the round.
                        #	Add a time tag if the update does not include a positive score
			# [TODO] Add an announcement of 4 hour threshold; starts play-by-play tweets
                        live = stillalive(tracker)
                        if tm.scoreDiff <= 0 and live:
                            timediff = time.time() - tm.lastScore

                            if timediff < 60:
                                lasttime = time.strftime("%S seconds",time.gmtime(timediff))
                            else:
                                lasttime = time.strftime("%M minutes",time.gmtime(timediff))

                            tm.message = tm.message + 'The last positive score was about {} ago. '.format(lasttime)

                        elif not live:
                            tm.message = tm.message + 'There are {} teams competing ({} in {}). '.format(
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

            # Play-by-play tweets should start at about the 2/3 mark of the
            # longest playing team; 4 hours (14,400 seconds) for a 6-hour round.
            # The result is a status update about every 3-5 minutes, or about
            # 24-40 tweets in a 2-hour period.

            h, m, s = maxtime(tracker).split(':')
            if (int(h)*3600 + int(m)*60) > 3600 * 4:
                redzone = True
            else:
                redzone = False

        if (time.time() > next) and stillalive(tracker):
            # weight the choices so that state [1] and local [2] get shown more often
            # unless one of the target teams is in the top n (default = 10)
            m = minplace(tracker)

            if m <= topn:
                choices = [1] * 3 + [2] * 2 + [3] * 4
            else:
                choices = [1] * 4 + [2] * 4 + [3] * 2

            r = random.choice(choices)

            str = 'Unofficial live scores: {}. As of {}, there are {} teams competing overall, and {} teams in {}. '.format(
                url,
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
                report(table, imgfile, teamfile = tfile, n = topn)  # Show the top n teams

            tweet(api, str, imgfile)
            next = time.time() + random.uniform(t - (t * .1), t + (t * .1))

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
