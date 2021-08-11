BEGIN {
	total_errors    = 0;
	# Get my hostname
	hn_cmd = "hostname -f";
	hn_cmd | getline my_host_name;
	close(hn_cmd);
	# Check rsnapshot type
	if ((rsnapshot_type != "sync") && (rsnapshot_type != "hourly") && (rsnapshot_type != "daily") && (rsnapshot_type != "weekly") && (rsnapshot_type != "monthly")) {
		print_timestamp(); print("ERROR: Unknown rsnapshot type: " rsnapshot_type);
		total_errors = total_errors + 1;
		exit;
	}
}

# Func to check remote hostname
function check_ssh_remote_hostname(f_connect_user, f_host_name, f_host_port, f_row_number) {
	print_timestamp(); printf("NOTICE: Checking remote hostname: ");
	ssh_check_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " f_host_port " " f_connect_user "@" f_host_name " 'hostname'";
	# Get exit code of ssh first
	err = system(ssh_check_cmd);
	if (err == 0) {
		# Get output of hostname cmd then
		ssh_check_cmd | getline checked_host_name;
		close(ssh_check_cmd);
		if (checked_host_name != host_name) {
			print_timestamp(); print("ERROR: Remote hostname " checked_host_name " doesn't match expected hostname " host_name " on config item " f_row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		}
	}
}

# Func to check loopback batch ssh login and try to authorize
function check_ssh_loopback(f_connect_user, f_host_name, f_host_port, f_row_number) {
	print_timestamp(); printf("NOTICE: Checking remote SSH: ");
	ssh_check_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " f_host_port " " f_connect_user "@" f_host_name " 'hostname'";
	err = system(ssh_check_cmd);
	# If OK - do nothing else, if error - try to authorize
	if (err != 0) {
		print_timestamp(); print("NOTICE: SSH without password didnt work on config item " f_row_number ", trying to add server key to authorized");
		err2 = system("/opt/sysadmws/rsnapshot_backup/rsnapshot_backup_authorize_loopback.sh");
		# If authorize script OK - check ssh again
		if (err2 == 0) {
			print_timestamp(); printf("NOTICE: Checking remote SSH again: ");
			err3 = system(ssh_check_cmd);
			# If second ssh check is not OK
			if (err3 != 0) {
				print_timestamp(); print("ERROR: SSH without password failed on config item " f_row_number ", skipping to next line");
				total_errors = total_errors + 1;
				next;
			}
		# If authorize script error
		} else {
			print_timestamp(); print("ERROR: Adding key failed on config item " f_row_number ", skipping to next line");
			system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_backup_authorize_loopback_out.tmp");
			total_errors = total_errors + 1;
			next;
		}
	}
}

# Func to check batch ssh login and hostname match
function check_ssh(f_connect_user, f_host_name, f_host_port, f_row_number) {
	print_timestamp(); printf("NOTICE: Checking remote SSH: ");
	ssh_check_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " f_host_port " " f_connect_user "@" f_host_name " 'hostname'";
	err = system(ssh_check_cmd);
	if (err != 0) {
		print_timestamp(); print("ERROR: SSH without password failed on config item " f_row_number ", skipping to next line");
		total_errors = total_errors + 1;
		next;
	}
}

# Func to print timestamp at the beginning of line
function print_timestamp() {
	system("date '+%F %T ' | tr -d '\n'");
}

{
	# Check if enabled
	if (row_enabled != "true") {
		next;
	}

	# Assign variables
	host_name		= row_host;
	backup_type		= row_type;
	backup_src		= row_source;
	backup_dst		= row_path;
	retain_h		= row_retain_h;
	retain_d		= row_retain_d;
	retain_w		= row_retain_w;
	retain_m		= row_retain_m;
	rsync_args		= row_rsync_args;
	mysqldump_args		= row_mysqldump_args;
	mongo_args		= row_mongo_args;
	connect_hn		= row_connect;
	connect_user		= row_connect_user;
	connect_passwd		= row_connect_passwd;
	validate_hostname	= row_validate_hostname;
	postgresql_noclean	= row_postgresql_noclean;
	mysql_noevents		= row_mysql_noevents;
	native_txt_check	= row_native_txt_check;
	native_10h_limit	= row_native_10h_limit;
	before_backup_check	= row_before_backup_check;
	exec_before_rsync	= row_exec_before_rsync;
	exec_after_rsync	= row_exec_after_rsync;

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

	# Default validate_hostname
	if (validate_hostname == "null") {
		validate_hostname = 1;
	} else if (validate_hostname == "true") {
		validate_hostname = 1;
	} else {
		validate_hostname = 0;
	}

	# Default postgresql_noclean
	if (postgresql_noclean == "null") {
		postgresql_noclean = 0;
	} else if (postgresql_noclean == "true") {
		postgresql_noclean = 1;
	} else {
		postgresql_noclean = 0;
	}

	# Default mysql_noevents
	if (mysql_noevents == "null") {
		mysql_noevents = 0;
	} else if (mysql_noevents == "true") {
		mysql_noevents = 1;
	} else {
		mysql_noevents = 0;
	}

	# Check mysqldump_args
	if (mysqldump_args == "null") {
		mysqldump_args = "";
	}

	# Default native_txt_check
	if (native_txt_check == "null") {
		native_txt_check = 0;
	} else if (native_txt_check == "true") {
		native_txt_check = 1;
	} else {
		native_txt_check = 0;
	}

	# Default native_10h_limit
	if (native_10h_limit == "null") {
		native_10h_limit = 0;
	} else if (native_10h_limit == "true") {
		native_10h_limit = 1;
	} else {
		native_10h_limit = 0;
	}

	# Default exec_before_rsync
	if (exec_before_rsync == "null") {
		exec_before_rsync = "";
	}

	# Default exec_after_rsync
	if (exec_after_rsync == "null") {
		exec_after_rsync = "";
	}

	# Display what do we backup
	print_timestamp(); print("NOTICE: Backup config line " row_number ": '" host_name " " backup_type " " backup_src " " backup_dst " " retain_h " " retain_d " " retain_w " " retain_m " " rsync_args " " mongo_args " " connect_hn " " connect_user " " connect_passwd " " row_comment "'");

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
			print_timestamp(); print("ERROR: Backup failed on config item " row_number);
			total_errors = total_errors + 1;
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
		}
		next;
	}

	# Exec before_backup_check
	if (before_backup_check != "null") {
		print_timestamp(); print("NOTICE: Executing local before_backup_check '" before_backup_check "' on config item " row_number);
		# Get exit code of script
		err = system(before_backup_check);
		if (err == 0) {
			print_timestamp(); print("NOTICE: Local execution of before_backup_check succeeded on config item " row_number);
		} else {
			print_timestamp(); print("ERROR: Local execution of before_backup_check failed on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next
		}
	}

	# Main
	if (backup_type == "RSYNC_SSH") {
		# Default ssh and rsync args
		if (rsync_args == "null") {
			rsync_args = "";
		}
		# Decide which port to use
		if (match(connect_hn, ":")) {
			connect_port = substr(connect_hn, RSTART + 1);
			connect_hn = substr(connect_hn, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port;
		} else {
			connect_port = "22";
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p 22";
		}
		# If connect to self call func with autoauthorization
		if (host_name == my_host_name) {
			print_timestamp(); print("NOTICE: Loopback connect detected on config item " row_number);
			check_ssh_loopback(connect_user, connect_hn, connect_port, row_number);
		} else {
			check_ssh(connect_user, connect_hn, connect_port, row_number);
		}
		# Validate hostname if needed
		if (validate_hostname) {
			print_timestamp(); print("NOTICE: Hostname validation required on config item " row_number);
			check_ssh_remote_hostname(connect_user, connect_hn, connect_port, row_number);
		}
		# Exec exec_before_rsync
		if (exec_before_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_before_rsync '" exec_before_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_before_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_before_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_before_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
		#
		if (backup_src == "UBUNTU") {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_UBUNTU.conf";
		} else if (backup_src == "DEBIAN") {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_DEBIAN.conf";
		} else if (backup_src == "CENTOS") {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_CENTOS.conf";
		} else if (match(backup_src, /UBUNTU\^/)) {
			split(substr(backup_src, 8), backup_excludes, ",");
			grep_part = " | grep -v ";
			for (backup_exclude in backup_excludes) {
				grep_part = grep_part "-e \"^backup.*" backup_excludes[backup_exclude] "\" ";
			}
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_UBUNTU.conf" grep_part;
			backup_src = "UBUNTU";
		} else if (match(backup_src, /DEBIAN\^/)) {
			split(substr(backup_src, 8), backup_excludes, ",");
			grep_part = " | grep -v ";
			for (backup_exclude in backup_excludes) {
				grep_part = grep_part "-e \"^backup.*" backup_excludes[backup_exclude] "\" ";
			}
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_DEBIAN.conf" grep_part;
			backup_src = "DEBIAN";
		} else if (match(backup_src, /CENTOS\^/)) {
			split(substr(backup_src, 8), backup_excludes, ",");
			grep_part = " | grep -v ";
			for (backup_exclude in backup_excludes) {
				grep_part = grep_part "-e \"^backup.*" backup_excludes[backup_exclude] "\" ";
			}
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_CENTOS.conf" grep_part;
			backup_src = "CENTOS";
		} else {
			template_file = "cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf";
		}
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			rsync_args = rsync_args " --no-compress";
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
			-e 's#__HOST_NAME__#" connect_hn "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__SRC__#" backup_src "/" "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " rsync_args "#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on config item " row_number);
				total_errors = total_errors + 1;
				system(template_file " | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" connect_hn "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__SRC__#" backup_src "/" "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " rsync_args " --no-compress#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on config item " row_number);
					total_errors = total_errors + 1;
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
		}
		# Exec exec_after_rsync
		if (exec_after_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_after_rsync '" exec_after_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_after_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_after_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_after_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
	} else if (backup_type == "POSTGRESQL_SSH") {
		# Default ssh and rsync args
		if (rsync_args == "null") {
			rsync_args = "";
		}
		# Decide which port to use
		if (match(connect_hn, ":")) {
			connect_port = substr(connect_hn, RSTART + 1);
			connect_hn = substr(connect_hn, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port;
			scp_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -P " connect_port;
		} else {
			connect_port = "22";
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p 22";
			scp_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -P 22";
		}
		# If connect to self call func with autoauthorization
		if (host_name == my_host_name) {
			print_timestamp(); print("NOTICE: Loopback connect detected on config item " row_number);
			check_ssh_loopback(connect_user, connect_hn, connect_port, row_number);
		} else {
			check_ssh(connect_user, connect_hn, connect_port, row_number);
		}
		# Validate hostname if needed
		if (validate_hostname) {
			print_timestamp(); print("NOTICE: Hostname validation required on config item " row_number);
			check_ssh_remote_hostname(connect_user, connect_hn, connect_port, row_number);
		}
		# Exec exec_before_rsync
		if (exec_before_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_before_rsync '" exec_before_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_before_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_before_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_before_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
		#
		if (postgresql_noclean) {
			print_timestamp(); print("NOTICE: postgresql_noclean set to T on config item " row_number);
			clean_part = "";
		} else {
			print_timestamp(); print("NOTICE: postgresql_noclean set to F on config item " row_number);
			clean_part = "--clean";
		}
		# Upload helper script
		make_tmp_file_cmd = "scp -q " scp_args " /opt/sysadmws/rsnapshot_backup/rsnapshot_backup_postgresql_query1.sql " connect_user "@" connect_hn ":/tmp/";
		print_timestamp(); print("NOTICE: Running remote helper script upload");
		err = system(make_tmp_file_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote helper script upload failed on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote helper script upload finished on config item " row_number);
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
			make_dump_cmd = "set -x && ssh " ssh_args " " connect_user "@" connect_hn " '" mkdir_part " && " chmod_part " && " lock_part " && " find_part " && " globals_part " && " dblist_part " && { for db in `cat /var/backups/postgresql/db_list.txt`; do ( [ -f /var/backups/postgresql/$db.gz ] || su - postgres -c \"pg_dump --create " clean_part " --verbose $db 2>/dev/null\" | gzip > /var/backups/postgresql/$db.gz ); done } '";
		} else {
			make_dump_cmd = "set -x && ssh " ssh_args " " connect_user "@" connect_hn " '" mkdir_part " && " chmod_part " && " lock_part " && " find_part " && " globals_part " && ( [ -f /var/backups/postgresql/" backup_src ".gz ] || su - postgres -c \"pg_dump --create " clean_part " --verbose " backup_src " 2>/dev/null\" | gzip > /var/backups/postgresql/" backup_src ".gz ) '";
		}
		print_timestamp(); print("NOTICE: Running remote dump:");
		err = system(make_dump_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote dump failed on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote dump finished on config item " row_number);
		}
		# Remove partially downloaded dumps
                system("rm -f " backup_dst "/.sync/rsnapshot/var/backups/postgresql/.*.gz.*");
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			rsync_args = rsync_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" connect_hn "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " rsync_args "#g' \
			-e 's#__SRC__#" "/var/backups/postgresql/#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on config item " row_number);
				total_errors = total_errors + 1;
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" connect_hn "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " rsync_args " --no-compress#g' \
					-e 's#__SRC__#" "/var/backups/postgresql/#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on config item " row_number);
					total_errors = total_errors + 1;
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
		}
		# Exec exec_after_rsync
		if (exec_after_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_after_rsync '" exec_after_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_after_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_after_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_after_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
	} else if (backup_type == "MYSQL_SSH") {
		# Default ssh and rsync args
		if (rsync_args == "null") {
			rsync_args = "";
		}
		# Decide which port to use
		if (match(connect_hn, ":")) {
			connect_port = substr(connect_hn, RSTART + 1);
			connect_hn = substr(connect_hn, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port;
		} else {
			connect_port = "22";
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p 22";
		}
		# If connect to self call func with autoauthorization
		if (host_name == my_host_name) {
			print_timestamp(); print("NOTICE: Loopback connect detected on config item " row_number);
			check_ssh_loopback(connect_user, connect_hn, connect_port, row_number);
		} else {
			check_ssh(connect_user, connect_hn, connect_port, row_number);
		}
		# Validate hostname if needed
		if (validate_hostname) {
			print_timestamp(); print("NOTICE: Hostname validation required on config item " row_number);
			check_ssh_remote_hostname(connect_user, connect_hn, connect_port, row_number);
		}
		# Exec exec_before_rsync
		if (exec_before_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_before_rsync '" exec_before_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_before_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_before_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_before_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
		#
		if (mysql_noevents) {
			print_timestamp(); print("NOTICE: mysql_noevents set to T on config item " row_number);
			events_part = "";
		} else {
			print_timestamp(); print("NOTICE: mysql_noevents set to F on config item " row_number);
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
			dblist_part = "mysql --defaults-file=/etc/mysql/debian.cnf --skip-column-names --batch -e \"SHOW DATABASES;\" | grep -v -e information_schema -e performance_schema | " grep_part " > /var/backups/mysql/db_list.txt";
			backup_src = "ALL";
		} else {
			dblist_part = "mysql --defaults-file=/etc/mysql/debian.cnf --skip-column-names --batch -e \"SHOW DATABASES;\" | grep -v -e information_schema -e performance_schema > /var/backups/mysql/db_list.txt";
		}
		if (backup_src == "ALL") {
			make_dump_cmd = "set -x && ssh " ssh_args " " connect_user "@" connect_hn " '" mkdir_part " && " lock_part " && " find_part " && " dblist_part " && { for db in `cat /var/backups/mysql/db_list.txt`; do ( [ -f /var/backups/mysql/$db.gz ] || mysqldump --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --skip-lock-tables " events_part " --databases $db " mysqldump_args " --max_allowed_packet=1G | gzip > /var/backups/mysql/$db.gz ); done } '";
		} else {
			make_dump_cmd = "set -x && ssh " ssh_args " " connect_user "@" connect_hn " '" mkdir_part " && " lock_part " && " find_part " && ( [ -f /var/backups/mysql/" backup_src ".gz ] || mysqldump --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --skip-lock-tables " events_part " --databases " backup_src " " mysqldump_args " --max_allowed_packet=1G | gzip > /var/backups/mysql/" backup_src ".gz ) '";
		}
		print_timestamp(); print("NOTICE: Running remote dump:");
		err = system(make_dump_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote dump failed on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote dump finished on config item " row_number);
		}
		# Remove partially downloaded dumps
                system("rm -f " backup_dst "/.sync/rsnapshot/var/backups/mysql/.*.gz.*");
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			rsync_args = rsync_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" connect_hn "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " rsync_args "#g' \
			-e 's#__SRC__#" "/var/backups/mysql/#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on config item " row_number);
				total_errors = total_errors + 1;
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" connect_hn "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " rsync_args " --no-compress#g' \
					-e 's#__SRC__#" "/var/backups/mysql/#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on config item " row_number);
					total_errors = total_errors + 1;
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
		}
		# Exec exec_after_rsync
		if (exec_after_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_after_rsync '" exec_after_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_after_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_after_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_after_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
	} else if (backup_type == "MONGODB_SSH") {
		# Default ssh and rsync args
		if (rsync_args == "null") {
			rsync_args = "";
		}
		# Default mongo args
		if (mongo_args == "null") {
			mongo_args = "";
		}
		# Decide which port to use
		if (match(connect_hn, ":")) {
			connect_port = substr(connect_hn, RSTART + 1);
			connect_hn = substr(connect_hn, 1, RSTART - 1);
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port;
			scp_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -P " connect_port;
		} else {
			connect_port = "22";
			ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -p 22";
			scp_args = "-o BatchMode=yes -o StrictHostKeyChecking=no -P 22";
		}
		# If connect to self call func with autoauthorization
		if (host_name == my_host_name) {
			print_timestamp(); print("NOTICE: Loopback connect detected on config item " row_number);
			check_ssh_loopback(connect_user, connect_hn, connect_port, row_number);
		} else {
			check_ssh(connect_user, connect_hn, connect_port, row_number);
		}
		# Validate hostname if needed
		if (validate_hostname) {
			print_timestamp(); print("NOTICE: Hostname validation required on config item " row_number);
			check_ssh_remote_hostname(connect_user, connect_hn, connect_port, row_number);
		}
		# Exec exec_before_rsync
		if (exec_before_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_before_rsync '" exec_before_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_before_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_before_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_before_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
		# Upload helper script
		make_tmp_file_cmd = "scp -q " scp_args " /opt/sysadmws/rsnapshot_backup/mongodb_db_list.sh " connect_user "@" connect_hn ":/tmp/";
		print_timestamp(); print("NOTICE: Running remote helper script upload");
		err = system(make_tmp_file_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote helper script upload failed on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote helper script upload finished on config item " row_number);
		}
		#
		mkdir_part = "mkdir -p /var/backups/mongodb";
		chmod_part = "chmod 755 /tmp/mongodb_db_list.sh";
		lock_part = "{ while [ -d /var/backups/mongodb/dump.lock ]; do sleep 5; done } && mkdir /var/backups/mongodb/dump.lock && trap \"rm -rf /var/backups/mongodb/dump.lock\" 0";
		# If hourly retains are used keep dumps only for 59 minutes
		if (retain_h != "NONE") {
			find_part = "cd /var/backups/mongodb && find /var/backups/mongodb/ -type f -name \"*.tar.gz\" -mmin +59 -delete";
		} else {
			find_part = "cd /var/backups/mongodb && find /var/backups/mongodb/ -type f -name \"*.tar.gz\" -mmin +720 -delete";
		}
		if (match(backup_src, /ALL\^/)) {
			split(substr(backup_src, 5), db_excludes, ",");
			grep_part = "grep -v ";
			for (db_exclude in db_excludes) {
				grep_part = grep_part "-e " db_excludes[db_exclude] " ";
			}
			dblist_part = "/tmp/mongodb_db_list.sh " mongo_args " | grep -v -e local | " grep_part " > /var/backups/mongodb/db_list.txt";
			backup_src = "ALL";
		} else {
			dblist_part = "/tmp/mongodb_db_list.sh " mongo_args " | grep -v -e local > /var/backups/mongodb/db_list.txt";
		}
		if (backup_src == "ALL") {
			make_dump_cmd = "set -x && ssh " ssh_args " " connect_user "@" connect_hn " '" mkdir_part " && " chmod_part " && " lock_part " && " find_part " && " dblist_part " && { for db in `cat /var/backups/mongodb/db_list.txt`; do ( [ -f /var/backups/mongodb/$db.tar.gz ] || { mongodump " mongo_args " --quiet --out /var/backups/mongodb --dumpDbUsersAndRoles --db $db && cd /var/backups/mongodb && tar zcvf /var/backups/mongodb/$db.tar.gz $db && rm -rf /var/backups/mongodb/$db; } ); done } '";
		} else {
			make_dump_cmd = "set -x && ssh " ssh_args " " connect_user "@" connect_hn " '" mkdir_part " && " chmod_part " && " lock_part " && " find_part " && ( [ -f /var/backups/mongodb/" backup_src ".tar.gz ] || { mongodump " mongo_args " --quiet --out /var/backups/mongodb --dumpDbUsersAndRoles --db " backup_src " && cd /var/backups/mongodb && tar zcvf /var/backups/mongodb/" backup_src ".tar.gz " backup_src " && rm -rf /var/backups/mongodb/" backup_src "; } ) '";
		}
		print_timestamp(); print("NOTICE: Running remote dump:");
		err = system(make_dump_cmd);
		if (err != 0) {
			print_timestamp(); print("ERROR: Remote dump failed on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		} else {
			print_timestamp(); print("NOTICE: Remote dump finished on config item " row_number);
		}
		# Remove partially downloaded dumps
                system("rm -f " backup_dst "/.sync/rsnapshot/var/backups/mongodb/.*.tar.gz.*");
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			rsync_args = rsync_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" connect_hn "#g' \
			-e 's#__SSH_ARGS__#" ssh_args "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " rsync_args "#g' \
			-e 's#__SRC__#" "/var/backups/mongodb/#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on config item " row_number);
				total_errors = total_errors + 1;
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_SSH_PATH.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" connect_hn "#g' \
					-e 's#__SSH_ARGS__#" ssh_args "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " rsync_args " --no-compress#g' \
					-e 's#__SRC__#" "/var/backups/mongodb/#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system("bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on config item " row_number);
					total_errors = total_errors + 1;
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
		}
		# Exec exec_after_rsync
		if (exec_after_rsync != "") {
			print_timestamp(); print("NOTICE: Executing remote exec_after_rsync '" exec_after_rsync "' on config item " row_number);
			ssh_exec_cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p " connect_port " " connect_user "@" connect_hn " '" exec_after_rsync "'";
			# Get exit code of script
			err = system(ssh_exec_cmd);
			if (err == 0) {
				print_timestamp(); print("NOTICE: Remote execution of exec_after_rsync succeeded on config item " row_number);
			} else {
				print_timestamp(); print("ERROR: Remote execution of exec_after_rsync failed on config item " row_number ", but script continues");
				total_errors = total_errors + 1;
			}
		}
	} else if (backup_type == "RSYNC_NATIVE") {
		# Default ssh and rsync args
		if (rsync_args == "null") {
			rsync_args = "";
		}
		# If native rsync - password is mandatory (passwordless rsync is unsafe)
		if (connect_passwd == "null") {
			print_timestamp(); print("ERROR: No Rsync password provided for native rsync on config item " row_number ", skipping to next line");
			total_errors = total_errors + 1;
			next;
		}
		if (native_txt_check) {
			print_timestamp(); print("NOTICE: native_txt_check set to True on config item " row_number);
			# Check remote .backup existance, if no file - skip to next. Remote windows rsync server can give empty set in some cases, which can lead to backup to be erased.
			system("touch /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
			system("chmod 600 /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
			system("echo '" connect_passwd "' > /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
			err = system("rsync --password-file=/opt/sysadmws/rsnapshot_backup/rsnapshot.passwd rsync://" connect_user "@" connect_hn "" backup_src "/ | grep .backup");
			if (err != 0) {
				print_timestamp(); print("ERROR: .backup not found, failed on config item " row_number ", skipping to next line");
				total_errors = total_errors + 1;
				next;
			} else {
				print_timestamp(); print("NOTICE: .backup found on config item " row_number);
			}
			system("rm -f /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		}
		if (native_10h_limit) {
			print_timestamp(); print("NOTICE: native_10h_limit set to T on config item " row_number);
			timeout_prefix = "timeout --preserve-status -k 60 10h ";
		} else {
			print_timestamp(); print("NOTICE: native_10h_limit set to F on config item " row_number);
			timeout_prefix = "";
		}
		# Check no compress file
		checknc = system("test -f /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
		if (checknc == 0) {
			rsync_args = rsync_args " --no-compress";
			print_timestamp(); print("NOTICE: no-compress_" row_number " file detected, adding --no-compress to rsync args");
		}
		# Prepare config and run
		system("touch /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		system("chmod 600 /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		system("echo '" connect_passwd "' > /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
		system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_NATIVE.conf | sed \
			-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
			-e 's/#_h_#/" h_comment "/g' \
			-e 's#__H__#" retain_h "#g' \
			-e 's#__D__#" retain_d "#g' \
			-e 's#__W__#" retain_w "#g' \
			-e 's#__M__#" retain_m "#g' \
			-e 's#__USER__#" connect_user "#g' \
			-e 's#__HOST_NAME__#" connect_hn "#g' \
			-e 's#__SRC__#" backup_src "/" "#g' \
			-e 's#__VERB_LEVEL__#" verb_level "#g' \
			-e 's#__ARGS__#" verbosity_args " " rsync_args "#g' \
			> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
		print_timestamp(); print("NOTICE: Running rsnapshot " rsnapshot_type);
		err = system(timeout_prefix "bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
		if (err != 0) {
			check = system("grep -q 'inflate returned -3' /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log");
			if (check == 0) {
				print_timestamp(); print("ERROR: Backup failed with inflate error on config item " row_number);
				total_errors = total_errors + 1;
				system("cat /opt/sysadmws/rsnapshot_backup/rsnapshot_conf_template_RSYNC_NATIVE.conf | sed \
					-e 's#__SNAPSHOT_ROOT__#" backup_dst "#g' \
					-e 's/#_h_#/" h_comment "/g' \
					-e 's#__H__#" retain_h "#g' \
					-e 's#__D__#" retain_d "#g' \
					-e 's#__W__#" retain_w "#g' \
					-e 's#__M__#" retain_m "#g' \
					-e 's#__USER__#" connect_user "#g' \
					-e 's#__HOST_NAME__#" connect_hn "#g' \
					-e 's#__SRC__#" backup_src "/" "#g' \
					-e 's#__VERB_LEVEL__#" verb_level "#g' \
					-e 's#__ARGS__#" verbosity_args " " rsync_args " --no-compress#g' \
					> /opt/sysadmws/rsnapshot_backup/rsnapshot.conf");
				print_timestamp(); print("NOTICE: Re-running rsnapshot with --no-compress " rsnapshot_type);
				err2 = system(timeout_prefix "bash -c 'set -o pipefail; rsnapshot -c /opt/sysadmws/rsnapshot_backup/rsnapshot.conf " rsnapshot_type " 2>&1 | tee /opt/sysadmws/rsnapshot_backup/rsnapshot_last_out.log'");
				if (err2 != 0) {
					print_timestamp(); print("ERROR: Backup failed on config item " row_number);
					total_errors = total_errors + 1;
				} else {
					system("touch /opt/sysadmws/rsnapshot_backup/no-compress_" row_number);
					print_timestamp(); print("NOTICE: no-compress_" row_number " file created");
					print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
				}
			}
		} else {
			print_timestamp(); print("NOTICE: Rsnapshot finished on config item " row_number);
		}
		system("rm -f /opt/sysadmws/rsnapshot_backup/rsnapshot.passwd");
	} else {
		print_timestamp(); print("ERROR: unknown backup type: " backup_type);
		total_errors = total_errors + 1;
	}
}
END {
	# Summ results
	my_folder = "/opt/sysadmws/rsnapshot_backup";
	system("awk '{ print $1 + " total_errors "}' < " my_folder "/rsnapshot_backup_error_count.txt > " my_folder "/rsnapshot_backup_error_count.txt.new && mv -f " my_folder "/rsnapshot_backup_error_count.txt.new " my_folder "/rsnapshot_backup_error_count.txt");
	# Total errors
	if (total_errors == 0) {
		print_timestamp(); print("NOTICE: rsnapshot_backup on server " my_host_name " run OK");
	} else {
		print_timestamp(); print("ERROR: rsnapshot_backup on server " my_host_name " errors found: " total_errors);
		exit(1);
	}
}
