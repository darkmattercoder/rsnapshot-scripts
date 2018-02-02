# rsnapshot-scripts

Collection of scripts to use with rsnapshot

## rsnapshot-once.php

This is a php script that I included here to show where rsnapshot-once.py originated. It was originally written by Philipp Heckel, who announced it in his blog: <http://blog.philippheckel.com/2013/06/28/script-run-rsnapshot-backups-only-once-and-rollback-failed-backups-using-rsnapshot-once/>

## rsnapshot-once.py

_WARNING:_ After extensive testing I cannot recomment the script for productive use. Depending on how your crontab is organized, the weeklys and monthlys will get messy because the script rotates even if not necessary (timestamp check succeeds on the second weekly attempt, even if it was performed tha day before). I do not want to waste a lot of time for debugging purposes,  so I leave it as is for now and changing my crontab (server) to execute each command only once. This fits my needs and I do not have to change thr script anymore.

This is my port of the above script for python. Particularly I made it to run properly with Python version 3.4. I made some additions though.

	Usage:
	rsnapshot-once [-c CFGFILE] (sync|hourly [<N>]|daily|weekly|monthly)
	rsnapshot-once -h

	Options:
	-c CFGFILE      specify the configfile that rsnapshot should use
					[default: /etc/rsnapshot.conf]
	-h              display help

	By passing the <N> argument with hourly, you can adjust the hourly intervals. Defaults to 6 if not given, meaning every 4 hours.
	This script will, as it is designed for now, run in systemd environments. You can use it in non systemd environments by removing or adjusting the wakeup-part.
