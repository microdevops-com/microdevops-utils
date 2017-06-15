#!/bin/sh
if [ `dirname $0` != "." ]; then
	echo "You should run this script from `dirname $0`"
	exit;
fi

# Increase a version of the package
perl -pi -e '($_=$1.q^.^.(int($2)+1).qq#\n#)if/^(Version:\s+\d+:\d+)\.(\d+)$/' sysadmws-utils/DEBIAN/control

# Remove all files in sub modules
find sysadmws-utils/opt -type f -delete
find sysadmws-utils/etc -type f -delete

# LICENSE README.md
cp ../LICENSE \
	../README.md \
	sysadmws-utils/opt/sysadmws-utils

# bulk_log
cp ../bulk_log/bulk_log.sh \
	sysadmws-utils/opt/sysadmws-utils/bulk_log
cp ../bulk_log/bulk_log.cron \
	sysadmws-utils/etc/cron.d/sysadmws-bulk-log
cp ../bulk_log/bulk_log.logrotate \
	sysadmws-utils/etc/logrotate.d/sysadmws-bulk-log
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/bulk_log/bulk_log.sh
sudo chmod 600 sysadmws-utils/etc/cron.d/sysadmws-bulk-log
sudo chmod 600 sysadmws-utils/etc/logrotate.d/sysadmws-bulk-log

# disk_alert
cp ../disk_alert/disk_alert.sh \
	sysadmws-utils/opt/sysadmws-utils/disk_alert
cp ../disk_alert/disk_alert.cron \
	sysadmws-utils/etc/cron.d/sysadmws-disk-alert
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/disk_alert/disk_alert.sh
sudo chmod 600 sysadmws-utils/etc/cron.d/sysadmws-disk-alert

# salt
cp ../salt/grains.template \
	sysadmws-utils/opt/sysadmws-utils/salt
sudo chmod 644 sysadmws-utils/opt/sysadmws-utils/salt/grains.template

# logrotate_db_backup
cp ../logrotate_db_backup/logrotate_db_backup.awk \
	../logrotate_db_backup/logrotate_db_backup.conf.sample \
	../logrotate_db_backup/logrotate_db_backup.sh \
	sysadmws-utils/opt/sysadmws-utils/logrotate_db_backup
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/logrotate_db_backup/*.awk
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/logrotate_db_backup/*.sh

# mikrotik_backup
cp ../mikrotik_backup/mikrotik_backup.sh \
	../mikrotik_backup/mikrotik_backup.conf.sample \
	sysadmws-utils/opt/sysadmws-utils/mikrotik_backup
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/mikrotik_backup/mikrotik_backup.conf.sample
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/mikrotik_backup/*.sh

# rsnapshot_backup
cp ../rsnapshot_backup/rsnapshot_backup.awk \
	../rsnapshot_backup/rsnapshot_backup.conf.sample \
	../rsnapshot_backup/rsnapshot_backup.conf.localhost \
	../rsnapshot_backup/rsnapshot_backup.sh \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_UBUNTU.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_CENTOS.conf \
	../rsnapshot_backup/rsnapshot_conf_template_ROTATE.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_NATIVE.conf \
	../rsnapshot_backup/rsnapshot_conf_template_LOCAL_PREEXEC.conf \
	../rsnapshot_backup/rsnapshot_backup_daily.cron \
	../rsnapshot_backup/rsnapshot_backup_hourly.cron \
	../rsnapshot_backup/rsnapshot_backup_postgresql_query1.sql \
	sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/*
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.sh
cp ../rsnapshot_backup/rsnapshot_backup.logrotate \
	sysadmws-utils/etc/logrotate.d/sysadmws-rsnapshot-backup
sudo chmod 600 sysadmws-utils/etc/logrotate.d/sysadmws-rsnapshot-backup

# backup_check
cp ../backup_check/backup_check.sh \
	../backup_check/by_check_file.awk \
	../backup_check/by_check_file.sh \
	../backup_check/by_fresh_files.awk \
	../backup_check/by_fresh_files.sh \
	../backup_check/by_mysql.awk \
	../backup_check/by_mysql.sh \
	../backup_check/by_postgresql.awk \
	../backup_check/by_postgresql.sh \
	../backup_check/compare_rsnapshot_backup_with_backup_check.awk \
	../backup_check/compare_rsnapshot_backup_with_backup_check.sh \
	sysadmws-utils/opt/sysadmws-utils/backup_check
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/backup_check/*.awk
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/backup_check/*.sh

# Chown to root
sudo chown -R root:root sysadmws-utils

# Make deb
sudo dpkg-deb -b sysadmws-utils

# Chown back to me
sudo chown -R `whoami`:`whoami` sysadmws-utils
