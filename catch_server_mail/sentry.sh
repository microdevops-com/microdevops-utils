#!/bin/bash

if [[ ! -f /opt/microdevops/catch_server_mail/sentry.properties ]]; then
        echo -e >&2 "ERROR: Sentry settings file /opt/microdevops/catch_server_mail/sentry.properties does not exist"
        exit 1
fi

CATCHER_LOG=/opt/microdevops/catch_server_mail/log/sentry.log
ATTACH_LOG="$(mktemp /tmp/catch_server_mail.XXXXXXXXX.log)"

# Check env file exist and source it
if [[ -f /opt/microdevops/catch_server_mail/sentry.env ]]; then
	source /opt/microdevops/catch_server_mail/sentry.env
fi

# Remove ATTACH_LOG on exit with trap
trap "rm -f $ATTACH_LOG" EXIT

# Save stdin to a temporary file
cat > "$ATTACH_LOG"

# Get Subject from mail
SUBJECT="$(grep -i '^Subject:' "$ATTACH_LOG" | sed -e 's/^Subject: //')"

# Send to Sentry
# Sentry shows error if tag sent is empty, so use none instead
SENTRY_PROPERTIES=/opt/microdevops/catch_server_mail/sentry.properties \
	/usr/local/bin/sentry-cli send-event \
	-m "${SUBJECT:-${0}}" \
	--logfile ${ATTACH_LOG} \
	--env "${SERVER_ENVIRONMENT:-infra}" \
	--tag location:"${SERVER_LOCATION:-none}" \
	--extra description:"${SERVER_DESCRIPTION}" \
	2>&1 | tee ${CATCHER_LOG}
