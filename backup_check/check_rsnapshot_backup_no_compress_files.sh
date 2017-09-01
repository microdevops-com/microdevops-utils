#!/bin/bash

# Check run syntax
if [ "$1" != "0" ] && [ "$1" != "1" ] && [ "$1" != "2" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "ERROR: Use $0 0|1|2 [HOSTNAME]"
	echo -e >&2 "ERROR: 0 to show only basic notices, 1 to show all notices and stats, 2 to show basic notices and stats"
        exit 1
fi

if [ "$1" == "1" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -n "NOTICE: Hostname: "
	salt-call --local grains.item fqdn 2>&1 | tail -n 1 | sed 's/^ *//'
fi

if find /opt/sysadmws-utils/rsnapshot_backup -name 'no-compress_*' | grep -q no-compress; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "WARNING: rsnapshot_backup/no-compress_ files found, consider adding --no-compress param to specific rsnapshot_backup.conf lines and clean those files out"
fi 
