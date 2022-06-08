#!/bin/bash
STATUS=$(echo "show status like 'wsrep_local_state'" | mysql | tail -n 1 | awk '{print $2}')
if [[ ${STATUS} = 4 ]]; then
	exit 0
else
	exit 1
fi
