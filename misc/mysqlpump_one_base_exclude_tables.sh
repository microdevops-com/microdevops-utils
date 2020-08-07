#!/bin/bash

set -u
set -e

DATABASE=$1
EXCLUDE_TABLES=$2

MYSQL_DEFAULTS_FILE="/etc/mysql/debian.cnf"
MYSQL_PUMP=$(which mysqlpump)
MYSQL_CLIENT=$(which mysql)
MYSQL_PUMP_OPTS="--single-transaction --add-drop-table"

WORK_DIR="/var/backups/mysql/"
DUMP_FILE="$DATABASE.mysqlpump.exclude-tables.gz"

$MYSQL_PUMP --defaults-file=$MYSQL_DEFAULTS_FILE --skip-dump-rows $DATABASE > $WORK_DIR/$DATABASE.skip-dump-rows.sql
$MYSQL_PUMP --defaults-file=$MYSQL_DEFAULTS_FILE $MYSQL_PUMP_OPTS $DATABASE --exclude-tables=$EXCLUDE_TABLES | gzip -c > $WORK_DIR/$DUMP_FILE
