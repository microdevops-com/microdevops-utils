#!/bin/bash
export HN=`hostname`
sed "s/HOSTNAME/$HN/g" /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf.localhost | grep MYSQL >> /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf
cat /opt/sysadmws-utils/salt/grains.mysql.template | sed "s/HOSTNAME/$HN/g" >> /etc/salt/grains
/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.sh sync
