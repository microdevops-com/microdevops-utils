#!/bin/bash
eval "$(/usr/local/bin/sentry-cli bash-hook)"
logfile=/opt/sysadmws/sentry_catch_root_mail/log/sentry-cli.log

if [[ ! -f /opt/sysadmws/sentry_catch_root_mail/sentry.properties ]]; then
        echo 'Sentry settings file /opt/sysadmws/sentry_catch_root_mail/sentry.properties does not exist'
        exit 1;
fi
export SENTRY_PROPERTIES=/opt/sysadmws/sentry_catch_root_mail/sentry.properties
while IFS= read line; do
        key=$(echo "${line}" | sed -E 's/([^:]*).*/\1/g')
        val=$(echo "${line}" | sed -E 's/([^:]*): (.*)/\2/g')
        if [[ "${key}" == "Subject" ]]; then
                subject="-m '$val'"
                continue;
        fi
        if [[ "${key}" == "From" ]]; then
                host="$(echo $val| sed -E 's/[^@]*@([^> ]*).*/\1/g')"
        fi
        lines="${lines:-} -m '$line'"
done

# TEMP-SENDER PATH
TMP_SENDER="$(mktemp /tmp/sender.XXXXXXXXX.sh)"

# MAKE TEMP-SENDER
cat << EOF > "${TMP_SENDER}"
#!/bin/bash
eval "\$(/usr/local/bin/sentry-cli bash-hook)"

# LOG TEMP-SENDER MAIN COMMAND LINE
echo "/usr/local/bin/sentry-cli send-event -t host:${host} ${subject} ${lines}" | sed 's/-m/\\\ \n -m/g;s/-t/\n -t/g' >> "${logfile}"
echo >> "${logfile}"

/usr/local/bin/sentry-cli send-event -t host:${host} ${subject} ${lines} 2>&1 |tee -a "${logfile}"
EOF

# MAKE TEMP-SENDER RUNABLE
chmod +x "${TMP_SENDER}"

# RUN TEMP-SENDER
"${TMP_SENDER}"

# REMOVE TEMP-SENDER
#rm -f "${TMP_SENDER}"