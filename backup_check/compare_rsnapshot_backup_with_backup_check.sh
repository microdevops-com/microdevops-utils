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

if [ "$1" -ge "1" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -n "NOTICE: Hostname: "
	salt-call --local grains.item fqdn 2>&1 | tail -n 1 | sed 's/^ *//'
fi

CONF_FILE=/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf
SKIP_FILE=/opt/sysadmws-utils/backup_check/compare_rsnapshot_backup_with_backup_check.skip

if [ -f $SKIP_FILE ]; then
        if [ -f $CONF_FILE ]; then
                if grep -q -v -e "^#" $CONF_FILE; then
                        date '+%F %T ' | tr -d '\n'
                        echo -e >&2 "WARNING: Both skip file $SKIP_FILE and config file $CONF_FILE exist on backup server and config file contains non comment lines"
                        exit 1
                else
                        if [ "$1" -ge "1" ]; then
                                date '+%F %T ' | tr -d '\n'
                                echo -e "NOTICE: Checking skipped as $SKIP_FILE skip file exists on backup server"
                        fi
                        exit 0
                fi
        else
                if [ "$1" -ge "1" ]; then
                        date '+%F %T ' | tr -d '\n'
                        echo -e "NOTICE: Checking skipped as $SKIP_FILE skip file exists on backup server"
                fi
                exit 0
        fi
fi

if [ -f $CONF_FILE ]; then
	awk -f /opt/sysadmws-utils/backup_check/compare_rsnapshot_backup_with_backup_check.awk -v show_notices=$1 -v hostname_filter=$2 $CONF_FILE 2>&1
	exit $?
else
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "WARNING: There is no $CONF_FILE config file on backup server"
        exit 1
fi
