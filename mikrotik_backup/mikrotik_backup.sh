#!/bin/bash

# Check run syntax
if [ "$1" != "0" ] && [ "$1" != "1" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: Use $0 1 [target_name] to show NOTICE lines or $0 0 [target_name] to skip them, [target_name] is optional"
	exit 1
fi

# Exit if lock exists (prevent multiple execution)
LOCK_DIR=/opt/sysadmws-utils/mikrotik_backup/mikrotik_backup.lock

if mkdir "$LOCK_DIR"
then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Successfully acquired lock on $LOCK_DIR"
	trap 'rm -rf "$LOCK_DIR"' 0
else
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: Cannot acquire lock, giving up on $LOCK_DIR"
	exit 0
fi

# Exit if no config file
ROUTERS="/opt/sysadmws-utils/mikrotik_backup/mikrotik_backup.conf"
if [ ! -f $ROUTERS ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: $ROUTERS config file not found"
	exit 0
fi	

# Some vars
BACKUPDIR="/var/backups/mikrotik_backup"
# Auto accept ssh fingerprints
SSHBATCH="-o BatchMode=yes -o StrictHostKeyChecking=no"
# Time to kill hanging scp or ssh
TIME_TIMEOUT="300"
# Path to key
ID="/root/.ssh/mktik"
# Run vars
DEBUG=$1
TARGET=$2
# Log file if debug
OUTLOG="/opt/sysadmws-utils/mikrotik_backup/mikrotik_backup.log"
# Empty log file
>$OUTLOG

# Make backup dir
mkdir -p $BACKUPDIR

# Read config file
COMMENTPATTERN="\#*"
mapfile	-t LOGINS < $ROUTERS
let i=0
for l in "${LOGINS[@]}"; do
	# Skip comments
	l=${l%%$COMMENTPATTERN}
	# Skip first spaces
	l=${l%%*( )}
	# Skip last spaces
	l=${l##*( )}
	# Skip empty lines or add normal
	if [[ -z "$l" ]]; then
		unset LOGINS[$i]
	else
		LOGINS[$i]=$l
	fi
	let i++
done

# Do backups while array loop
for LOGIN in "${LOGINS[@]}"; do
	# Use awk to parse columns to vars
	BNAME=$(echo $LOGIN | awk '{print $1}')
	BUSER=$(echo $LOGIN | awk '{print $2}')
	BHOST=$(echo $LOGIN | awk '{print $3}')
	BPORT=$(echo $LOGIN | awk '{print $4}')
	# If taget is set skip everything else, but target
	if [ ! -z $TARGET ] && [ ${TARGET}_ != ${BNAME}_ ]
	then
		continue
	else
		# If debug print everything to terminal
		if [ $DEBUG == "1" ]
		then
			date '+%F %T ' | tr -d '\n'
			echo >&2 "NOTICE: Starting backup: Name: $BNAME, User: $BUSER, Host: $BHOST, Port: $BPORT"
			{ /usr/bin/timeout $TIME_TIMEOUT	/usr/bin/ssh -v	$SSHBATCH -p $BPORT -i $ID $BUSER@$BHOST  "/export compact file=${BNAME}" && \
			/usr/bin/timeout $TIME_TIMEOUT	/usr/bin/scp -v		  -P $BPORT -i $ID $BUSER@$BHOST:/${BNAME}.rsc $BACKUPDIR ; }
			{ /usr/bin/timeout $TIME_TIMEOUT	/usr/bin/ssh -v		  -p $BPORT -i $ID $BUSER@$BHOST  "/system backup save name=${BNAME}" && sleep 2 && \
			/usr/bin/timeout $TIME_TIMEOUT	/usr/bin/scp -v		  -P $BPORT -i $ID $BUSER@$BHOST:/${BNAME}.backup $BACKUPDIR ; }
		# Else redirect to file and more verbosity
		else
			date '+%F %T ' | tr -d '\n' >>$OUTLOG
			echo >&2 "NOTICE: Starting backup: Name: $BNAME, User: $BUSER, Host: $BHOST, Port: $BPORT" >>$OUTLOG
			{ /usr/bin/timeout $TIME_TIMEOUT	/usr/bin/ssh	$SSHBATCH -p $BPORT -i $ID $BUSER@$BHOST  "/export compact file=${BNAME}" && \
			/usr/bin/timeout $TIME_TIMEOUT	/usr/bin/scp		  -P $BPORT -i $ID $BUSER@$BHOST:/${BNAME}.rsc $BACKUPDIR ; } >>$OUTLOG 2>&1
			{ /usr/bin/timeout $TIME_TIMEOUT	/usr/bin/ssh		  -p $BPORT -i $ID $BUSER@$BHOST  "/system backup save name=${BNAME}" && sleep 2 && \
			/usr/bin/timeout $TIME_TIMEOUT	/usr/bin/scp		  -P $BPORT -i $ID $BUSER@$BHOST:/${BNAME}.backup $BACKUPDIR ; } >>$OUTLOG 2>&1
		fi
	fi
done

date '+%F %T ' | tr -d '\n'
echo -e >&2 "NOTICE: Script finished"
