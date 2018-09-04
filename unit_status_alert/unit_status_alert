#!/bin/bash

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi

UNIT=$1
TYPE=$2
HOSTNAME=$3
DATE=$(date '+%F %T')

PROCESS_PID=$(systemctl status $UNIT | grep "Process:" | awk '{print $2}')
MAIN_PID=$(systemctl status $UNIT | grep "Main PID:" | awk '{print $3}')

LOG_ID="$PROCESS_PID"
if [ -z "$PROCESS_PID" ] ; then
        LOG_ID="$MAIN_PID"
fi

LOG_STATUS=$(journalctl -u "$UNIT" _PID="$LOG_ID" -o cat -n 20 --no-pager)
LOG_JSON=$(echo -e '\n'"$LOG_STATUS" | python -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

echo '{"host": "'$HOSTNAME'", "from": "'$UNIT'", "type": "'$TYPE'", "status": "Failed", "date time": "'$DATE'", "log": '${LOG_JSON}'}' | /opt/sysadmws/notify_devilry/notify_devilry.py --force-send
