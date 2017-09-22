#!/bin/bash

###     Define PATH
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

###     Try too find mysql service
MY_CHECK_SYSVINIT=$(service --status-all 2>&1 | grep "\+" | grep mysql)
MY_CHECK_UPSTART=$(initctl list | grep mysql | grep running)

if [ -z "${MY_CHECK_SYSVINIT}" ] && [ -z "${MY_CHECK_UPSTART}" ] ; then
        exit 0
fi


###     Set some variables
MY_CLIENT=$(which mysql)
MY_CRED="--defaults-file=/etc/mysql/debian.cnf"
MY_QUERY="show full processlist\G"
CUR_DATE_TIME=$(date +"%F %T")

###     Get full processlist snapshot to the variable
MPL_SNAP=$("$MY_CLIENT" "$MY_CRED" -e "$MY_QUERY")

###     Parse full processlist to some needed blocks or counters
MPL_REALQ=$(echo "$MPL_SNAP" | sed -e '/Rows_examined:*/G' | sed -e '/./{H;$!d;}' -e 'x;/Sleep/d' | sed -e '/./{H;$!d;}' -e 'x;/Binlog/d' | sed -e '/./{H;$!d;}' -e 'x;/Info\:\ show\ full\ processlist/d')

###     Calculate some counters for summary
MPL_REALQ_COUNT=$(echo "$MPL_REALQ" | grep -c "Command:")
MPL_SLEEP_COUNT=$(echo "$MPL_SNAP" | grep -c "Command: Sleep")
MPL_BINLOG_COUNT=$(echo "$MPL_SNAP" | grep -c "Command: Binlog")
MPL_SELF_COUNT=$(echo "$MPL_SNAP" | grep -c "Info: show full processlist")
MPL_TOTAL_COUNT=$(echo "$MPL_SNAP" | grep -c "Command:")

###     Print start line
echo -e "$CUR_DATE_TIME START#\n"

###     Print "real" queries if they are present
if [ ! -z "${MPL_REALQ}" ] ; then
        echo -e "Real queries: $MPL_REALQ\n\n"
        echo -e "****************************************************************\n"
fi

###     Print summary
echo -e "Summary:\n\t\
        Binlog queries:\t$MPL_BINLOG_COUNT\n\t\
        Sleep queries:\t$MPL_SLEEP_COUNT\n\t\
        Self queries:\t$MPL_SELF_COUNT\n\t\
        Real queries:\t$MPL_REALQ_COUNT\n\t\
        Total queries:\t$MPL_TOTAL_COUNT\n\n"

###     Print EOL
echo -e "$CUR_DATE_TIME END#\n\n"

echo -e "||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||--||\n\n"

exit 0
