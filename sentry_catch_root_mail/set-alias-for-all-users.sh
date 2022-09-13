#!/bin/bash
while IFS= read -r line; do
	id="$(cut -d: -f3 <<<"$line")"
        user="$(cut -d: -f1 <<<"$line")"
        if [[ "${id}" -gt 999 ]]; then
                if [[ "${id}" -lt 65534 ]]; then
                        if [[ $(grep "${user}:" /etc/aliases) ]]; then
                                sed -iE "s/^${user}:.*/${user}: | \/opt\/sysadmws\/sentry_catch_root_mail\/sentry-sender.sh/g" /etc/aliases
                        else
                                echo "${user}: | /opt/sysadmws/sentry_catch_root_mail/sentry-sender.sh" >> /etc/aliases
                        fi
                fi
        fi
done </etc/passwd
newaliases
