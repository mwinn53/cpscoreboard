# scoreboard

## description
This scoreboard application allows spectators to monitor the Cyber Patriot 
scoreboard from the perspective of their own team and direct competition 
(i.e., county)

## dependencies
The following system level libraries are required
- libxml2-dev 
- libxslt1-dev
- libfreetype6-dev
- libxft-dev
- python3-tk

The following additional python packages are used:
- pandas
- matplotlib
- bs4
- tweepy

## instructions
Install the app and its dependencies:
` python setup.py install `

The usage is self-documenting: 
~~~~
usage: cpscoreboard.py [-h] [-a ALIAS] [-k KEYS KEYS KEYS KEYS] [-r REFRESH]
                       [-o OUTPUT] [-v]
                       url team
                       
positional arguments:
  url                   URL to the Scoreboard
  team                  Text file of team numbers to track (one per line

optional arguments:
  -h, --help            show this help message and exit
  -a ALIAS, --alias ALIAS
                        CSV file of team numbers and name aliases.
  -k KEYS KEYS KEYS KEYS, --keys KEYS KEYS KEYS KEYS
                        Twitter API Keys (separated by space): ConsumerKey
                        SecretKey AccessToken AccessSecret)
  -r REFRESH, --refresh REFRESH
                        Refresh Interval (default: 60 seconds)
  -o OUTPUT, --output OUTPUT
                        File name for output journal (default: scoreboard.txt
                        in current directory)
  -v, --verbose         Enable verbose logging (e.g., for troubleshooting).
~~~~

The app uses tkinter and matplotlib to generate images of tables (i.e. to post
 to Twitter). If running on a server without a display interface, you might 
 need to set the following environment variables:

~~~~
export DISPLAY=:0.0
export MPLBACKEND="agg"
~~~~