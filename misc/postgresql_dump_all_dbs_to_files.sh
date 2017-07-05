#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

DIR=${PWD}
[ ! $DIR ] && mkdir -p $DIR || :
LIST=$(su -c 'psql -l' - postgres | awk '{ print $1}' | grep -vE '^-|^List|^Name|template[0|1]|^\(|^\|')
for d in $LIST
do
  echo $d
  su -c "/usr/bin/pg_dump $d" - postgres | gzip -c >  $DIR/$d.out.gz
done
