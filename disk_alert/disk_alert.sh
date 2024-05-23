#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
DATE=$(date '+%F %T')
declare -A DISK_ALERT_PERCENT_CRITICAL
declare -A DISK_ALERT_PERCENT_WARNING
declare -A DISK_ALERT_FREE_SPACE_CRITICAL
declare -A DISK_ALERT_FREE_SPACE_WARNING
declare -A DISK_ALERT_PREDICT_CRITICAL
declare -A DISK_ALERT_PREDICT_WARNING
declare -A DISK_ALERT_INODE_CRITICAL
declare -A DISK_ALERT_INODE_WARNING
# Seconds since unix epoch
TIMESTAMP=$(date '+%s')

# Include config
if [ -f /opt/sysadmws/disk_alert/disk_alert.conf ]; then
	. /opt/sysadmws/disk_alert/disk_alert.conf
fi

# Optional first arg - random sleep up to arg value
if [[ -n "$1" ]]; then
	sleep $((RANDOM % $1))
fi

# Check defaults
if [[ -n "${HOSTNAME_OVERRIDE}" ]]; then
	HOSTNAME=${HOSTNAME_OVERRIDE}
else
	HOSTNAME=$(hostname -f)
fi
#
if [[ _$DISK_ALERT_FILTER != "_" ]]; then
	FILTER=$DISK_ALERT_FILTER
else
	FILTER="^Filesystem|^tmpfs|^cdrom|^none|^/dev/loop|^overlay|^shm|^udev|^cgroup|^cgmfs|^snapfuse|kubernetes.io|volume-subpaths"
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
	if [[ _${DISK_ALERT_PERCENT_WARNING[$PARTITION]} != "_" ]]; then
		WARNING=${DISK_ALERT_PERCENT_WARNING[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_PERCENT_WARNING != "_" ]]; then
		WARNING=$DISK_ALERT_DEFAULT_PERCENT_WARNING
	else
		WARNING="90"
	fi
	#
	if [[ _${DISK_ALERT_FREE_SPACE_CRITICAL[$PARTITION]} != "_" ]]; then
		FREE_SPACE_CRITICAL=${DISK_ALERT_FREE_SPACE_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_FREE_SPACE_CRITICAL != "_" ]]; then
		FREE_SPACE_CRITICAL=$DISK_ALERT_DEFAULT_FREE_SPACE_CRITICAL
	else
		FREE_SPACE_CRITICAL="1024"
	fi
	if [[ _${DISK_ALERT_FREE_SPACE_WARNING[$PARTITION]} != "_" ]]; then
		FREE_SPACE_WARNING=${DISK_ALERT_FREE_SPACE_WARNING[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_FREE_SPACE_WARNING != "_" ]]; then
		FREE_SPACE_WARNING=$DISK_ALERT_DEFAULT_FREE_SPACE_WARNING
	else
		FREE_SPACE_WARNING="2048"
	fi
	#
	if [[ _${DISK_ALERT_PREDICT_CRITICAL[$PARTITION]} != "_" ]]; then
		PREDICT_CRITICAL=${DISK_ALERT_PREDICT_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_PREDICT_CRITICAL != "_" ]]; then
		PREDICT_CRITICAL=$DISK_ALERT_DEFAULT_PREDICT_CRITICAL
	else
		PREDICT_CRITICAL="3600"
	fi
	if [[ _${DISK_ALERT_PREDICT_WARNING[$PARTITION]} != "_" ]]; then
		PREDICT_WARNING=${DISK_ALERT_PREDICT_WARNING[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_PREDICT_WARNING != "_" ]]; then
		PREDICT_WARNING=$DISK_ALERT_DEFAULT_PREDICT_WARNING
	else
		PREDICT_WARNING="86400"
	fi
	# 100% is always fatal
	if [[ $USEP -eq "100" ]]; then
		echo '{
			"severity": "fatal",
			"service": "disk",
			"resource": "'$HOSTNAME':'$PARTITION'",
			"event": "disk_alert_percentage_usage_high",
			"origin": "disk_alert.sh",
			"text": "Disk usage high percentage detected",
			"value": "'$USEP'%",
			"correlate": ["disk_alert_percentage_usage_ok","disk_alert_percentage_usage_almost_high"],
			"attributes": {
				"free space": "'$FREESP'MB",
				"warning threshold": "'$WARNING'%",
				"critical threshold": "'$CRITICAL'%"
			}
		}' | /opt/sysadmws/notify_devilry/notify_devilry.py
	# Usage check type
	elif [[ $USAGE_CHECK == "PERCENT" ]]; then
		# Critical percent message
		if [[ $USEP -ge $CRITICAL ]]; then
			echo '{
				"severity": "critical",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_percentage_usage_high",
				"origin": "disk_alert.sh",
				"text": "Disk usage high percentage detected",
				"value": "'$USEP'%",
				"correlate": ["disk_alert_percentage_usage_ok","disk_alert_percentage_usage_almost_high"],
				"attributes": {
					"free space": "'$FREESP'MB",
					"warning threshold": "'$WARNING'%",
					"critical threshold": "'$CRITICAL'%"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		elif [[ $USEP -ge $WARNING ]]; then
			echo '{
				"severity": "major",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_percentage_usage_almost_high",
				"origin": "disk_alert.sh",
				"text": "Disk usage almost high percentage detected",
				"value": "'$USEP'%",
				"correlate": ["disk_alert_percentage_usage_ok","disk_alert_percentage_usage_high"],
				"attributes": {
					"free space": "'$FREESP'MB",
					"warning threshold": "'$WARNING'%",
					"critical threshold": "'$CRITICAL'%"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		else
			echo '{
				"severity": "ok",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_percentage_usage_ok",
				"origin": "disk_alert.sh",
				"text": "Disk usage ok percentage detected",
				"value": "'$USEP'%",
				"correlate": ["disk_alert_percentage_usage_high","disk_alert_percentage_usage_almost_high"],
				"attributes": {
					"free space": "'$FREESP'MB",
					"warning threshold": "'$WARNING'%",
					"critical threshold": "'$CRITICAL'%"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		fi
	elif [[ $USAGE_CHECK == "FREE_SPACE" ]]; then
		# Critical free space message
		if [[ $FREESP -le $FREE_SPACE_CRITICAL ]]; then
			echo '{
				"severity": "critical",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_free_space_low",
				"origin": "disk_alert.sh",
				"text": "Low disk free space in MB detected",
				"value": "'$FREESP'MB",
				"correlate": ["disk_alert_free_space_ok","disk_alert_free_space_almost_low"],
				"attributes": {
					"use": "'$USEP'%",
					"warning threshold": "'$FREE_SPACE_WARNING'MB",
					"critical threshold": "'$FREE_SPACE_CRITICAL'MB"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		elif [[ $FREESP -le $FREE_SPACE_WARNING ]]; then
			echo '{
				"severity": "major",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_free_space_almost_low",
				"origin": "disk_alert.sh",
				"text": "Almost low disk free space in MB detected",
				"value": "'$FREESP'MB",
				"correlate": ["disk_alert_free_space_ok","disk_alert_free_space_low"],
				"attributes": {
					"use": "'$USEP'%",
					"warning threshold": "'$FREE_SPACE_WARNING'MB",
					"critical threshold": "'$FREE_SPACE_CRITICAL'MB"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		else
			echo '{
				"severity": "ok",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_free_space_ok",
				"origin": "disk_alert.sh",
				"text": "Enough disk free space in MB detected",
				"value": "'$FREESP'MB",
				"correlate": ["disk_alert_free_space_low","disk_alert_free_space_almost_low"],
				"attributes": {
					"use": "'$USEP'%",
					"warning threshold": "'$FREE_SPACE_WARNING'MB",
					"critical threshold": "'$FREE_SPACE_CRITICAL'MB"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
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
                P_ANGLE=$(echo "$LR" | python -c "import sys, json; print(json.load(sys.stdin)['angle'])")
                P_SHIFT=$(echo "$LR" | python -c "import sys, json; print(json.load(sys.stdin)['shift'])")
                P_QUALITY=$(echo "$LR" | python -c "import sys, json; print(json.load(sys.stdin)['quality'])")
                PREDICT_SECONDS=$(echo "$LR" | python -c "import sys, json; print(json.load(sys.stdin)['predict seconds'])")
                P_HMS=$(echo "$LR" | python -c "import sys, json; print(json.load(sys.stdin)['predict hms'])")
	fi
	# Critical predict message
	if [[ $PREDICT_SECONDS != "None" ]]; then
		if [[ $PREDICT_SECONDS -lt $PREDICT_CRITICAL && $PREDICT_SECONDS -gt 0 ]]; then
			echo '{
				"severity": "minor",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_predict_usage_full",
				"origin": "disk_alert.sh",
				"text": "Full usage of disk predicted within critical threshold",
				"value": "'$PREDICT_SECONDS's",
				"correlate": ["disk_alert_predict_usage_ok","disk_alert_warning_predict_usage_full"],
				"attributes": {
					"use": "'$USEP'%",
					"free space": "'$FREESP'MB",
					"angle": "'$P_ANGLE'",
					"shift": "'$P_SHIFT'",
					"quality": "'$P_QUALITY'",
					"predict hms": "'$P_HMS'",
					"predict warning threshold": "'$PREDICT_WARNING'",
					"predict critical threshold": "'$PREDICT_CRITICAL'"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		elif [[ $PREDICT_SECONDS -lt $PREDICT_WARNING && $PREDICT_SECONDS -gt 0 ]]; then
			echo '{
				"severity": "warning",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_warning_predict_usage_full",
				"origin": "disk_alert.sh",
				"text": "Full usage of disk predicted within warning threshold",
				"value": "'$PREDICT_SECONDS's",
				"correlate": ["disk_alert_predict_usage_ok","disk_alert_predict_usage_full"],
				"attributes": {
					"use": "'$USEP'%",
					"free space": "'$FREESP'MB",
					"angle": "'$P_ANGLE'",
					"shift": "'$P_SHIFT'",
					"quality": "'$P_QUALITY'",
					"predict hms": "'$P_HMS'",
					"predict warning threshold": "'$PREDICT_WARNING'",
					"predict critical threshold": "'$PREDICT_CRITICAL'"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		else
			echo '{
				"severity": "ok",
				"service": "disk",
				"resource": "'$HOSTNAME':'$PARTITION'",
				"event": "disk_alert_predict_usage_ok",
				"origin": "disk_alert.sh",
				"text": "No full usage of disk predicted within threshold",
				"value": "'$PREDICT_SECONDS's",
				"correlate": ["disk_alert_predict_usage_full","disk_alert_warning_predict_usage_full"],
				"attributes": {
					"use": "'$USEP'%",
					"free space": "'$FREESP'MB",
					"angle": "'$P_ANGLE'",
					"shift": "'$P_SHIFT'",
					"quality": "'$P_QUALITY'",
					"predict hms": "'$P_HMS'",
					"predict warning threshold": "'$PREDICT_WARNING'",
					"predict critical threshold": "'$PREDICT_CRITICAL'"
				}
			}' | /opt/sysadmws/notify_devilry/notify_devilry.py
		fi
	fi
done

# Check df inodes
df -P -i | grep -vE $FILTER | awk '{ print $5 " " $6 }' | while read output; do
	USEP=$(echo $output | awk '{ print $1}' | cut -d'%' -f1 )
	PARTITION=$(echo $output | awk '{ print $2 }' )
	# Skip partitions without inodes
	if [[ _$USEP = _- ]]; then
		continue
	fi
	# Get thresholds
	if [[ _${DISK_ALERT_INODE_CRITICAL[$PARTITION]} != "_" ]]; then
		CRITICAL=${DISK_ALERT_INODE_CRITICAL[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_INODE_CRITICAL != "_" ]]; then
		CRITICAL=$DISK_ALERT_DEFAULT_INODE_CRITICAL
	else
		CRITICAL="95"
	fi
	if [[ _${DISK_ALERT_INODE_WARNING[$PARTITION]} != "_" ]]; then
		WARNING=${DISK_ALERT_INODE_WARNING[$PARTITION]}
	elif [[ _$DISK_ALERT_DEFAULT_INODE_WARNING != "_" ]]; then
		WARNING=$DISK_ALERT_DEFAULT_INODE_WARNING
	else
		WARNING="90"
	fi
	#
	# Critical percent message
	if [[ $USEP -ge $CRITICAL ]]; then
		echo '{
			"severity": "critical",
			"service": "disk",
			"resource": "'$HOSTNAME':'$PARTITION'",
			"event": "disk_alert_inode_usage_high",
			"origin": "disk_alert.sh",
			"text": "Inode usage high percentage detected",
			"value": "'$USEP'%",
			"correlate": ["disk_alert_inode_usage_ok","disk_alert_inode_usage_almost_high"],
			"attributes": {
				"warning threshold": "'$WARNING'%",
				"critical threshold": "'$CRITICAL'%"
			}
		}' | /opt/sysadmws/notify_devilry/notify_devilry.py
	elif [[ $USEP -ge $WARNING ]]; then
		echo '{
			"severity": "major",
			"service": "disk",
			"resource": "'$HOSTNAME':'$PARTITION'",
			"event": "disk_alert_inode_usage_almost_high",
			"origin": "disk_alert.sh",
			"text": "Inode usage almost high percentage detected",
			"value": "'$USEP'%",
			"correlate": ["disk_alert_inode_usage_ok","disk_alert_inode_usage_high"],
			"attributes": {
				"warning threshold": "'$WARNING'%",
				"critical threshold": "'$CRITICAL'%"
			}
		}' | /opt/sysadmws/notify_devilry/notify_devilry.py
	else
		echo '{
			"severity": "ok",
			"service": "disk",
			"resource": "'$HOSTNAME':'$PARTITION'",
			"event": "disk_alert_inode_usage_ok",
			"origin": "disk_alert.sh",
			"text": "Inode usage ok percentage detected",
			"value": "'$USEP'%",
			"correlate": ["disk_alert_inode_usage_high","disk_alert_inode_usage_almost_high"],
			"attributes": {
				"warning threshold": "'$WARNING'%",
				"critical threshold": "'$CRITICAL'%"
			}
		}' | /opt/sysadmws/notify_devilry/notify_devilry.py
	fi
done
