#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)
DATE=$(date '+%F %T')
declare -A DISK_ALERT_CRITICAL
declare -A DISK_ALERT_PREDICT_CRITICAL
# Seconds since unix epoch
TIMESTAMP=$(date '+%s')

# Include config
. /opt/sysadmws-utils/disk_alert/disk_alert.conf

# Check defaults
if [[ _$DISK_ALERT_FILTER != "_" ]]; then
	FILTER=$DISK_ALERT_FILTER
else
	FILTER="^Filesystem|tmpfs|cdrom|none"
fi
if [[ _$DISK_ALERT_HISTORY_SIZE != "_" ]]; then
	HISTORY_SIZE=$DISK_ALERT_HISTORY_SIZE
else
	HISTORY_SIZE="2016"
fi

# Make history dir
mkdir -p "/opt/sysadmws-utils/disk_alert/history"

# Check df space
df -PH | grep -vE $FILTER | awk '{ print $5 " " $1 }' | while read output; do
	USEP=$(echo $output | awk '{ print $1}' | cut -d'%' -f1  )
	PARTITION=$(echo $output | awk '{ print $2 }' )
	# Get thresholds
	if [[ _${DISK_ALERT_CRITICAL[$PARTITION]} != "_" ]]; then
		CRITICAL=${DISK_ALERT_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_CRITICAL != "_" ]]; then
		CRITICAL=$DISK_ALERT_DEFAULT_CRITICAL
	else
		CRITICAL="95"
	fi
	if [[ _${DISK_ALERT_PREDICT_CRITICAL[$PARTITION]} != "_" ]]; then
		PREDICT_CRITICAL=${DISK_ALERT_PREDICT_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_PREDICT_CRITICAL != "_" ]]; then
		PREDICT_CRITICAL=$DISK_ALERT_DEFAULT_PREDICT_CRITICAL
	else
		PREDICT_CRITICAL="86400"
	fi
	# Critical message
	if [[ $USEP -ge $CRITICAL ]]; then
		echo '{"host": "'$HOSTNAME'", "date": "'$DATE'", "type": "disk alert", "message": "disk free space critical", "partition": "'$PARTITION'", "use": "'$USEP'%", "threshold": "'$CRITICAL'%"}' | /opt/sysadmws-utils/notify_devilry/notify_devilry.py
	fi
	# Add partition usage history by seconds from unix epoch
	PARTITION_FN=$(echo $PARTITION | sed -e 's#/#_#g')
	echo "$TIMESTAMP	$USEP" >> "/opt/sysadmws-utils/disk_alert/history/$PARTITION_FN.txt"
	# Leave only last N lines in file
	tail -n $HISTORY_SIZE "/opt/sysadmws-utils/disk_alert/history/$PARTITION_FN.txt" > "/opt/sysadmws-utils/disk_alert/history/$PARTITION_FN.txt.new"
	mv -f "/opt/sysadmws-utils/disk_alert/history/$PARTITION_FN.txt.new" "/opt/sysadmws-utils/disk_alert/history/$PARTITION_FN.txt"
	# Get linear regression json
	LR=$(awk -f /opt/sysadmws-utils/disk_alert/lr.awk --assign timestamp="$TIMESTAMP" "/opt/sysadmws-utils/disk_alert/history/$PARTITION_FN.txt" 2>/dev/null)
	if [[ _$LR == "_" ]]; then
		P_ANGLE="None"
		P_SHIFT="None"
		P_QUALITY="None"
		PREDICT_SECONDS="None"
		P_HMS="None"
	else
		# Get predict seconds value
		export PYTHONIOENCODING=utf8
		P_ANGLE=$(echo "$LR" | python -c "import sys, json; print json.load(sys.stdin)['angle']")
		P_SHIFT=$(echo "$LR" | python -c "import sys, json; print json.load(sys.stdin)['shift']")
		P_QUALITY=$(echo "$LR" | python -c "import sys, json; print json.load(sys.stdin)['quality']")
		PREDICT_SECONDS=$(echo "$LR" | python -c "import sys, json; print json.load(sys.stdin)['predict seconds']")
		P_HMS=$(echo "$LR" | python -c "import sys, json; print json.load(sys.stdin)['predict hms']")
	fi
	# Critical predict message
	if [[ $PREDICT_SECONDS != "None" ]]; then
		if [[ $PREDICT_SECONDS -lt $PREDICT_CRITICAL ]]; then
			if [[ $PREDICT_SECONDS -gt 0 ]]; then
				echo '{"host": "'$HOSTNAME'", "date": "'$DATE'", "type": "disk alert", "message": "disk free space prediction critical", "partition": "'$PARTITION'", "use": "'$USEP'%", "angle": "'$P_ANGLE'", "shift": "'$P_SHIFT'", "quality": "'$P_QUALITY'", "predict seconds": "'$PREDICT_SECONDS'", "predict hms": "'$P_HMS'", "prediction threshold": "'$PREDICT_CRITICAL'"}' | /opt/sysadmws-utils/notify_devilry/notify_devilry.py
			fi
		fi
	fi
done
