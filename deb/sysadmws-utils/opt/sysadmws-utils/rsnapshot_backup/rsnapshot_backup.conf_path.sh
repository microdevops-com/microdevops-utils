#!/bin/bash
export HN=`hostname`
export XPATH=$1
echo "---			FS_RSYNC_SSH			$XPATH		---" >> /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf
cat /opt/sysadmws-utils/salt/grains.path.template | sed "s/HOSTNAME/$HN/g" | sed "s#PATH#$XPATH#g" >> /etc/salt/grains
/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.sh sync
