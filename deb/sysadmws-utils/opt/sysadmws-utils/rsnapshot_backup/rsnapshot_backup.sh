#!/bin/bash

# Check AWK version
if [ `awk --version | head -1 | sed -e 's/GNU Awk //' -e 's/\..*//'` -lt 4 ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: AWK version above or equal 4 is required"
	exit 1
fi

# Check run syntax
if [ "$1" = "" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: Use rsnapshot_backup.sh TYPE [LINE] [VERBOSITY]"
	echo -e >&2 "ERROR: TYPE = sync, daily, weekly, monthly (sync_first enabled)"
	echo -e >&2 "ERROR: LINE = run sync only for config file line number LINE (including comments)"
	echo -e >&2 "ERROR: If LINE is empty - run all lines"
	echo -e >&2 "ERROR: If VERBOSITY = 1 - show progress of rsync, if empty or other - do not show"
	exit 1
fi
if [ "$1" != "sync" ]; then
	if [ "$2" != "" ]; then
		date '+%F %T ' | tr -d '\n'
		echo -e >&2 "ERROR: LINE can only be used with sync TYPE"
		exit 1
	fi
fi


# Exit if lock exists (prevent multiple execution)
LOCK_DIR=/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.lock

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

CONF_FILE=/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf

if [ -f $CONF_FILE ]; then
	awk -f /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.awk -v rsnapshot_type=$1 -v config_line=$2 -v verbosity=$3 $CONF_FILE 2>&1
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Script finished"
	exit $?
fi	
