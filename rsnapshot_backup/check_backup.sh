#!/bin/bash

# Check AWK version
if [ `awk --version | head -1 | sed -e 's/GNU Awk //' -e 's/\..*//'` -lt 4 ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: AWK version above or equal 4 is required"
	exit 1
fi

# Check run syntax
if [ "$1" != "0" ] && [ "$1" != "1" ] && [ "$1" != "2" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: Use $0 0|1|2 [HOSTNAME]"
	echo -e >&2 "ERROR: 0 to show only basic notices, 1 to show all notices and stats, 2 to show basic notices and stats"
	echo -e >&2 "ERROR: HOSTNAME is optional to check specific host backups only"
	exit 1
fi

date '+%F %T ' | tr -d '\n'
echo "NOTICE: Hostname: $(hostname -f)"

# Exit if lock exists (prevent multiple execution)
LOCK_DIR=/opt/sysadmws/rsnapshot_backup/check_backup.lock

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
OK_COUNT_FILE=/opt/sysadmws/rsnapshot_backup/check_backup_ok_count.txt
ERROR_COUNT_FILE=/opt/sysadmws/rsnapshot_backup/check_backup_error_count.txt
GRAND_EXIT=0
echo "0" > $OK_COUNT_FILE
echo "0" > $ERROR_COUNT_FILE

# Check no-compress files
if find /opt/sysadmws/rsnapshot_backup -name 'no-compress_*' | grep -q no-compress; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "WARNING: rsnapshot_backup/no-compress_ files found, consider adding --no-compress param and clean those files out"
	GRAND_EXIT=1
fi 

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
		ROW_RUN_ARGS=$(echo ${CONF_ROW} | jq -r '.run_args')
		ROW_CONNECT_USER=$(echo ${CONF_ROW} | jq -r '.connect_user')
		ROW_CONNECT_PASSWD=$(echo ${CONF_ROW} | jq -r '.connect_password')
		ROW_CHECKS=$(echo ${CONF_ROW} | jq -r '.checks')
		# If item number in $2 - skip everything but needed
		if [ "$2" != "" ]; then
			if [ "$2" != "${ROW_HOST}" ]; then
				continue
			fi
		fi
		# Get checks and run corresponding script for every check found
		if [ "${ROW_CHECKS}" != "null" ]; then
			echo ${CONF_ROW} | jq -r '.checks' > /opt/sysadmws/rsnapshot_backup/check_backup_checks.tmp
			for CHECK in $(cat /opt/sysadmws/rsnapshot_backup/check_backup_checks.tmp | jq -c '.[]'); do
				CHECK_TYPE=$(echo ${CHECK} | jq -r '.type')
				if [ "${CHECK_TYPE}" == ".backup" ]; then
					# No data need to be read by awk, so send just null
					echo "null" | awk -f /opt/sysadmws/rsnapshot_backup/check_dot_backup.awk \
						-v show_notices=$1 \
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
						-v row_run_args=${ROW_RUN_ARGS} \
						-v row_connect_user=${ROW_CONNECT_USER} \
						-v row_connect_passwd=${ROW_CONNECT_PASSWD}
					# Exit code depends on rows
					if [ $? -gt 0 ]; then
						GRAND_EXIT=1
					fi
				elif [ "${CHECK_TYPE}" == "s3/.backup" ]; then
					CHECK_S3_BUCKET=$(echo ${CHECK} | jq -r '.s3_bucket')
					CHECK_S3_PATH=$(echo ${CHECK} | jq -r '.s3_path')
					# No data need to be read by awk, so send just null
					echo "null" | awk -f /opt/sysadmws/rsnapshot_backup/check_s3_dot_backup.awk \
						-v show_notices=$1 \
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
						-v row_run_args=${ROW_RUN_ARGS} \
						-v row_connect_user=${ROW_CONNECT_USER} \
						-v row_connect_passwd=${ROW_CONNECT_PASSWD} \
						-v check_s3_bucket=${CHECK_S3_BUCKET} \
						-v check_s3_path=${CHECK_S3_PATH}
					# Exit code depends on rows
					if [ $? -gt 0 ]; then
						GRAND_EXIT=1
					fi
				elif [ "${CHECK_TYPE}" == "FILE_AGE" ]; then
					CHECK_MIN_FILE_SIZE=$(echo ${CHECK} | jq -r '.min_file_size')
					CHECK_FILE_TYPE=$(echo ${CHECK} | jq -r '.file_type')
					CHECK_LAST_FILE_AGE=$(echo ${CHECK} | jq -r '.last_file_age')
					CHECK_FILES_TOTAL=$(echo ${CHECK} | jq -r '.files_total')
					CHECK_FILES_MASK=$(echo ${CHECK} | jq -r '.files_mask')
					# No data need to be read by awk, so send just null
					echo "null" | awk -f /opt/sysadmws/rsnapshot_backup/check_file_age.awk \
						-v show_notices=$1 \
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
						-v row_run_args=${ROW_RUN_ARGS} \
						-v row_connect_user=${ROW_CONNECT_USER} \
						-v row_connect_passwd=${ROW_CONNECT_PASSWD} \
						-v check_min_file_size=${CHECK_MIN_FILE_SIZE} \
						-v check_file_type=${CHECK_FILE_TYPE} \
						-v check_last_file_age=${CHECK_LAST_FILE_AGE} \
						-v check_files_total=${CHECK_FILES_TOTAL} \
						-v check_files_mask=${CHECK_FILES_MASK}
					# Exit code depends on rows
					if [ $? -gt 0 ]; then
						GRAND_EXIT=1
					fi
				elif [ "${CHECK_TYPE}" == "POSTGRESQL" -o "${CHECK_TYPE}" == "MYSQL" ]; then
					if [ "${CHECK_TYPE}" == "POSTGRESQL" ]; then
						DB_LIST_PATH="postgresql/db_list.txt"
						AWK_SCRIPT="check_postgresql.awk"
					fi
					if [ "${CHECK_TYPE}" == "MYSQL" ]; then
						DB_LIST_PATH="mysql/db_list.txt"
						AWK_SCRIPT="check_mysql.awk"
					fi
					# Get empty_db
					echo ${CHECK} | jq -r '.empty_db' | jq -c '.[]' | sed -e 's/^"//' -e 's/"$//' > /opt/sysadmws/rsnapshot_backup/check_backup_check_empty_db.tmp
					# Expand db_list.txt for ALL
					if [ "${ROW_SOURCE}" == "ALL" ]; then
						if [ ! -f "${ROW_PATH}/.sync/rsnapshot/var/backups/${DB_LIST_PATH}" ]; then
							echo -e >&2 "ERROR: ${ROW_PATH}/.sync/rsnapshot/var/backups/${DB_LIST_PATH} not found on ALL source"
							GRAND_EXIT=1
						else
							for DB_NAME in $(cat "${ROW_PATH}/.sync/rsnapshot/var/backups/${DB_LIST_PATH}"); do
								# Check for db name in empty db list and if not only then run script
								if ! grep -q -e "^${DB_NAME}$" /opt/sysadmws/rsnapshot_backup/check_backup_check_empty_db.tmp; then
									# No data need to be read by awk, so send just null
									echo "null" | awk -f /opt/sysadmws/rsnapshot_backup/${AWK_SCRIPT} \
										-v show_notices=$1 \
										-v row_db_sub_name=${DB_NAME} \
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
										-v row_run_args=${ROW_RUN_ARGS} \
										-v row_connect_user=${ROW_CONNECT_USER} \
										-v row_connect_passwd=${ROW_CONNECT_PASSWD}
									# Exit code depends on rows
									if [ $? -gt 0 ]; then
										GRAND_EXIT=1
									fi
								fi
							done
						fi
					else
						# No data need to be read by awk, so send just null
						echo "null" | awk -f /opt/sysadmws/rsnapshot_backup/${AWK_SCRIPT} \
							-v show_notices=$1 \
							-v row_db_sub_name=${ROW_SOURCE} \
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
							-v row_run_args=${ROW_RUN_ARGS} \
							-v row_connect_user=${ROW_CONNECT_USER} \
							-v row_connect_passwd=${ROW_CONNECT_PASSWD}
						# Exit code depends on rows
						if [ $? -gt 0 ]; then
							GRAND_EXIT=1
						fi
					fi
					rm -f /opt/sysadmws/rsnapshot_backup/check_backup_check_empty_db.tmp
				else
					date '+%F %T ' | tr -d '\n'
					echo -e >&2 "ERROR: Check script for type ${CHECK_TYPE} not found"
					GRAND_EXIT=1
				fi
			done
			rm -f /opt/sysadmws/rsnapshot_backup/check_backup_checks.tmp
		fi
	done
	if [ "`cat $OK_COUNT_FILE`" == "0" ] && [ "`cat $ERROR_COUNT_FILE`" == "0" ]; then
		date '+%F %T ' | tr -d '\n'
		echo "WARNING: Zero checks made"
		GRAND_EXIT=1
	else
		date '+%F %T ' | tr -d '\n'
		echo -n "RESULT: Successful checks made: "
		cat $OK_COUNT_FILE
		date '+%F %T ' | tr -d '\n'
		echo -n "RESULT: Errors during checks: "
		cat $ERROR_COUNT_FILE
		if [ "`cat $ERROR_COUNT_FILE`" != "0" ]; then
			GRAND_EXIT=1
		fi
	fi
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Script finished"
	exit $GRAND_EXIT
else
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "WARNING: There is no $CONF_FILE config file on backup server"
        exit 1
fi	
