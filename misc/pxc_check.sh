#!/bin/bash
STATUS=$(echo "show status like 'wsrep_local_state'" | mysql | tail -n 1 | awk '{print $2}')
# https://docs.percona.com/percona-xtradb-cluster/8.0/wsrep-status-index.html#wsrep_local_state_comment
if [[ ${STATUS} == 4 || ${STATUS} == 2 ]]; then
	exit 0
else
	exit 1
fi
