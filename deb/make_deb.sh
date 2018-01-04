#!/bin/sh
if [ `dirname $0` != "." ]; then
	echo "You should run this script from `dirname $0`"
	exit;
fi

# Increase a version of the package
perl -pi -e '($_=$1.q^.^.(int($2)+1).qq#\n#)if/^(Version:\s+\d+)\.(\d+)$/' sysadmws-utils/DEBIAN/control

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

# mysql_queries_log
cp ../mysql_queries_log/mysql_queries_log.sh \
	sysadmws-utils/opt/sysadmws-utils/mysql_queries_log
cp ../mysql_queries_log/mysql_queries_log.cron \
	sysadmws-utils/etc/cron.d/sysadmws-mysql-queries-log
cp ../mysql_queries_log/mysql_queries_log.logrotate \
	sysadmws-utils/etc/logrotate.d/sysadmws-mysql-queries-log
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/mysql_queries_log/mysql_queries_log.sh
sudo chmod 600 sysadmws-utils/etc/cron.d/sysadmws-mysql-queries-log
sudo chmod 600 sysadmws-utils/etc/logrotate.d/sysadmws-mysql-queries-log

# mysql_replica_checker
cp ../mysql_replica_checker/mysql_replica_checker.sh \
	sysadmws-utils/opt/sysadmws-utils/mysql_replica_checker
cp ../mysql_replica_checker/mysql_replica_checker.cron \
	sysadmws-utils/etc/cron.d/sysadmws-mysql-replica-checker
cp ../mysql_replica_checker/mysql_replica_checker.conf.sample \
	sysadmws-utils/opt/sysadmws-utils/mysql_replica_checker
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/mysql_replica_checker/mysql_replica_checker.sh
sudo chmod 600 sysadmws-utils/etc/cron.d/sysadmws-mysql-replica-checker
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/mysql_replica_checker/mysql_replica_checker.conf.sample

# notify_devilry
cp ../notify_devilry/notify_devilry.py \
	sysadmws-utils/opt/sysadmws-utils/notify_devilry
cp ../notify_devilry/notify_devilry_test.sh \
	sysadmws-utils/opt/sysadmws-utils/notify_devilry
cp ../notify_devilry/notify_devilry.yaml.jinja.example \
	sysadmws-utils/opt/sysadmws-utils/notify_devilry
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/notify_devilry/notify_devilry.py
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/notify_devilry/notify_devilry_test.sh
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/notify_devilry/notify_devilry.yaml.jinja.example

# disk_alert
cp ../disk_alert/disk_alert.sh \
	sysadmws-utils/opt/sysadmws-utils/disk_alert
cp ../disk_alert/disk_alert.cron \
	sysadmws-utils/etc/cron.d/sysadmws-disk-alert
cp ../disk_alert/disk_alert.conf \
	sysadmws-utils/opt/sysadmws-utils/disk_alert
cp ../disk_alert/lr.awk \
	sysadmws-utils/opt/sysadmws-utils/disk_alert
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/disk_alert/disk_alert.sh
sudo chmod 600 sysadmws-utils/etc/cron.d/sysadmws-disk-alert
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/disk_alert/disk_alert.conf
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/disk_alert/lr.awk

# salt
cp ../salt/grains.template \
	sysadmws-utils/opt/sysadmws-utils/salt
cp ../salt/grains.ubuntu.template \
	sysadmws-utils/opt/sysadmws-utils/salt
cp ../salt/grains.postgresql.template \
	sysadmws-utils/opt/sysadmws-utils/salt
cp ../salt/grains.mysql.template \
	sysadmws-utils/opt/sysadmws-utils/salt
cp ../salt/grains.path.template \
	sysadmws-utils/opt/sysadmws-utils/salt
sudo chmod 644 sysadmws-utils/opt/sysadmws-utils/salt/grains.template
sudo chmod 644 sysadmws-utils/opt/sysadmws-utils/salt/grains.ubuntu.template
sudo chmod 644 sysadmws-utils/opt/sysadmws-utils/salt/grains.postgresql.template
sudo chmod 644 sysadmws-utils/opt/sysadmws-utils/salt/grains.mysql.template
sudo chmod 644 sysadmws-utils/opt/sysadmws-utils/salt/grains.path.template

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
	../rsnapshot_backup/rsnapshot_backup.conf_ubuntu.sh \
	../rsnapshot_backup/rsnapshot_backup.conf_postgresql.sh \
	../rsnapshot_backup/rsnapshot_backup.conf_mysql.sh \
	../rsnapshot_backup/rsnapshot_backup.conf_path.sh \
	../rsnapshot_backup/rsnapshot_backup_postgresql_query1.sql \
	sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/*
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.sh
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf_ubuntu.sh
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf_postgresql.sh
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf_mysql.sh
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/rsnapshot_backup/rsnapshot_backup.conf_path.sh
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
	../backup_check/check_rsnapshot_backup_no_compress_files.sh \
	sysadmws-utils/opt/sysadmws-utils/backup_check
sudo chmod 600 sysadmws-utils/opt/sysadmws-utils/backup_check/*.awk
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/backup_check/*.sh

# misc
cp ../misc/mysql_dump_all_dbs_to_files.sh \
	../misc/postgresql_dump_all_dbs_to_files.sh \
	../misc/mysql_table_extractor.sh \
	../misc/mysql_create_new_database.sh \
	sysadmws-utils/opt/sysadmws-utils/misc
sudo chmod 700 sysadmws-utils/opt/sysadmws-utils/misc/*.sh

# Make md5sums
cd sysadmws-utils && \
( find . -type f ! -regex '.*?debian-binary.*' ! -regex '.*?DEBIAN.*' -printf '%P ' | xargs md5sum > DEBIAN/md5sums ) && \
cd ..

# Chown to root
sudo chown -R root:root sysadmws-utils

# Make deb
sudo dpkg-deb -b sysadmws-utils

# Chown back to me
sudo chown -R `whoami`:`whoami` sysadmws-utils
