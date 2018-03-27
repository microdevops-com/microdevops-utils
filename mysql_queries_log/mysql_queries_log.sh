#!/bin/bash

###     Define PATH
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

###     Set some variables
MY_ADMIN=$(which mysqladmin)
MY_CLIENT=$(which mysql)
MY_CRED="--defaults-file=/etc/mysql/debian.cnf"
MY_QUERY="show full processlist\G"
CUR_DATE_TIME=$(date +"%F %T")

###     Detect is mysql service alive
MY_CHECK=$("$MY_ADMIN" "$MY_CRED" ping 2>/dev/null | grep alive)

if [ "z$MY_CHECK" = "z" ] ; then
	exit 0
fi

###     Get full processlist snapshot to the variable
MPL_SNAP=$("$MY_CLIENT" "$MY_CRED" -e "$MY_QUERY")

MY_CHECK_VANILA=$(echo "MPL_SNAP" | grep -c "Rows_examined:")

if [ "MY_CHECK_VANILA" != "0" ] ; then
	MPL_SED_PARSE="Rows_examined:"
else
	MPL_SED_PARSE="Info:"
fi

###     Parse full processlist to some needed blocks or counters
MPL_REALQ=$(echo "$MPL_SNAP" | sed -e "/$MPL_SED_PARSE*/G" | sed -e '/./{H;$!d;}' -e 'x;/Sleep/d' | sed -e '/./{H;$!d;}' -e 'x;/Binlog/d' | sed -e '/./{H;$!d;}' -e 'x;/Info\:\ show\ full\ processlist/d')

###     Calculate some counters for summary
MPL_REALQ_COUNT=$(echo "$MPL_REALQ" | grep -c "Command:")
MPL_SLEEP_COUNT=$(echo "$MPL_SNAP" | grep -c "Command: Sleep")
MPL_BINLOG_COUNT=$(echo "$MPL_SNAP" | grep -c "Command: Binlog")
MPL_SELF_COUNT=$(echo "$MPL_SNAP" | grep -c "Info: show full processlist")
MPL_TOTAL_COUNT=$(echo "$MPL_SNAP" | grep -c "Command:")

###     Print start line
echo -e "$CUR_DATE_TIME START#\n"

# Exit if lock exists (prevent multiple execution)
LOCK_DIR=/opt/sysadmws-utils/mysql_queries_log/mysql_queries_log.lock

if mkdir "$LOCK_DIR"
then
        echo -e >&2 "NOTICE: Successfully acquired lock on $LOCK_DIR"
        trap 'rm -rf "$LOCK_DIR"' 0
else
        echo -e >&2 "ERROR: Cannot acquire lock, giving up on $LOCK_DIR"
        exit 0
fi

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
