#!/bin/bash

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TABLE_NAME=$1
DB_DUMP=$2
OUTPUT_DIR=${PWD}

RESULT_FILE=$OUTPUT_DIR/$TABLE_NAME.extracted.$(date +%Y-%m-%d-%H-%M-%S).sql

USAGE='USAGE: ./mysql_table_extractor.sh $TABLE_NAME $DB_DUMP'

if [ "x$TABLE_NAME" = "x" ] && [ "y$DB_DUMP" = "y" ] ; then
        echo -e "$USAGE"
        exit 1
fi

if [ ! -f "$DB_DUMP" ] ; then
	echo -e "Could not found \"$DB_DUMP\". Check the path and then try again."
	exit 1
fi	

if [[ $(file "$DB_DUMP" | grep "gzip") ]]  ; then
	gunzip -c "$DB_DUMP" | sed -n -e "/-- Table structure for table \`$TABLE_NAME\`/,/-- Table structure/p" | pv > "$RESULT_FILE"
else
	cat "$DB_DUMP" | sed -n -e "/-- Table structure for table \`$TABLE_NAME\`/,/-- Table structure/p" | pv > "$RESULT_FILE"
fi

if [ -s ${RESULT_FILE} ] ; then 
	echo -e "Success! Table \"$TABLE_NAME\" extracted to $RESULT_FILE"
else
	echo -e "Dump \"$DB_DUMP\" does not contain a table \"$TABLE_NAME\""
	rm -f ${RESULT_FILE}
fi

exit 0
