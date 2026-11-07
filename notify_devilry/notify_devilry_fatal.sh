#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "$LANG" != "en_US.UTF-8" ]]; then export LANG=C ; fi
HOSTNAME=$(hostname -f)
# Optional first argument: alert timeout in seconds (Alerta expires the alert after it), default 300.
TIMEOUT="${1:-300}"
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || { echo "usage: $0 [timeout_seconds]" >&2; exit 2; }

# Send test
echo '{
	"severity": "fatal",
	"service": "notify_devilry",
	"resource": "'$HOSTNAME'",
	"event": "notify_devilry_critical",
	"value": "fatal",
	"text": "Severity fatal test alert sent with notify_devilry_fatal.sh",
	"origin": "notify_devilry_fatal.sh",
	"timeout": '$TIMEOUT',
	"correlate": ["notify_devilry_ok"]
}' | /opt/sysadmws/notify_devilry/notify_devilry.py --debug --force-send
