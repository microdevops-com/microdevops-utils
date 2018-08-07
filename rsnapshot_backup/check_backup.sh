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

OK_COUNT_FILE=/opt/sysadmws/rsnapshot_backup/check_backup_ok_count.txt
ERRORS_COUNT_FILE=/opt/sysadmws/rsnapshot_backup/check_backup_error_count.txt
echo "0" > $OK_COUNT_FILE
echo "0" > $ERRORS_COUNT_FILE

/opt/sysadmws/rsnapshot_backup/check_rsnapshot_backup_no_compress_files.sh $1
/opt/sysadmws/rsnapshot_backup/check_dot_backup.sh $1 $2
/opt/sysadmws/rsnapshot_backup/check_file_age.sh $1 $2
/opt/sysadmws/rsnapshot_backup/check_mysql.sh $1 $2
/opt/sysadmws/rsnapshot_backup/check_postgresql.sh $1 $2

if [ "$1" == "1" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e "NOTICE: Script finished"
fi

if [ "`cat $OK_COUNT_FILE`" == "0" ] && [ "`cat $ERRORS_COUNT_FILE`" == "0" ]; then
        date '+%F %T ' | tr -d '\n'
        echo "WARNING: Zero checks made"
else
        date '+%F %T ' | tr -d '\n'
        echo -n "RESULT: Successful checks made: "
        cat $OK_COUNT_FILE
        date '+%F %T ' | tr -d '\n'
        echo -n "RESULT: Errors during checks: "
        cat $ERRORS_COUNT_FILE
fi
