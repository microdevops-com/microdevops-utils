#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)
DATE=$(date '+%F %T')
declare -A DISK_ALERT_PERCENT_CRITICAL
declare -A DISK_ALERT_FREE_SPACE_CRITICAL
declare -A DISK_ALERT_PREDICT_CRITICAL
# Seconds since unix epoch
TIMESTAMP=$(date '+%s')

# Include config
if [ -f /opt/sysadmws/disk_alert/disk_alert.conf ]; then
	. /opt/sysadmws/disk_alert/disk_alert.conf
fi

# Check defaults
if [[ _$DISK_ALERT_FILTER != "_" ]]; then
	FILTER=$DISK_ALERT_FILTER
else
	FILTER="^Filesystem|tmpfs|cdrom|none|/snap"
fi
#
if [[ _$DISK_ALERT_USAGE_CHECK == "_PERCENT" ]]; then
	USAGE_CHECK="PERCENT"
elif [[ _$DISK_ALERT_USAGE_CHECK == "_FREE_SPACE" ]]; then
	USAGE_CHECK="FREE_SPACE"
else
	USAGE_CHECK="PERCENT"
fi
#
if [[ _$DISK_ALERT_HISTORY_SIZE != "_" ]]; then
	HISTORY_SIZE=$DISK_ALERT_HISTORY_SIZE
else
	HISTORY_SIZE="2016"
fi

# Make history dir
mkdir -p "/opt/sysadmws/disk_alert/history"

# Check df space
df -P -BM | grep -vE $FILTER | awk '{ print $5 " " $6 " " $4 }' | while read output; do
	USEP=$(echo $output | awk '{ print $1}' | cut -d'%' -f1 )
	PARTITION=$(echo $output | awk '{ print $2 }' )
	FREESP=$(echo $output | awk '{ print $3}' | sed 's/.$//' )
	# Get thresholds
	if [[ _${DISK_ALERT_PERCENT_CRITICAL[$PARTITION]} != "_" ]]; then
		CRITICAL=${DISK_ALERT_PERCENT_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_PERCENT_CRITICAL != "_" ]]; then
		CRITICAL=$DISK_ALERT_DEFAULT_PERCENT_CRITICAL
	else
		CRITICAL="95"
	fi
	#
	if [[ _${DISK_ALERT_FREE_SPACE_CRITICAL[$PARTITION]} != "_" ]]; then
		FREE_SPACE_CRITICAL=${DISK_ALERT_FREE_SPACE_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_FREE_SPACE_CRITICAL != "_" ]]; then
		FREE_SPACE_CRITICAL=$DISK_ALERT_DEFAULT_FREE_SPACE_CRITICAL
	else
		FREE_SPACE_CRITICAL="1024"
	fi
	#
	if [[ _${DISK_ALERT_PREDICT_CRITICAL[$PARTITION]} != "_" ]]; then
		PREDICT_CRITICAL=${DISK_ALERT_PREDICT_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_PREDICT_CRITICAL != "_" ]]; then
		PREDICT_CRITICAL=$DISK_ALERT_DEFAULT_PREDICT_CRITICAL
	else
		PREDICT_CRITICAL="86400"
	fi
	# Usage check type
	if [[ $USAGE_CHECK == "PERCENT" ]]; then
		# Critical percent message
		if [[ $USEP -ge $CRITICAL ]]; then
			echo '{"host": "'$HOSTNAME'", "from": "disk_alert.sh", "type": "disk used space percent", "status": "CRITICAL", "date time": "'$DATE'", "partition": "'$PARTITION'", "free space": "'$FREESP'MB", "use": "'$USEP'%", "threshold": "'$CRITICAL'%"}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		fi
	elif [[ $USAGE_CHECK == "FREE_SPACE" ]]; then
		# Critical free space message
		if [[ $FREESP -le $FREE_SPACE_CRITICAL ]]; then
			echo '{"host": "'$HOSTNAME'", "from": "disk_alert", "type": "disk free space MB", "status": "CRITICAL", "date time": "'$DATE'", "partition": "'$PARTITION'", "free space": "'$FREESP'MB", "use": "'$USEP'%", "threshold": "'$FREE_SPACE_CRITICAL'MB"}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		fi
	fi
	# Add partition usage history by seconds from unix epoch
	PARTITION_FN=$(echo $PARTITION | sed -e 's#/#_#g')
	echo "$TIMESTAMP	$USEP" >> "/opt/sysadmws/disk_alert/history/$PARTITION_FN.txt"
	# Leave only last N lines in file
	tail -n $HISTORY_SIZE "/opt/sysadmws/disk_alert/history/$PARTITION_FN.txt" > "/opt/sysadmws/disk_alert/history/$PARTITION_FN.txt.new"
	mv -f "/opt/sysadmws/disk_alert/history/$PARTITION_FN.txt.new" "/opt/sysadmws/disk_alert/history/$PARTITION_FN.txt"
	# Get linear regression json
	LR=$(awk -f /opt/sysadmws/disk_alert/lr.awk --assign timestamp="$TIMESTAMP" "/opt/sysadmws/disk_alert/history/$PARTITION_FN.txt" 2>/dev/null)
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
				echo '{"host": "'$HOSTNAME'", "from": "disk_alert", "type": "disk used space predict", "status": "CRITICAL", "date time": "'$DATE'", "partition": "'$PARTITION'", "free space": "'$FREESP'MB", "use": "'$USEP'%", "angle": "'$P_ANGLE'", "shift": "'$P_SHIFT'", "quality": "'$P_QUALITY'", "predict seconds": "'$PREDICT_SECONDS'", "predict hms": "'$P_HMS'", "predict threshold": "'$PREDICT_CRITICAL'"}' | /opt/sysadmws/notify_devilry/notify_devilry.py
			fi
		fi
	fi
done
