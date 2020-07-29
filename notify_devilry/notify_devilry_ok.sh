#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)

# Send test
echo '{
	"severity": "ok",
	"service": "server",
	"resource": "'$HOSTNAME'",
	"event": "notify_devilry_ok",
	"group": "software",
	"value": "ok",
	"text": "ok test alarm sent with notify_devilry_ok.sh",
	"origin": "notify_devilry_ok.sh",
	"timeout": 300,
	"correlate": ["notify_devilry_critical"]
}' | /opt/sysadmws/notify_devilry/notify_devilry.py --debug --force-send
