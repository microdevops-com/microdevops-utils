#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MYSQLDUMP="/usr/bin/nice -n 2 /usr/bin/mysqldump"
MYSQL="/usr/bin/mysql"

OUTPUTDIR=${PWD}
GZIP_ENABLED=1

if [ ! -d "$OUTPUTDIR" ]; then
    mkdir -p $OUTPUTDIR
fi

databases=`$MYSQL --defaults-file=/etc/mysql/debian.cnf -e "SHOW DATABASES;" | grep -Ev "(Database|information_schema|performance_schema)"`

for db in $databases; do
    echo $db
        if [ $GZIP_ENABLED == 1 ]; then
                $MYSQLDUMP --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --lock-tables=false --events --ignore-table=mysql.event --databases $db | gzip > "$OUTPUTDIR/$db.gz"
        else
            $MYSQLDUMP --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --lock-tables=false --events --ignore-table=mysql.event --databases $db > "$OUTPUTDIR/$db.sql"
        fi
done

