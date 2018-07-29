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
	echo -e >&2 "ERROR: Use rsnapshot_backup.sh TYPE [JSON LIST ITEM NUMBER] [VERBOSITY]"
	echo -e >&2 "ERROR: TYPE = sync, hourly, daily, weekly, monthly (sync_first enabled)"
	echo -e >&2 "ERROR: JSON LIST ITEM NUMBER = run sync only for item N in the config file"
	echo -e >&2 "ERROR: If JSON LIST ITEM NUMBER is empty - run for all items"
	echo -e >&2 "ERROR: If VERBOSITY = 1 - show progress of rsync, if empty or other - do not show"
	exit 1
fi
if [ "$1" != "sync" ]; then
	if [ "$2" != "" ]; then
		date '+%F %T ' | tr -d '\n'
		echo -e >&2 "ERROR: JSON LIST ITEM NUMBER can only be used with sync TYPE"
		exit 1
	fi
fi


# Exit if lock exists (prevent multiple execution)
LOCK_DIR=/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.lock

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

CONF_FILE=/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.conf

if [ -f $CONF_FILE ]; then
	ROW_NUMBER=0
	# Loop over conf file items
	for CONF_ROW in $(cat ${CONF_FILE} | jq -c '.[]'); do
		# Get values from JSON
		ROW_NUMBER=$((ROW_NUMBER+1))
		ROW_ENABLED=$(echo ${CONF_ROW} | jq -r '.enabled')
		ROW_COMMENT=$(echo ${CONF_ROW} | jq -r '.comment')
		ROW_CONNECT=$(echo ${CONF_ROW} | jq -r '.connect')
		ROW_PATH=$(echo ${CONF_ROW} | jq -r '.path')
		ROW_SOURCE=$(echo ${CONF_ROW} | jq -r '.source')
		ROW_TYPE=$(echo ${CONF_ROW} | jq -r '.type')
		ROW_RETAIN_H=$(echo ${CONF_ROW} | jq -r '.retain_hourly')
		ROW_RETAIN_D=$(echo ${CONF_ROW} | jq -r '.retain_daily')
		ROW_RETAIN_W=$(echo ${CONF_ROW} | jq -r '.retain_weekly')
		ROW_RETAIN_M=$(echo ${CONF_ROW} | jq -r '.retain_monthly')
		ROW_RUN_ARGS=$(echo ${CONF_ROW} | jq -r '.run_args')
		ROW_CONNECT_USER=$(echo ${CONF_ROW} | jq -r '.connect_user')
		ROW_CONNECT_PASSWD=$(echo ${CONF_ROW} | jq -r '.connect_password')
		# If item number in $2 - skip everything but needed
		if [ "$2" != "" ]; then
			if [ "$2" -ne "${ROW_NUMBER}" ]; then
				continue
			fi
		fi
		# No data need to be read by awk, so send just null
		echo "null" | awk -f /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.awk \
			-v rsnapshot_type=$1 \
			-v verbosity=$3 \
			-v row_number=${ROW_NUMBER} \
			-v row_enabled=${ROW_ENABLED} \
			-v row_comment=${ROW_COMMENT} \
			-v row_connect=${ROW_CONNECT} \
			-v row_path=${ROW_PATH} \
			-v row_source=${ROW_SOURCE} \
			-v row_type=${ROW_TYPE} \
			-v row_retain_h=${ROW_RETAIN_H} \
			-v row_retain_d=${ROW_RETAIN_D} \
			-v row_retain_w=${ROW_RETAIN_W} \
			-v row_retain_m=${ROW_RETAIN_M} \
			-v row_run_args=${ROW_RUN_ARGS} \
			-v row_connect_user=${ROW_CONNECT_USER} \
			-v row_connect_passwd=${ROW_CONNECT_PASSWD} \
			2>&1
	done
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Script finished"
	exit $?
fi	
