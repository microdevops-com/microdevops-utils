#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)

# Send test
echo '{
	"severity": "fatal",
	"service": "notify_devilry",
	"resource": "'$HOSTNAME'",
	"event": "notify_devilry_critical",
	"value": "fatal",
	"text": "Severity fatal test alert sent with notify_devilry_fatal.sh",
	"origin": "notify_devilry_fatal.sh",
	"timeout": 300,
	"correlate": ["notify_devilry_ok"]
}' | /opt/sysadmws/notify_devilry/notify_devilry.py --debug --force-send
