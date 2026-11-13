from setuptools import setup

setup(
    name='cpscoreboard',
    version='0.1b',
    packages=['cpscoreboard',],
    url='https://github.com/mwinn53/cpscoreboard',
    license='',
    author='mwinn',
    author_email='legitbits@protonmail.com',
    description='Cyber Patriot Scoreboard Companion',
    install_requires=['pandas',
                      'matplotlib',
                      'bs4',
                      'requests',
                      'datetime',
                      'tweepy',
                      'inflect',
                      'lxml']
)
