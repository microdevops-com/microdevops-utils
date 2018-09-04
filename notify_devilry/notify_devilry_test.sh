#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)
DATE=$(date '+%F %T')

# Send test
echo '{"host": "'$HOSTNAME'", "from": "notify_devilry_test.sh", "type": "notify devilry test", "status": "OK", "date time": "'$DATE'"}' | /opt/sysadmws/notify_devilry/notify_devilry.py --debug --force-send
