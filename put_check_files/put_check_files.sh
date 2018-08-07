#!/bin/bash

# Set vars
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
HOSTNAME=$(hostname -f)
DATE=$(date '+%F %T')
declare -A BACKUPS_PER_PATH
CONF_FILE=/opt/sysadmws/put_check_files/put_check_files.conf

# If config exists, read fields but skip comment lines
if [ -f $CONF_FILE ]; then
	cat $CONF_FILE | grep -v "^#" | while read LINE
	do
		echo "---"
		# Get config fields via regexp
		if [[ "$LINE" =~ ([^[:blank:]]+)[[:blank:]]+([^[:blank:]]+)[[:blank:]]+([^[:blank:]]+)[[:blank:]]+([^[:blank:]]+) ]]; then
			LOCAL_PATH=${BASH_REMATCH[1]}
			BACKUP_SERVER=${BASH_REMATCH[2]}
			BACKUP_DST=${BASH_REMATCH[3]}
			BACKUP_DST_TYPE=${BASH_REMATCH[4]}
			if [[ "$LOCAL_PATH" = "UBUNTU" ]]; then
				LOCAL_SUBPATHS=("/etc"
				"/home"
				"/root"
				"/var/log"
				"/var/spool/cron"
				"/usr/local"
				"/lib/ufw"
				"/opt/sysadmws")
			elif [[ "$LOCAL_PATH" = "DEBIAN" ]]; then
				LOCAL_SUBPATHS=("/etc"
				"/home"
				"/root"
				"/var/log"
				"/var/spool/cron"
				"/usr/local"
				"/lib/ufw"
				"/opt/sysadmws")
			elif [[ "$LOCAL_PATH" = "CENTOS" ]]; then
				LOCAL_SUBPATHS=("/etc"
				"/home"
				"/root"
				"/var/log"
				"/var/spool/cron"
				"/usr/local"
				"/opt/sysadmws")
			else
				LOCAL_SUBPATHS=("$LOCAL_PATH")
			fi
			echo "LOCAL_SUBPATHS: $LOCAL_SUBPATHS"
			for LOCAL_SUBPATH_LINE in ${LOCAL_SUBPATHS[@]}
			do
				echo "LOCAL_SUBPATH_LINE: $LOCAL_SUBPATH_LINE"
				echo "BACKUPS_PER_PATH: ${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]}"
				# On the first occurance BACKUPS_PER_PATH value by path key is empty, do some work on the first occurance
				if [[ _${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]} = "_" ]]; then
					echo "$LOCAL_SUBPATH_LINE/.backup REMOVED"
					rm -f "$LOCAL_SUBPATH_LINE/.backup"
					BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]=1
					echo "BACKUPS_PER_PATH: ${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]}"
					echo -e "Host: $HOSTNAME\nPath: $LOCAL_SUBPATH_LINE\nDate: $DATE" >> "$LOCAL_SUBPATH_LINE/.backup"
				fi
				echo -e "Backup ${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]} Host: $BACKUP_SERVER\nBackup ${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]} Path: $BACKUP_DST\nBackup ${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]} Path Type: $BACKUP_DST_TYPE" >> "$LOCAL_SUBPATH_LINE/.backup"
				let "BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]=${BACKUPS_PER_PATH["$LOCAL_SUBPATH_LINE"]}+1"
			done
		fi
	done
fi
