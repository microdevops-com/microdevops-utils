#!/bin/bash
export HN=`hostname`
[ -e /root/.ssh/id_rsa ] || { ssh-keygen -b 4096 -f /root/.ssh/id_rsa -q -N "" ; ( cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys ) }
chmod 600 /root/.ssh/authorized_keys
ssh -oStrictHostKeyChecking=no localhost exit
ssh -oStrictHostKeyChecking=no $HN exit
sed "s/HOSTNAME/$HN/g" /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf.localhost | grep UBUNTU > /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf
cp /opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup_daily.cron /etc/cron.d/sysadmws-rsnapshot-backup
chmod 600 /etc/cron.d/sysadmws-rsnapshot-backup

cp /opt/sysadmws-utils/salt/grains.template /etc/salt/grains.sample
cat /opt/sysadmws-utils/salt/grains.ubuntu.template | sed "s/HOSTNAME/$HN/g" >> /etc/salt/grains

/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.sh sync
