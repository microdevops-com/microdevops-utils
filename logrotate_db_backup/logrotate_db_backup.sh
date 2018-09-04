#!/bin/bash

# Check AWK version
if [ `awk --version | head -1 | sed -e 's/GNU Awk //' -e 's/\..*//'` -lt 4 ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: AWK version above or equal 4 is required"
	exit 1
fi

# Check run syntax
if [ "$1" != "0" ] && [ "$1" != "1" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: Use $0 1 [target_name] to show NOTICE lines or $0 0 [target_name] to skip them, [target_name] is optional"
	exit 1
fi

# Exit if lock exists (prevent multiple execution)
LOCK_DIR=/opt/sysadmws/logrotate_db_backup/logrotate_db_backup.lock

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

CONF_FILE=/opt/sysadmws/logrotate_db_backup/logrotate_db_backup.conf

if [ -f $CONF_FILE ]; then
	awk -f /opt/sysadmws/logrotate_db_backup/logrotate_db_backup.awk -v show_notices=$1 -v target_name=$2 $CONF_FILE 2>&1
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Script finished"
	exit $?
fi	
