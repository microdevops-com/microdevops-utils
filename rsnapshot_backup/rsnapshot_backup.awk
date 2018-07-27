BEGIN {
	# Check rsnapshot type
	if ((rsnapshot_type != "sync") && (rsnapshot_type != "hourly") && (rsnapshot_type != "daily") && (rsnapshot_type != "weekly") && (rsnapshot_type != "monthly")) {
		print_timestamp(); print("ERROR: Unknown rsnapshot type: " rsnapshot_type);
		exit;
	}
}

# Func to check batch ssh login and hostname match
function check_ssh(f_connect_user, f_host_name, f_row_number) {
	print_timestamp(); printf("NOTICE: Checked hostname: ");
	ssh_check_cmd = "ssh -o BatchMode=yes " f_connect_user "@" f_host_name " 'hostname'";
	err = system(ssh_check_cmd);
	if (err != 0) {
		print_timestamp(); print("ERROR: SSH without password failed on line " f_row_number ", skipping to next line");
		next;
	} else {
		ssh_check_cmd | getline checked_host_name;
		close(ssh_check_cmd);
		if (checked_host_name != host_name) {
			print_timestamp(); print("ERROR: Remote hostname doesn't match config hostname on line " f_row_number ", skipping to next line");
			next;
		}
	}
}
# Func to check batch ssh login and hostname match
function check_ssh_no_hostname_custom_port(f_connect_user, f_host_name, f_host_port, f_row_number) {
	print_timestamp(); printf("NOTICE: Checked hostname: ");
	ssh_check_cmd = "ssh -o BatchMode=yes -p " f_host_port " " f_connect_user "@" f_host_name " 'hostname'";
	err = system(ssh_check_cmd);
	if (err != 0) {
		print_timestamp(); print("ERROR: SSH without password failed on line " f_row_number ", skipping to next line");
		next;
	}
}
# Func to print timestamp at the beginning of line
function print_timestamp() {
	system("date '+%F %T ' | tr -d '\n'");
}

{
	# Assign variables
	host_name	= row_connect;
	backup_type	= row_type;
	backup_src	= row_source;
	backup_dst	= row_path;
	retain_h	= row_retain_h;
	retain_d	= row_retain_d;
	retain_w	= row_retain_w;
	retain_m	= row_retain_m;
	run_args	= row_run_args;
	connect_user	= row_connect_user;
	connect_passwd	= row_connect_passwd;
	
	# Check retains
	if (retain_h == "null") {
		retain_h = "NONE";
		h_comment = "#";
	} else {
		h_comment = "";
	}
	if (retain_d == "null") {
		retain_d = "7";
	}
	if (retain_w == "null") {
		retain_w = "4";
	}
	if (retain_m == "null") {
		retain_m = "3";
	}

	# Default user
	if (connect_user == "null") {
		connect_user = "root";
	}

	# Display what we backup
	print_timestamp(); print("NOTICE: Backup config line " row_number ": '" host_name " " backup_type " " backup_src " " backup_dst " " retain_h " " retain_d " " retain_w " " retain_m " " run_args " " connect_user " " connect_passwd "'");

	# Progress bar on verbosity
	if (verbosity == "1") {
		verb_level = "5"
		verbosity_args = " --human-readable --progress ";
	} else {
		verb_level = "2"
		verbosity_args = " ";
	}

	# Process hourly, daily, weekly, monthly rotations
	if ((rsnapshot_type == "hourly") || (rsnapshot_type == "daily") || (rsnapshot_type == "weekly") || (rsnapshot_type == "monthly")) {
		# Process each backup_dst only once
		if (backup_dst == backup_dst_save) {
			next;
		}
		backup_dst_save = backup_dst;
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_ROTATE.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type);
		if (err != 0) {
			print_timestamp(); print("ERROR: Backup failed on line " row_number);
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
		}
		next;
	}

	# Main
	if ((backup_type == "FS_RSYNC_SSH") || (backup_type == "FS_RSYNC_SSH_NOCHECK")) {
		# Default ssh and rsync args
		if (run_args == "null") {
			run_args = "";
		}
		if (match(host_name, ":")) {
			host_port = substr(host_name, RSTART + 1);
			host_name = substr(host_name, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -p " host_port;
			# Check batch ssh login only
			check_ssh_no_hostname_custom_port(connect_user, host_name, host_port, row_number);
		} else if (backup_type == "FS_RSYNC_SSH_NOCHECK") {
			ssh_args = "-o BatchMode=yes -p 22"
			# Check batch ssh login only
			check_ssh_no_hostname_custom_port(connect_user, host_name, "22", row_number);
		} else {
			ssh_args = "-o BatchMode=yes -p 22"
			# Check batch ssh login and hostname match
			check_ssh(connect_user, host_name, row_number);
		}
		#
		if (backup_src == "UBUNTU") {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_UBUNTU.conf";
		} else if (backup_src == "DEBIAN") {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_DEBIAN.conf";
		} else if (backup_src == "CENTOS") {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_CENTOS.conf";
		} else if (match(backup_src, /UBUNTU\^/)) {
			split(substr(backup_src, 8), backup_excludes, ",");
			grep_part = " | grep -v ";
			for (backup_exclude in backup_excludes) {
				grep_part = grep_part "-e \"^backup.*" backup_excludes[backup_exclude] "\" ";
			}
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_UBUNTU.conf" grep_part;
			backup_src = "UBUNTU";
		} else if (match(backup_src, /DEBIAN\^/)) {
			split(substr(backup_src, 8), backup_excludes, ",");
			grep_part = " | grep -v ";
			for (backup_exclude in backup_excludes) {
				grep_part = grep_part "-e \"^backup.*" backup_excludes[backup_exclude] "\" ";
			}
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_DEBIAN.conf" grep_part;
			backup_src = "DEBIAN";
		} else if (match(backup_src, /CENTOS\^/)) {
			split(substr(backup_src, 8), backup_excludes, ",");
			grep_part = " | grep -v ";
			for (backup_exclude in backup_excludes) {
				grep_part = grep_part "-e \"^backup.*" backup_excludes[backup_exclude] "\" ";
			}
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_CENTOS.conf" grep_part;
			backup_src = "CENTOS";
		} else {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf";
		}
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			run_args = run_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system(template_file " | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" host_name "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__SRC__#" backup_src "/" "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " run_args "#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on line " row_number);
				system(template_file " | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" host_name "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__SRC__#" backup_src "/" "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " run_args " --no-compress#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on line " row_number);
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
		}
	} else if ((backup_type == "POSTGRESQL") || (backup_type == "POSTGRESQL_NOCLEAN") || (backup_type == "POSTGRESQL_NOCLEAN_NOCHECK") || (backup_type == "POSTGRESQL_NOCHECK")) {
		# Default ssh and rsync args
		if (run_args == "null") {
			run_args = "";
		}
		if (match(host_name, ":")) {
			host_port = substr(host_name, RSTART + 1);
			host_name = substr(host_name, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -p " host_port;
			scp_args = "-o BatchMode=yes -P " host_port;
			# Check batch ssh login only
			check_ssh_no_hostname_custom_port(connect_user, host_name, host_port, row_number);
		} else if ((backup_type == "POSTGRESQL_NOCLEAN_NOCHECK") || (backup_type == "POSTGRESQL_NOCHECK")) {
			ssh_args = "-o BatchMode=yes -p 22"
			scp_args = "-o BatchMode=yes -P 22"
			# Check batch ssh login only
			check_ssh_no_hostname_custom_port(connect_user, host_name, "22", row_number);
		} else {
			ssh_args = "-o BatchMode=yes -p 22"
			scp_args = "-o BatchMode=yes -P 22"
			# Check batch ssh login and hostname match
			check_ssh(connect_user, host_name, row_number);
		}
		#
		if ((backup_type == "POSTGRESQL_NOCLEAN") || (backup_type == "POSTGRESQL_NOCLEAN_NOCHECK")) {
			clean_part = "";
		} else {
			clean_part = "--clean";
		}
		#
		make_tmp_file_cmd = "scp " scp_args " /opt/sysadmws/rsnapshot_backup/rsnapshot_backup_postgresql_query1.sql " connect_user "@" host_name ":/tmp/";
		print_timestamp(); print("NOTICE: Running remote temp file creation");
		err = system(make_tmp_file_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote temp file creation failed on line " row_number ", skipping to next line");
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote temp file creation finished on line " row_number);
		}
		#
		mkdir_part = "mkdir -p /var/backups/postgresql";
		chmod_part = "chmod 644 /tmp/rsnapshot_backup_postgresql_query1.sql";
                lock_part = "{ while [ -d /var/backups/postgresql/dump.lock ]; do sleep 5; done } && mkdir /var/backups/postgresql/dump.lock && trap \"rm -rf /var/backups/postgresql/dump.lock\" 0";
		# If hourly retains are used keep dumps only for 59 minutes
		if (retain_h != "NONE") {
			find_part = "cd /var/backups/postgresql && find /var/backups/postgresql/ -type f -name \"*.gz\" -mmin +59 -delete";
		} else {
			find_part = "cd /var/backups/postgresql && find /var/backups/postgresql/ -type f -name \"*.gz\" -mmin +720 -delete";
		}
		globals_part = "su - postgres -c \"pg_dumpall --clean --schema-only --verbose 2>/dev/null\" | gzip > /var/backups/postgresql/globals.gz";
                if (match(backup_src, /ALL\^/)) {
                        split(substr(backup_src, 5), db_excludes, ",");
                        grep_part = "grep -v ";
                        for (db_exclude in db_excludes) {
                                grep_part = grep_part "-e " db_excludes[db_exclude] " ";
                        }
                        dblist_part = "su - postgres -c \"cat /tmp/rsnapshot_backup_postgresql_query1.sql | psql --no-align -t template1\" | " grep_part " > /var/backups/postgresql/db_list.txt";
                        backup_src = "ALL";
                } else {
                        dblist_part = "su - postgres -c \"cat /tmp/rsnapshot_backup_postgresql_query1.sql | psql --no-align -t template1\" > /var/backups/postgresql/db_list.txt";
                }
		if (backup_src == "ALL") {
			make_dump_cmd = "ssh " ssh_args " " connect_user "@" host_name " '" mkdir_part " && " chmod_part " && " lock_part " && " find_part " && " globals_part " && " dblist_part " && { for db in `cat /var/backups/postgresql/db_list.txt`; do ( [ -f /var/backups/postgresql/$db.gz ] || su - postgres -c \"pg_dump --create " clean_part " --verbose $db 2>/dev/null\" | gzip > /var/backups/postgresql/$db.gz ); done } '";
		} else {
			make_dump_cmd = "ssh " ssh_args " " connect_user "@" host_name " '" mkdir_part " && " chmod_part " && " lock_part " && " find_part " && " globals_part " && ( [ -f /var/backups/postgresql/" backup_src ".gz ] || su - postgres -c \"pg_dump --create " clean_part " --verbose " backup_src " 2>/dev/null\" | gzip > /var/backups/postgresql/" backup_src ".gz ) '";
		}
		print_timestamp(); print("NOTICE: Running remote dump");
		err = system(make_dump_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote dump failed on line " row_number ", skipping to next line");
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote dump finished on line " row_number);
		}
		# Remove partially downloaded dumps
                system("rm -f " backup_dst "/.sync/rsnapshot/var/backups/postgresql/.*.gz.*");
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			run_args = run_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" host_name "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " run_args "#g' \
			-e 's#__SRC__#" "/var/backups/postgresql/#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on line " row_number);
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" host_name "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " run_args " --no-compress#g' \
					-e 's#__SRC__#" "/var/backups/postgresql/#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on line " row_number);
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
		}
	} else if ((backup_type == "MYSQL") || (backup_type == "MYSQL_NOEVENTS") || (backup_type == "MYSQL_NOEVENTS_NOCHECK") || (backup_type == "MYSQL_NOCHECK")) {
		# Default ssh and rsync args
		if (run_args == "null") {
			run_args = "";
		}
		if (match(host_name, ":")) {
			host_port = substr(host_name, RSTART + 1);
			host_name = substr(host_name, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -p " host_port;
			# Check batch ssh login only
			check_ssh_no_hostname_custom_port(connect_user, host_name, host_port, row_number);
		} else if ((backup_type == "MYSQL_NOEVENTS_NOCHECK") || (backup_type == "MYSQL_NOCHECK")) {
			ssh_args = "-o BatchMode=yes -p 22"
			# Check batch ssh login only
			check_ssh_no_hostname_custom_port(connect_user, host_name, "22", row_number);
		} else {
			ssh_args = "-o BatchMode=yes -p 22"
			# Check batch ssh login and hostname match
			check_ssh(connect_user, host_name, row_number);
		}
		#
		if ((backup_type == "MYSQL_NOEVENTS") || (backup_type == "MYSQL_NOEVENTS_NOCHECK")) {
			events_part = "";
		} else {
			events_part = "--events";
		}
		#
		mkdir_part = "mkdir -p /var/backups/mysql";
		lock_part = "{ while [ -d /var/backups/mysql/dump.lock ]; do sleep 5; done } && mkdir /var/backups/mysql/dump.lock && trap \"rm -rf /var/backups/mysql/dump.lock\" 0";
		# If hourly retains are used keep dumps only for 59 minutes
		if (retain_h != "NONE") {
			find_part = "cd /var/backups/mysql && find /var/backups/mysql/ -type f -name \"*.gz\" -mmin +59 -delete";
		} else {
			find_part = "cd /var/backups/mysql && find /var/backups/mysql/ -type f -name \"*.gz\" -mmin +720 -delete";
		}
		if (match(backup_src, /ALL\^/)) {
			split(substr(backup_src, 5), db_excludes, ",");
			grep_part = "grep -v ";
			for (db_exclude in db_excludes) {
				grep_part = grep_part "-e " db_excludes[db_exclude] " ";
			}
			dblist_part = "mysql --defaults-file=/etc/mysql/debian.cnf --skip-column-names --batch -e \"SHOW DATABASES;\" | grep -v performance_schema | " grep_part " > /var/backups/mysql/db_list.txt";
			backup_src = "ALL";
		} else {
			dblist_part = "mysql --defaults-file=/etc/mysql/debian.cnf --skip-column-names --batch -e \"SHOW DATABASES;\" | grep -v performance_schema > /var/backups/mysql/db_list.txt";
		}
		if (backup_src == "ALL") {
			make_dump_cmd = "ssh " ssh_args " " connect_user "@" host_name " '" mkdir_part " && " lock_part " && " find_part " && " dblist_part " && { for db in `cat /var/backups/mysql/db_list.txt`; do ( [ -f /var/backups/mysql/$db.gz ] || mysqldump --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --lock-tables=false " events_part " --databases $db | gzip > /var/backups/mysql/$db.gz ); done } '";
		} else {
			make_dump_cmd = "ssh " ssh_args " " connect_user "@" host_name " '" mkdir_part " && " lock_part " && " find_part " && ( [ -f /var/backups/mysql/" backup_src ".gz ] || mysqldump --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --lock-tables=false " events_part " --databases " backup_src " | gzip > /var/backups/mysql/" backup_src ".gz ) '";
		}
		print_timestamp(); print("NOTICE: Running remote dump");
		err = system(make_dump_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote dump failed on line " row_number ", skipping to next line");
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote dump finished on line " row_number);
		}
		# Remove partially downloaded dumps
                system("rm -f " backup_dst "/.sync/rsnapshot/var/backups/mysql/.*.gz.*");
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			run_args = run_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" host_name "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " run_args "#g' \
			-e 's#__SRC__#" "/var/backups/mysql/#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on line " row_number);
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_SSH_PATH.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" host_name "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " run_args " --no-compress#g' \
					-e 's#__SRC__#" "/var/backups/mysql/#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on line " row_number);
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
		}
	} else if ((backup_type == "FS_RSYNC_NATIVE") || (backup_type == "FS_RSYNC_NATIVE_TXT_CHECK") || (backup_type == "FS_RSYNC_NATIVE_TO_10H")) {
		# Default ssh and rsync args
		if (run_args == "null") {
			run_args = "";
		}
		# If native rsync - password is mandatory (passwordless rsync is unsafe)
		if (connect_passwd == "null") {
			print_timestamp(); print("ERROR: No Rsync password provided for native rsync on line " row_number ", skipping to next line");
			next;
		}
		if (backup_type == "FS_RSYNC_NATIVE_TXT_CHECK") {
			# Check remote .backup_check existance, if no file - skip to next. Remote windows rsync server can give empty set in some cases, which can lead to backup to be erased.
			system("touch /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
			system("chmod 600 /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
			system("echo '" connect_passwd "' > /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
			err = system("rsync --password-file=/opt/sysadmws/rsnapshot_backup/rsnapshot.passwd rsync://" connect_user "@" host_name "" backup_src "/ | grep .backup_check");
			if (err != 0) {
				print_timestamp(); print("ERROR: .backup_check not found, failed on line " row_number ", skipping to next line");
				next;
			} else {
				print_timestamp(); print("NOTICE: .backup_check found on line " row_number);
			}
			system("rm -f /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		}
		if (backup_type == "FS_RSYNC_NATIVE_TO_10H") {
			timeout_prefix = "timeout --preserve-status -k 60 10h ";
		} else {
			timeout_prefix = "";
		}
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			run_args = run_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("touch /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		system("chmod 600 /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		system("echo '" connect_passwd "' > /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_NATIVE.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" host_name "#g' \
			-e 's#__SRC__#" backup_src "/" "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " run_args "#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system(timeout_prefix "bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on line " row_number);
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_FS_RSYNC_NATIVE.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" host_name "#g' \
					-e 's#__SRC__#" backup_src "/" "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " run_args " --no-compress#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system(timeout_prefix "bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on line " row_number);
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
		}
		system("rm -f /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
	} else if (backup_type == "LOCAL_PREEXEC") {
		err = system(host_name);
		if (err != 0) {
			print_timestamp(); print("ERROR: Preexec failed on line " row_number ", skipping to next line");
			next;
		}
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			run_args = run_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_LOCAL_PREEXEC.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__SRC__#" backup_src "/" "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " run_args "#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on line " row_number);
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_LOCAL_PREEXEC.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__SRC__#" backup_src "/" "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " run_args " --no-compress#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on line " row_number);
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
				}
			}
			print_timestamp(); print("ERROR: Backup failed on line " row_number);
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on line " row_number);
		}
	} else {
		print_timestamp(); print("ERROR: unknown backup type: " backup_type);
	}
}
