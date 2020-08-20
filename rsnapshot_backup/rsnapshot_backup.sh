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
	echo -e >&2 "ERROR: Use rsnapshot_backup.sh TYPE [JSON LIST ITEM NUMBER | HOST] [VERBOSITY]"
	echo -e >&2 "ERROR: TYPE = sync, hourly, daily, weekly, monthly (sync_first enabled)"
	echo -e >&2 "ERROR: JSON LIST ITEM NUMBER = run sync only for item N in the config file"
	echo -e >&2 "ERROR: HOST = run sync only for items with HOST in the config file"
	echo -e >&2 "ERROR: If JSON LIST ITEM NUMBER or HOST is empty - run for all items"
	echo -e >&2 "ERROR: If VERBOSITY = 1 - show progress of rsync, if empty or other - do not show"
	exit 1
fi
if [ "$1" != "sync" ]; then
	if [ "$2" != "" ]; then
		date '+%F %T ' | tr -d '\n'
		echo -e >&2 "ERROR: JSON LIST ITEM NUMBER or HOST can only be used with sync TYPE"
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
	exit 1
fi

CONF_FILE=/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.conf
ERROR_COUNT_FILE=/opt/sysadmws/rsnapshot_backup/rsnapshot_backup_error_count.txt
GRAND_EXIT=0
echo "0" > $ERROR_COUNT_FILE
declare -A ROTATIONS

if [ -f $CONF_FILE ]; then
	ROW_NUMBER=0
	# Loop over conf file items
	IFS=$'\n' # Separate only by newlines
	for CONF_ROW in $(cat ${CONF_FILE} | jq -c '.[]'); do
		# Get values from JSON
		ROW_NUMBER=$((ROW_NUMBER+1))
		ROW_ENABLED=$(echo ${CONF_ROW} | jq -r '.enabled')
		ROW_COMMENT=$(echo ${CONF_ROW} | jq -r '.comment')
		ROW_CONNECT=$(echo ${CONF_ROW} | jq -r '.connect')
		ROW_HOST=$(echo ${CONF_ROW} | jq -r '.host')
		ROW_PATH=$(echo ${CONF_ROW} | jq -r '.path')
		ROW_SOURCE=$(echo ${CONF_ROW} | jq -r '.source')
		ROW_TYPE=$(echo ${CONF_ROW} | jq -r '.type')
		ROW_RETAIN_H=$(echo ${CONF_ROW} | jq -r '.retain_hourly')
		ROW_RETAIN_D=$(echo ${CONF_ROW} | jq -r '.retain_daily')
		ROW_RETAIN_W=$(echo ${CONF_ROW} | jq -r '.retain_weekly')
		ROW_RETAIN_M=$(echo ${CONF_ROW} | jq -r '.retain_monthly')
		ROW_RSYNC_ARGS=$(echo ${CONF_ROW} | jq -r '.rsync_args')
		ROW_MONGO_ARGS=$(echo ${CONF_ROW} | jq -r '.mongo_args')
		ROW_MYSQLDUMP_ARGS=$(echo ${CONF_ROW} | jq -r '.mysqldump_args')
		ROW_CONNECT_USER=$(echo ${CONF_ROW} | jq -r '.connect_user')
		ROW_CONNECT_PASSWD=$(echo ${CONF_ROW} | jq -r '.connect_password')
		ROW_VALIDATE_HOSTNAME=$(echo ${CONF_ROW} | jq -r '.validate_hostname')
		ROW_POSTGRESQL_NOCLEAN=$(echo ${CONF_ROW} | jq -r '.postgresql_noclean')
		ROW_MYSQL_NOEVENTS=$(echo ${CONF_ROW} | jq -r '.mysql_noevents')
		ROW_NATIVE_TXT_CHECK=$(echo ${CONF_ROW} | jq -r '.native_txt_check')
		ROW_NATIVE_10H_LIMIT=$(echo ${CONF_ROW} | jq -r '.native_10h_limit')
		ROW_EXEC_BEFORE_RSYNC=$(echo ${CONF_ROW} | jq -r '.exec_before_rsync')
		ROW_EXEC_AFTER_RSYNC=$(echo ${CONF_ROW} | jq -r '.exec_after_rsync')
		# If filter in $2 - skip everything but needed
		if [ "$2" != "" ]; then
			# Check if $2 is a number
			if [[ "$2" =~ ^[0-9]+$ ]]; then
				if [ "$2" -ne "${ROW_NUMBER}" ]; then
					continue
				fi
			else
				if [ "$2" != "${ROW_HOST}" ]; then
					continue
				fi
			fi
		fi
		# For rotation items (!= sync) - do a rotation only once per path (ROW_PATH)
		if [ "$1" != "sync" ]; then
			if [ "_${ROTATIONS[${ROW_PATH}]}" == "_done" ]; then
				date '+%F %T ' | tr -d '\n'
				echo -e >&2 "NOTICE: Rotation for ${ROW_PATH} has been already made, skipping"
				continue
			else
				ROTATIONS[${ROW_PATH}]="done"
			fi
		fi
		# No data need to be read by awk, so send just null
		echo "null" | awk -b -f /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.awk \
			-v rsnapshot_type=$1 \
			-v verbosity=$3 \
			-v row_number=${ROW_NUMBER} \
			-v row_enabled=${ROW_ENABLED} \
			-v row_comment=${ROW_COMMENT} \
			-v row_connect=${ROW_CONNECT} \
			-v row_host=${ROW_HOST} \
			-v row_path=${ROW_PATH} \
			-v row_source=${ROW_SOURCE} \
			-v row_type=${ROW_TYPE} \
			-v row_retain_h=${ROW_RETAIN_H} \
			-v row_retain_d=${ROW_RETAIN_D} \
			-v row_retain_w=${ROW_RETAIN_W} \
			-v row_retain_m=${ROW_RETAIN_M} \
			-v row_rsync_args=${ROW_RSYNC_ARGS} \
			-v row_mongo_args=${ROW_MONGO_ARGS} \
			-v row_mysqldump_args=${ROW_MYSQLDUMP_ARGS} \
			-v row_connect_user=${ROW_CONNECT_USER} \
			-v row_connect_passwd=${ROW_CONNECT_PASSWD} \
			-v row_validate_hostname=${ROW_VALIDATE_HOSTNAME} \
			-v row_postgresql_noclean=${ROW_POSTGRESQL_NOCLEAN} \
			-v row_mysql_noevents=${ROW_MYSQL_NOEVENTS} \
			-v row_native_txt_check=${ROW_NATIVE_TXT_CHECK} \
			-v row_native_10h_limit=${ROW_NATIVE_10H_LIMIT} \
			-v row_exec_before_rsync=${ROW_EXEC_BEFORE_RSYNC} \
			-v row_exec_after_rsync=${ROW_EXEC_AFTER_RSYNC}
		# Exit code depends on rows
		if [ $? -gt 0 ]; then
			GRAND_EXIT=1
		fi
	done
	if [ "`cat $ERROR_COUNT_FILE`" != "0" ]; then
		date '+%F %T ' | tr -d '\n'
		echo -n "RESULT: Errors occuried: "
		cat $ERROR_COUNT_FILE
		GRAND_EXIT=1
	fi
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Script finished"
	exit $GRAND_EXIT
else
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "WARNING: There is no $CONF_FILE config file on backup server"
        exit 1
fi	
