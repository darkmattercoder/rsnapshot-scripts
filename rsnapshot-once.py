#!/usr/bin/python3

#########################################################################################
# rsnapshot-once python                                                                 #
# Copyright (C) 2017 Jochen Bauer <devel@jochenbauer.net>                               #
#########################################################################################
# Wrapper script for rsnapshot. Based on the php version of rsnapshot-once by
# Philipp Heckel.
#
# Original blog post at:
# http://blog.philippheckel.com/2013/06/28/script-run-rsnapshot-backups-only-once-and-rollback-failed-backups-using-rsnapshot-once/
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
            Usage:
            rsnapshot-once [-c CFGFILE] (sync|hourly [<N>]|daily|weekly|monthly)
            rsnapshot-once -h

            Options:
            -c CFGFILE      specify the configfile that rsnapshot should use
                            [default: /etc/rsnapshot.conf]
            -h              display help

           By passing the <N> argument with hourly, you can adjust the hourly intervals. Defaults
           to 6 if not given, meaning every 4 hours. This script will, as it is designed for now,
           run in systemd environments. You can use it in non systemd environments by removing or
           adjusting the wakeup-part.
"""

import os.path
import logging
import sys
import re
import datetime
import subprocess

from time import strftime
from shutil import rmtree
from systemd import journal
from docopt import docopt
from natsort import versorted

RSNAPSHOT_BINARY = "/usr/local/bin/rsnapshot"

def logf(logstring, logfile=None, prefix=""):
	'''Logs in rsnapshot's logfile when existing'''
	if logfile:
		logstring = prefix + logstring
		try:
			with open(logfile, 'a') as lf:
				lf.write(logstring + "\n")
		except FileNotFoundError:
			logging.critical("Specified logfile does not exist")
	logging.info("Writing to logfile: "+logstring)
	return True

def logft(logstring, logfile=None, prefix=""):
	'''Logs with timestamp'''
	logstring = strftime("[%d/%b/%Y:%H:%M:%S] ") + logstring
	logf(logstring, logfile, prefix)
	return True

def abortlog(logfile):
		'''Logs aborting the script'''
		logft("## BACKUP ABORTED #######################\n", logfile)

def uptime():
	'''Gets the machine uptime from /proc'''
	with open('/proc/uptime', 'r') as procUptime:
		uptime_seconds = float(procUptime.readline().split()[0])
		return uptime_seconds

def removepid(pidfile, logfile=None, prefix=""):
	'''removes the pidfile of rsnapshot-once'''
	logft("Removing rsnapshot-once pidfile at "+pidfile+" (CLEAN EXIT).", logfile, prefix)
	os.remove(pidfile)

def parseConfig(configpath, configfile):
	'''recursively parses the rsnapshot configs'''
	abspath = configpath+"/"+configfile
	logfile = None
	syncFirst = None
	snapshotRoot = None
	with open(abspath, "r") as cf:
		for line in cf:
			if line.lower().startswith("include_conf"):
				referencedpath = os.path.split(line.strip().split("\t")[1])[0]
				referencedfile = os.path.split(line.strip().split("\t")[1])[1]
				if not os.path.isabs(referencedpath):
					logft("referenced file is given by relative path. This might lead to errors depending on where this script has been invoked from", LOGFILE)
					referencedpath = configpath +"/"+ referencedpath
				logft("referenced file: "+referencedpath+"/"+referencedfile, LOGFILE)
				lf, sf, sr = parseConfig(referencedpath, referencedfile)
				if lf != None:
					logfile = lf
				if sf != None:
					syncFirst = sf
				if sr != None:
					snapshotRoot = sr
			if line.lower().startswith("logfile"):
				logfile = line.strip().split("\t")[1]
			if line.lower().startswith("snapshot_root"):
				snapshotRoot = line.strip().split("\t")[1]
				if snapshotRoot.strip()[-1] != "/":
					snapshotRoot = None
					logft("Snapshot has no trailing slash", logfile)
			if line.lower().startswith("sync_first"):
				syncFirst = line.strip().split("\t")[1]
				logging.debug("Syncfirst: "+syncFirst)
			if syncFirst == 1:
				break
	logging.debug("return: " + " " + str(logfile) + " " + str(syncFirst) + " " + str(snapshotRoot))
	return logfile, syncFirst, snapshotRoot

ARGS = docopt(__doc__, version='0.0.1-alpha')

logging.basicConfig(stream=sys.stdout, level=logging.INFO, formatter=logging.BASIC_FORMAT)
logging.debug("Parsed arguments:\n" + str(ARGS))

# getting snapshotroot and logfile
SNAPSHOT_ROOT = None
LOGFILE = None
SYNC_FIRST = None
CONFIGFILE = ARGS.get("-c")
CONFIGPATH = os.path.split(os.path.abspath(CONFIGFILE))[0]
CONFIGFILE = os.path.split(os.path.abspath(CONFIGFILE))[1]
logft("Configpath: "+CONFIGPATH)
try:
	LOGFILE, SYNC_FIRST, SNAPSHOT_ROOT = parseConfig(CONFIGPATH, CONFIGFILE)
	if not LOGFILE:
		logft("No logfile entry in settings file. Is this intended?", LOGFILE)
except FileNotFoundError:
	logft("Specified settings file does not exist", LOGFILE)
	raise SystemExit(-1)

if SYNC_FIRST == "1":
	logft("Rsnapshot is configured to use sync_fist. This is not supported for now.", LOGFILE)
	abortlog(LOGFILE)
	raise SystemExit(-1)

if not SNAPSHOT_ROOT:
	logft("No valid snapshot root entry in settings file. Aborting", LOGFILE)
	abortlog(LOGFILE)
	raise SystemExit(-1)

logft("## STARTING BACKUP ######################", LOGFILE)

# get command
COMMAND = None
for k, v in ARGS.items():
	if isinstance(v, bool) and v:
		COMMAND = k
if COMMAND != "sync":
	# Check pid file
	PIDFILE = SNAPSHOT_ROOT + ".rsnapshot-once.pid"
	logft("Checking rsnapshot-once pidfile at " + PIDFILE + " ... ", LOGFILE)
	try:
		with open(PIDFILE) as pf:
			pid = pf.read().strip()
			if os.path.isfile("/proc/" + pid):
				logf("Process " + pid + " still running. Aborting", LOGFILE)
				abortlog(LOGFILE)
				raise SystemExit(-1)
			logf("PID file exists but process " + pid + " is not running. Script crashed before", LOGFILE)
			sortedBackups = []
			for entry in os.listdir(SNAPSHOT_ROOT):
				if COMMAND in entry:
					sortedBackups.append(entry)
			# hack for sorting with natsort 3.5.1: User versorted to handle the dot
			sortedBackups = versorted(sortedBackups)
			sortedBackupsCount = len(sortedBackups)
			if sortedBackupsCount == 0:
				logft("No previous backups found. No cleanup necessary.", LOGFILE)
			else:
				logft("Cleaning up unfinished backup ...", LOGFILE)
				firstBackup = sortedBackups.pop(0)
				logft("Deleting " + firstBackup + " ...", LOGFILE)

				# double check before deleting (!)
				regExpMatches = re.search(r'^(.+)\.(\d+)$', firstBackup)
				if not os.path.isdir(SNAPSHOT_ROOT + firstBackup) or len(firstBackup) < 2 or not regExpMatches:
					logf("Script security issue. EXITING.", LOGFILE)
					abortlog(LOGFILE)
					raise SystemExit(-1)
				else:
					# Delete
					try:
						rmtree(SNAPSHOT_ROOT + firstBackup)
						logf("Done", LOGFILE)
					except:
						logft("Unexpected error " + str(sys.exc_info()[0]) + " on deleting " + SNAPSHOT_ROOT + firstBackup, LOGFILE)
						raise SystemExit(-1)
					sortedBackupsCount = len(sortedBackups)
					while sortedBackupsCount > 0:
						backup = sortedBackups.pop(0)
						sortedBackupsCount = len(sortedBackups)
						#logging.debug("Backup: "+backup)
						regExpMatches = re.search(r"^(.+)\.(\d+)$", backup)
						if regExpMatches:
							#logging.debug("M: "+str(m))
							#logging.debug("M1: " + regExpMatches.group(1)+" M2: "+regExpMatches.group(2))
							#logging.debug("Prev: "+previousBackup)
							previousBackup = regExpMatches.group(1)+"."+str(int(regExpMatches.group(2))-1)
							logft("Moving "+backup+" to " +previousBackup+" ... ")
							try:
								os.rename(SNAPSHOT_ROOT+backup, SNAPSHOT_ROOT+previousBackup)
								logft("DONE", LOGFILE)
							except OSError:
								logft("Could not rename directory. Target already exists")
								abortlog(LOGFILE)
								raise SystemExit(-1)
	except FileNotFoundError:
		logft("Does not exist. Last backup was clean.", LOGFILE)

	logft("Checking delays (minimum 15 minutes since startup/wakeup) ...", LOGFILE)
	upMinutes = int(uptime()//60)
	if upMinutes < 15:
		logft("- Computer uptime is "+str(upMinutes)+" minutes. NOT ENOUGH. EXITING.", LOGFILE)
		abortlog(LOGFILE)
		raise SystemExit(-1)
	else:
		logft("- Computer uptime is "+str(upMinutes)+" minutes. THAT'S OKAY.", LOGFILE)

	# Get time of resume from systemd journal
	j = journal.Reader()
	j.this_boot()
	j.add_match(SYSLOG_IDENTIFIER="systemd-sleep")
	j.seek_tail()
	ENTRY = j.get_previous()
	WAKEUPMINUTES = None
	if ENTRY:
		while ENTRY["MESSAGE"] != "System resumed.":
			ENTRY = j.get_previous()
			if not ENTRY:
				break
		if ENTRY:
			timediff = datetime.datetime.now() - ENTRY["__REALTIME_TIMESTAMP"]
			WAKEUPMINUTES = timediff.seconds // 60
	if WAKEUPMINUTES:
		if WAKEUPMINUTES < 15:
			logft("- Computer wakeup time is "+str(WAKEUPMINUTES)+" minutes. NOT ENOUGH. EXITING.", LOGFILE)
			abortlog(LOGFILE)
			raise SystemExit(-1)
		else:
			logft("- Computer wakeup time is "+str(WAKEUPMINUTES)+" minutes. THAT'S OKAY.", LOGFILE)

	# Get date of newest folder (e.g. weekly.0, daily.0, monthly.0)
	# to figure out if the job needs to run
	NEEDSTORUN = False
	NEWESTBACKUP = SNAPSHOT_ROOT + COMMAND + ".0"
	if not os.path.isdir(NEWESTBACKUP):
		logft("No backup exists for job "+COMMAND+" at "+NEWESTBACKUP, LOGFILE)
		NEEDSTORUN = True
	else:
		BACKUPTIME = datetime.datetime.fromtimestamp(os.path.getmtime(NEWESTBACKUP))
		logft("Last backup for job "+COMMAND+" at "+NEWESTBACKUP+" was at "+str(BACKUPTIME), LOGFILE)
		TIMESINCELAST = None
		TIMEMIN = None
		if COMMAND == "hourly":
			intervalsPerDay = ARGS.get("<N>")
			if intervalsPerDay is None:
				intervalsPerDay = 6 # the default
			if int(intervalsPerDay) > 24 or int(intervalsPerDay) < 2:
				logft("Invalid interval for hourly given. Must be between 2 and 24. Aborting.", LOGFILE)
				abortlog(LOGFILE)
				raise SystemExit
			TIMEMIN = datetime.timedelta(minutes=(24/intervalsPerDay)*60-5)
		elif COMMAND == "daily":
			TIMEMIN = datetime.timedelta(hours=23)
		elif COMMAND == "weekly":
			TIMEMIN = datetime.timedelta(days=6.5)
		elif COMMAND == "monthly":
			TIMEMIN = datetime.timedelta(days=29)
		else:
			logft("Error: This should not happen. ERROR.", LOGFILE)
			abortlog(LOGFILE)
			raise SystemExit(-1)

		TIMESINCELAST = (datetime.datetime.now() - BACKUPTIME)
		NEEDSTORUN = TIMESINCELAST > TIMEMIN
		logging.debug("Time since last: "+str(TIMESINCELAST))
		logging.debug("Mintime: "+str(TIMEMIN))

		if not NEEDSTORUN:
			logft("Job does NOT need to run. Last run is only "+str(TIMESINCELAST)+" ago (min. is "+str(TIMEMIN)+") EXITING.", LOGFILE)
			abortlog(LOGFILE)
			raise SystemExit
		else:
			logft("Last run is "+str(TIMESINCELAST)+" ago (min. is "+str(TIMEMIN)+")", LOGFILE)
	PID = os.getpid()
	logft("Writing rsnapshot-once pidfile (PID "+str(PID)+") to "+PIDFILE)
	with open(PIDFILE, "w") as pf:
		pf.write(str(PID))

	SYSCMD = RSNAPSHOT_BINARY+" -c "+ARGS.get("-c")+" "+COMMAND
	logft("NOW RUNNING JOB: "+SYSCMD+"\n", LOGFILE)
	SYSCMD = SYSCMD.split(" ")
	EXITCODE = 0
	CONFIGERROR = False
	COMPLETEPROCESS = None
	try:
		COMPLETEPROCESS = subprocess.check_output(SYSCMD, universal_newlines=True, stderr=subprocess.STDOUT)
	except subprocess.CalledProcessError as retVal:
		EXITCODE = retVal.returncode
		COMPLETEPROCESS = retVal.output

	for index, LINE in enumerate(COMPLETEPROCESS.split("\n")):
		if index == 0:
			logft(" captured output: "+LINE,LOGFILE,"\n")
		else:
			logft(" captured output: "+LINE,LOGFILE)
		#logging.info(" captured output: "+LINE)
		if "rsnapshot encountered an error" in LINE:
			CONFIGERROR = True

	if CONFIGERROR:
		logft("Exiting rsnapshot-once, because error in rsnapshot config detected.", LOGFILE, "\n")
		removepid(PIDFILE, LOGFILE)
		abortlog(LOGFILE)
		raise SystemExit(-1)

	# pidfile should NOT exist if exit was clean
	if EXITCODE == 1: # 1 means 'fatal error' in rsnapshot terminology
		logft("No clean exit. Backup aborted. Cleanup necessary on next run (DIRTY EXIT).", LOGFILE, "\n")
		abortlog(LOGFILE)
		raise SystemExit(-1)
	elif EXITCODE == 2: # 2 means that warnings ocurred
		logft("Rsnapshot encountered warnings, this is worth a look at the log file", LOGFILE, "\n")

	removepid(PIDFILE, LOGFILE, "\n")
	logft("## BACKUP COMPLETE ######################\n", LOGFILE)
else:
	# sync is not supported in this context
	logft("Sync is not supported as command", LOGFILE)
	abortlog(LOGFILE)
	raise SystemExit(-1)
