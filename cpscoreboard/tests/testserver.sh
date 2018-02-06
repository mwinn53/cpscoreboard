#!/bin/bash

cp testpage_orig.txt testpage.php

echo "Starting scoreboard app for testing..."
python3.6 ../cpscoreboard.py http://127.0.0.1:8000/testpage.php team -a lookups -r 10 &
read -n 1 -s -r -p "Press any key when ready"

echo "> Waiting 30 seconds to simulate web site initialization."
sleep 30 
echo "Staring web server..."
python3.6 server.py &
read -n 1 -s -r -p "Tail the log and press any key to continue"

F=$(ls -1 *.php | wc -l)
((F--))
for i in $(seq 1 $F); 
do
	echo "Step ${i}..."
	cp "testpage${i}.php" testpage.php
	sleep 30
done

echo "Test complete!"

killall python3.6
