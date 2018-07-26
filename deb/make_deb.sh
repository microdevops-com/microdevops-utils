#!/bin/sh
if [ `dirname $0` != "." ]; then
	echo "You should run this script from `dirname $0`"
	exit;
fi

# Increase a version of the package
perl -pi -e '($_=$1.q^.^.(int($2)+1).qq#\n#)if/^(Version:\s+\d+)\.(\d+)$/' sysadmws-utils-v1/DEBIAN/control

# Create dir for every util
mkdir -p sysadmws-utils-v1/opt/sysadmws/bulk_log
mkdir -p sysadmws-utils-v1/opt/sysadmws/mysql_queries_log
mkdir -p sysadmws-utils-v1/opt/sysadmws/mysql_replica_checker
mkdir -p sysadmws-utils-v1/opt/sysadmws/notify_devilry
mkdir -p sysadmws-utils-v1/opt/sysadmws/disk_alert
mkdir -p sysadmws-utils-v1/opt/sysadmws/put_check_files
mkdir -p sysadmws-utils-v1/opt/sysadmws/logrotate_db_backup
mkdir -p sysadmws-utils-v1/opt/sysadmws/mikrotik_backup
mkdir -p sysadmws-utils-v1/opt/sysadmws/rsnapshot_backup
mkdir -p sysadmws-utils-v1/opt/sysadmws/backup_check
mkdir -p sysadmws-utils-v1/opt/sysadmws/misc

# Remove all files in every util
find sysadmws-utils-v1/opt/sysadmws -type f -delete

# LICENSE README.md
cp	../LICENSE \
	../README.md \
	sysadmws-utils-v1/opt/sysadmws

# bulk_log
cp	../bulk_log/bulk_log.sh \
	../bulk_log/bulk_log.cron \
	../bulk_log/bulk_log.logrotate \
	sysadmws-utils-v1/opt/sysadmws/bulk_log

# mysql_queries_log
cp	../mysql_queries_log/mysql_queries_log.sh \
	../mysql_queries_log/mysql_queries_log.cron \
	../mysql_queries_log/mysql_queries_log.logrotate \
	sysadmws-utils-v1/opt/sysadmws/mysql_queries_log

# mysql_replica_checker
cp	../mysql_replica_checker/mysql_replica_checker.sh \
	../mysql_replica_checker/mysql_replica_checker.cron \
	../mysql_replica_checker/mysql_replica_checker.conf.sample \
	sysadmws-utils-v1/opt/sysadmws/mysql_replica_checker

# notify_devilry
cp	../notify_devilry/notify_devilry.py \
	../notify_devilry/notify_devilry_test.sh \
	../notify_devilry/notify_devilry.yaml.jinja.example \
	../notify_devilry/notify_devilry.yaml.jinja.shortex \
	sysadmws-utils-v1/opt/sysadmws/notify_devilry

# disk_alert
cp	../disk_alert/disk_alert.sh \
	../disk_alert/disk_alert.cron \
	../disk_alert/disk_alert.conf \
	../disk_alert/lr.awk \
	sysadmws-utils-v1/opt/sysadmws/disk_alert

# put_check_files
cp	../put_check_files/put_check_files.sh \
	../put_check_files/put_check_files.cron \
	../put_check_files/put_check_files.conf.sample \
	sysadmws-utils-v1/opt/sysadmws/put_check_files

# logrotate_db_backup
cp	../logrotate_db_backup/logrotate_db_backup.awk \
	../logrotate_db_backup/logrotate_db_backup.conf.sample \
	../logrotate_db_backup/logrotate_db_backup.sh \
	sysadmws-utils-v1/opt/sysadmws/logrotate_db_backup

# mikrotik_backup
cp	../mikrotik_backup/mikrotik_backup.sh \
	../mikrotik_backup/mikrotik_backup.conf.sample \
	sysadmws-utils-v1/opt/sysadmws/mikrotik_backup

# rsnapshot_backup
cp	../rsnapshot_backup/rsnapshot_backup.awk \
	../rsnapshot_backup/rsnapshot_backup.sh \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_UBUNTU.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_DEBIAN.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_CENTOS.conf \
	../rsnapshot_backup/rsnapshot_conf_template_ROTATE.conf \
	../rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_NATIVE.conf \
	../rsnapshot_backup/rsnapshot_conf_template_LOCAL_PREEXEC.conf \
	../rsnapshot_backup/rsnapshot_backup_daily.cron \
	../rsnapshot_backup/rsnapshot_backup_hourly.cron \
	../rsnapshot_backup/rsnapshot_backup_postgresql_query1.sql \
	../rsnapshot_backup/rsnapshot_backup.logrotate \
	sysadmws-utils-v1/opt/sysadmws/rsnapshot_backup

# backup_check
cp	../backup_check/backup_check.sh \
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
	sysadmws-utils-v1/opt/sysadmws/backup_check

# misc
cp	../misc/mysql_dump_all_dbs_to_files.sh \
	../misc/postgresql_dump_all_dbs_to_files.sh \
	../misc/mysql_table_extractor.sh \
	../misc/mysql_create_new_database.sh \
	sysadmws-utils-v1/opt/sysadmws/misc

# Make md5sums
cd sysadmws-utils-v1 && \
( find . -type f ! -regex '.*?debian-binary.*' ! -regex '.*?DEBIAN.*' -printf '%P ' | xargs md5sum > DEBIAN/md5sums ) && \
cd ..

# Chown to root
sudo chown -R root:root sysadmws-utils-v1

# Make deb
sudo dpkg-deb -b sysadmws-utils-v1

# Chown back to me
sudo chown -R `whoami`:`whoami` sysadmws-utils-v1
