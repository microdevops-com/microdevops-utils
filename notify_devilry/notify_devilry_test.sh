#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)

# Send test
echo '{
	"severity": "informational",
	"service": "notify_devilry",
	"resource": "'$HOSTNAME'",
	"event": "notify_devilry_test",
	"value": "test",
	"text": "Severity informational test alert sent with notify_devilry_test.sh",
	"origin": "notify_devilry_test.sh",
	"timeout": 300
}' | /opt/sysadmws/notify_devilry/notify_devilry.py --debug --force-send
