import inflect
import time
from datetime import datetime, timedelta
from collections import OrderedDict

class Team:
    ''' Tracks changes in a row extracted from the scoreboard. '''

    # Data Structure of the series:
    #   TeamNumber          str   10-3905
    #   State   str   CA
    #   Division            str   Middle School
    #   Tier                str   Middle School
    #   ScoredImages        str   3
    #   PlayTime            time  05:35
    #   CurrentScore        int   191
    #   *Warn
    #   OverallPlace        int   4
    #   StatePlace          int   4.0
    #   TeamName            str   Test School 1

    def __init__(self, s):
        self.series = s
        self.scoreDiff = 0
        self.oPlaceDiff = 0
        self.sPlaceDiff = 0
        self.lastScore = time.time()
        self.maxscore = 0
        self.message = ""
        self.post = False
        self.live = True

    def updatestats(self, newSeries):
        ''' Receives an updated row from the main scoreboard, compares with
        the existing row, records the relevant changes, and finally replaces
         the existing row with the new row.'''

        self.scoreDiff = newSeries.CurrentScore.item() - self.series.CurrentScore.item()
        self.oPlaceDiff = self.series.OverallPlace.item() - newSeries.OverallPlace.item()
        self.sPlaceDiff = self.series.StatePlace.item() - newSeries.StatePlace.item()

        if (self.scoreDiff > 0) and (newSeries.CurrentScore.item() > self.maxscore):
            self.maxscore = newSeries.CurrentScore.item()
            self.lastScore = time.time()

        self.series = newSeries

        if (self.scoreDiff + self.oPlaceDiff + self.scoreDiff) != 0:
            self.buildMessage()

        # Check if the team's time exceeds the 6 hour competition windows
        # (elapsed time + time since last score < 6 hours)
        etime = datetime.strptime(newSeries['PlayTime'].item(), '%H:%M')
        ltime = timedelta(seconds = (time.time() - self.lastScore))

        totaltime = etime + ltime

        limit = datetime.strptime('06:00', '%H:%M')

        if totaltime > limit:
            self.live = False

    def buildMessage(self):
        ''' Constructs and stores a string (will be twitter post),
         using the updated stats.'''

        # The following conditions trigger a report:
        #   Change in points
        #   Change in place (state)
        #   Change in place (overall)

        ords = inflect.engine()

        # Prioritizes string build by most significant category first
        stats = {}
        stats['ascore'] = self.scoreDiff
        stats['placeO'] = self.oPlaceDiff
        stats['placeS'] = self.sPlaceDiff

        # Sorting the dictionary results in a list of tuples
        stats = OrderedDict(sorted(stats.items(), key = lambda kv: (abs(kv[1]), kv[0]), reverse = True))

        try:
            message = '{} ({}) '.format(self.series['TeamName'].item(),
                                        self.series['TeamNumber'].item())
        except:
            message = 'Team {} '.format(self.series['TeamNumber'].item())

        for i in stats:
            title = i
            amount = stats[i]

            if (abs(amount) == 1):
                place = 'place'
            else:
                place = 'places'

            if title == 'ascore':
                if amount > 0:
                    message = message + '+{} points to {}. '\
                        .format(abs(amount),
                                self.series['CurrentScore'].item())
                if amount < 0:
                    message = message + '-{} points, down to {}. '\
                        .format(abs(amount),
                                self.series['CurrentScore'].item())
                if amount == 0:
                    message = message + 'Score unchanged ({}). '\
                        .format(self.series['CurrentScore'].item())

            if title == 'placeO':
                if amount > 0:
                    message = message + '+{} {} overall (now {}). '\
                        .format(abs(amount), place,
                                ords.ordinal(self.series['OverallPlace'].item()))
                if amount < 0:
                    message = message + '-{} {} overall (now {}). '\
                        .format(abs(amount), place,
                                ords.ordinal(self.series['OverallPlace'].item()))
                if amount == 0:
                    message = message + 'Overall place is unchanged; still {}. '\
                        .format(ords.ordinal(self.series['OverallPlace'].item()))

            if title == 'placeS':
                if amount > 0:
                    message = message + '+{} {} (now {} in {}). '\
                        .format(abs(amount),
                                place,
                                ords.ordinal(self.series['StatePlace'].item()),
                                self.series['State'].item())
                if amount < 0:
                    message = message + '-{} {} (now {} in {}). '\
                        .format(abs(amount),
                                place,
                                ords.ordinal(self.series['StatePlace'].item()),
                                self.series['State'].item())
                if amount == 0:
                    message = message + 'Place in state is unchanged; still {} in {}. '\
                        .format(ords.ordinal(self.series['StatePlace'].item()),
                                self.series['State'].item())

        self.post = True
        self.message = message
