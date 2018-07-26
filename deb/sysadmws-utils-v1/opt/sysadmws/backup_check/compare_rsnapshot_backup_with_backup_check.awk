BEGIN {
	# Get my hostname
	hn_cmd = "salt-call --local grains.item fqdn 2>&1 | tail -n 1 | sed 's/^ *//'";
	hn_cmd | getline checked_host_name;
	close(hn_cmd);
	total_errors	= 0;
	total_ok        = 0;
	# Read files to arrays
	# Check File
	txt_file = "/opt/sysadmws-utils/backup_check/by_check_file.txt";
	i = 1;
	if (system("test -e " txt_file) == 0) {
		while ((getline check_file_line < txt_file) > 0) {
			if (!match(check_file_line, /^#/)) {
				split(check_file_line, line_array, "	");
				check_file_array[i, 1] = line_array[1];
				check_file_array[i, 2] = line_array[2];
				check_file_array[i, 3] = line_array[3];
				check_file_array[i, 4] = line_array[4];
				check_file_array[i, 5] = line_array[5];
				check_file_array[i, 6] = line_array[6];
				i++;
			}
		}
		close (txt_file);
	}
	check_file_array_size = i-1;
	# Fresh Files
	txt_file = "/opt/sysadmws-utils/backup_check/by_fresh_files.txt";
	i = 1;
	if (system("test -e " txt_file) == 0) {
		while ((getline fresh_file_line < txt_file) > 0) {
			if (!match(fresh_file_line, /^#/)) {
				split(fresh_file_line, line_array, "	");
				fresh_file_array[i, 1] = line_array[1];
				fresh_file_array[i, 2] = line_array[2];
				fresh_file_array[i, 3] = line_array[3];
				fresh_file_array[i, 4] = line_array[4];
				fresh_file_array[i, 5] = line_array[5];
				fresh_file_array[i, 6] = line_array[6];
				fresh_file_array[i, 7] = line_array[7];
				fresh_file_array[i, 8] = line_array[8];
				fresh_file_array[i, 9] = line_array[9];
				fresh_file_array[i, 10] = line_array[10];
				fresh_file_array[i, 11] = line_array[11];
				i++;
			}
		}
		close (txt_file);
	}
	fresh_file_array_size = i-1;
	# Mysql
	txt_file = "/opt/sysadmws-utils/backup_check/by_mysql.txt";
	i = 1;
	if (system("test -e " txt_file) == 0) {
		while ((getline mysql_file_line < txt_file) > 0) {
			if (!match(mysql_file_line, /^#/)) {
				split(mysql_file_line, line_array, "	");
				mysql_file_array[i, 1] = line_array[1];
				mysql_file_array[i, 2] = line_array[2];
				mysql_file_array[i, 3] = line_array[3];
				mysql_file_array[i, 4] = line_array[4];
				mysql_file_array[i, 5] = line_array[5];
				mysql_file_array[i, 6] = line_array[6];
				i++;
			}
		}
		close (txt_file);
	}
	mysql_file_array_size = i-1;
	# Postgresql
	txt_file = "/opt/sysadmws-utils/backup_check/by_postgresql.txt";
	i = 1;
	if (system("test -e " txt_file) == 0) {
		while ((getline pg_file_line < txt_file) > 0) {
			if (!match(pg_file_line, /^#/)) {
				split(pg_file_line, line_array, "	");
				pg_file_array[i, 1] = line_array[1];
				pg_file_array[i, 2] = line_array[2];
				pg_file_array[i, 3] = line_array[3];
				pg_file_array[i, 4] = line_array[4];
				pg_file_array[i, 5] = line_array[5];
				pg_file_array[i, 6] = line_array[6];
				i++;
			}
		}
		close (txt_file);
	}
	pg_file_array_size = i-1;
	#
	ubuntu_backup_src_arr[1] = "/etc";
	ubuntu_backup_src_arr[2] = "/home";
	ubuntu_backup_src_arr[3] = "/root";
	ubuntu_backup_src_arr[4] = "/var/log";
	ubuntu_backup_src_arr[5] = "/var/spool/cron";
	ubuntu_backup_src_arr[6] = "/usr/local";
	ubuntu_backup_src_arr[7] = "/lib/ufw";
	ubuntu_backup_src_arr[8] = "/opt/sysadmws-utils";
	#
	debian_backup_src_arr[1] = "/etc";
	debian_backup_src_arr[2] = "/home";
	debian_backup_src_arr[3] = "/root";
	debian_backup_src_arr[4] = "/var/log";
	debian_backup_src_arr[5] = "/var/spool/cron";
	debian_backup_src_arr[6] = "/usr/local";
	debian_backup_src_arr[7] = "/lib/ufw";
	debian_backup_src_arr[8] = "/opt/sysadmws-utils";
	#
	centos_backup_src_arr[1] = "/etc";
	centos_backup_src_arr[2] = "/home";
	centos_backup_src_arr[3] = "/root";
	centos_backup_src_arr[4] = "/var/log";
	centos_backup_src_arr[5] = "/var/spool/cron";
	centos_backup_src_arr[6] = "/usr/local";
	debian_backup_src_arr[7] = "/opt/sysadmws-utils";
}

# Func to print timestamp at the beginning of line
function print_timestamp() {
	system("date '+%F %T ' | tr -d '\n'");
}

{
	# Skip commnets
	if ((substr($0, 1, 1) == "#") || (NF == "0")) {
		next;
	}

	# Assign variables
	host_name	= $1;
	backup_type	= $2;
	backup_src	= $3;
	backup_dst	= $4;
	dwm_number	= $5;
	run_args	= $6;
	connect_user	= $7;
	connect_passwd	= $8;
	
	# Assign previous params
	if (host_name == "---") {
		host_name = host_name_prev;
	}
	if (backup_type == "---") {
		backup_type = backup_type_prev;
	}
	if (backup_src == "---") {
		backup_src = backup_src_prev;
	}
	if (backup_dst == "---") {
		backup_dst = backup_dst_prev;
	}
	if (dwm_number == "---") {
		dwm_number = dwm_number_prev;
	}
	if (run_args == "---") {
		run_args = run_args_prev;
	}
	if (connect_user == "---") {
		connect_user = connect_user_prev;
	}
	if (connect_passwd == "---") {
		connect_passwd = connect_passwd_prev;
	}

	# Save params for the next line
	host_name_prev		= host_name;
	backup_type_prev	= backup_type;
	backup_src_prev		= backup_src;
	backup_dst_prev		= backup_dst;
	dwm_number_prev		= dwm_number;
	run_args_prev		= run_args;
	connect_user_prev	= connect_user;
	connect_passwd_prev	= connect_passwd;

	# Apply hostname_filter
	if (hostname_filter != "") {
		if (host_name != hostname_filter) {
			next;
		}
	}

	# Expand backup_src macroses
	delete backup_src_arr;
	delete backup_excludes;
	if (backup_src == "UBUNTU") {
		for (ii in ubuntu_backup_src_arr) {
			backup_src_arr[ii] = ubuntu_backup_src_arr[ii];
		}
	} else if (backup_src == "DEBIAN") {
		for (ii in debian_backup_src_arr) {
			backup_src_arr[ii] = debian_backup_src_arr[ii];
		}
	} else if (backup_src == "CENTOS") {
		for (ii in centos_backup_src_arr) {
			backup_src_arr[ii] = centos_backup_src_arr[ii];
		}
	} else if (match(backup_src, /UBUNTU\^/)) {
		split(substr(backup_src, 8), backup_excludes, ",");
		for (ii in ubuntu_backup_src_arr) {
			exclude_found = 0;
			for (backup_exclude in backup_excludes) {
				if (match(ubuntu_backup_src_arr[ii], backup_excludes[backup_exclude])) {
					exclude_found = 1;
				}
			}
			if (exclude_found != 1) {
				backup_src_arr[ii] = ubuntu_backup_src_arr[ii];
			}
		}
	} else if (match(backup_src, /DEBIAN\^/)) {
		split(substr(backup_src, 8), backup_excludes, ",");
		for (ii in debian_backup_src_arr) {
			exclude_found = 0;
			for (backup_exclude in backup_excludes) {
				if (match(debian_backup_src_arr[ii], backup_excludes[backup_exclude])) {
					exclude_found = 1;
				}
			}
			if (exclude_found != 1) {
				backup_src_arr[ii] = debian_backup_src_arr[ii];
			}
		}
	} else if (match(backup_src, /CENTOS\^/)) {
		split(substr(backup_src, 8), backup_excludes, ",");
		for (ii in centos_backup_src_arr) {
			exclude_found = 0;
			for (backup_exclude in backup_excludes) {
				if (match(centos_backup_src_arr[ii], backup_excludes[backup_exclude])) {
					exclude_found = 1;
				}
			}
			if (exclude_found != 1) {
				backup_src_arr[ii] = centos_backup_src_arr[ii];
			}
		}
	} else if (match(backup_src, /ALL\^/)) {
		backup_src = "ALL";
	} else {
		backup_src_arr[1] = backup_src;
	}

	# Try to find backup check
	if ((backup_type == "FS_RSYNC_SSH") || (backup_type == "FS_RSYNC_NATIVE") || (backup_type == "FS_RSYNC_NATIVE_TXT_CHECK") || (backup_type == "FS_RSYNC_NATIVE_TO_10H") || (backup_type == "FS_RSYNC_SSH_NOCHECK")) {
		# Loop expanded
		for (ii in backup_src_arr) {
			backup_src_found = 0;
			for (i = 1; i <= check_file_array_size; i++) {
				if ((check_file_array[i, 1] == host_name) || (check_file_array[i, 5] == host_name)) {
					if ((check_file_array[i, 2] == backup_src_arr[ii]) || (check_file_array[i, 6] == backup_src_arr[ii])) {
						if (index(check_file_array[i, 3], backup_dst) != 0) {
							if (show_notices == 1) {
								print_timestamp(); print("NOTICE: rsnapshot_backup found in by_check_file.txt: " host_name "	" backup_type "	" backup_src_arr[ii] "	" backup_dst " on line " FNR);
							}
							total_ok = total_ok + 1;
							backup_src_found = 1;
						}
					}
				}
			}
			for (i = 1; i <= fresh_file_array_size; i++) {
				if ((fresh_file_array[i, 1] == host_name) || (fresh_file_array[i, 10] == host_name)) {
					if ((fresh_file_array[i, 2] == backup_src_arr[ii]) || (fresh_file_array[i, 11] == backup_src_arr[ii])) {
						if (index(fresh_file_array[i, 3], backup_dst) != 0) {
							if (show_notices == 1) {
								print_timestamp(); print("NOTICE: rsnapshot_backup found in by_fresh_files.txt: " host_name "	" backup_type "	" backup_src_arr[ii] "	" backup_dst " on line " FNR);
							}
							total_ok = total_ok + 1;
							backup_src_found = 1;
						}
					}
				}
			}
			if (backup_src_found == 0) {
				print_timestamp(); print("ERROR: Unchecked rsnapshot_backup found: " host_name "	" backup_type "	" backup_src_arr[ii] "	" backup_dst " on line " FNR);
				total_errors = total_errors + 1;
			}
		}
		next;
	}
	if (backup_type == "LOCAL_PREEXEC") {
		for (i = 1; i <= check_file_array_size; i++) {
			if (check_file_array[i, 1] == checked_host_name) {
				if ((check_file_array[i, 2] == backup_src) || (check_file_array[i, 6] == backup_src)) {
					if (index(check_file_array[i, 3], backup_dst) != 0) {
						if (show_notices == 1) {
							print_timestamp(); print("NOTICE: rsnapshot_backup found in by_check_file.txt: " host_name "	" backup_type "	" backup_src "	" backup_dst " on line " FNR);
						}
						total_ok = total_ok + 1;
						next;
					}
				}
			}
		}
		for (i = 1; i <= fresh_file_array_size; i++) {
			if (fresh_file_array[i, 1] == checked_host_name) {
				if (fresh_file_array[i, 2] == backup_src) {
					if (index(fresh_file_array[i, 3], backup_dst) != 0) {
						if (show_notices == 1) {
							print_timestamp(); print("NOTICE: rsnapshot_backup found in by_fresh_files.txt: " host_name "	" backup_type "	" backup_src "	" backup_dst " on line " FNR);
						}
						total_ok = total_ok + 1;
						next;
					}
				}
			}
		}
	}
	if ((backup_type == "MYSQL") || (backup_type == "MYSQL_NOEVENTS") || (backup_type == "MYSQL_NOEVENTS_NOCHECK") || (backup_type == "MYSQL_NOCHECK")) {
		for (i = 1; i <= mysql_file_array_size; i++) {
			if ((mysql_file_array[i, 1] == host_name) || (mysql_file_array[i, 5] == host_name)) {
				if ((mysql_file_array[i, 2] == backup_src) || ((mysql_file_array[i, 2] == "MYSQL_ALL") && (backup_src == "ALL"))) {
					if (index(mysql_file_array[i, 4], backup_dst) != 0) {
						if (show_notices == 1) {
							print_timestamp(); print("NOTICE: rsnapshot_backup found in by_mysql.txt: " host_name "	" backup_type "	" backup_src "	" backup_dst " on line " FNR);
						}
						total_ok = total_ok + 1;
						next;
					}
				}
			}
		}
	}
	if ((backup_type == "POSTGRESQL") || (backup_type == "POSTGRESQL_NOCLEAN") || (backup_type == "POSTGRESQL_NOCLEAN_NOCHECK") || (backup_type == "POSTGRESQL_NOCHECK")) {
		for (i = 1; i <= pg_file_array_size; i++) {
			if ((pg_file_array[i, 1] == host_name) || (pg_file_array[i, 5] == host_name)) {
				if ((pg_file_array[i, 2] == backup_src) || ((pg_file_array[i, 2] == "POSTGRESQL_ALL") && (backup_src == "ALL"))) {
					if (index(pg_file_array[i, 4], backup_dst) != 0) {
						if (show_notices == 1) {
							print_timestamp(); print("NOTICE: rsnapshot_backup found in by_postgresql.txt: " host_name "	" backup_type "	" backup_src "	" backup_dst " on line " FNR);
						}
						total_ok = total_ok + 1;
						next;
					}
				}
			}
		}
	}
	# In all other cases
	print_timestamp(); print("ERROR: Unchecked rsnapshot_backup found: " host_name "	" backup_type "	" backup_src "	" backup_dst " on line " FNR);
	total_errors = total_errors + 1;
}
END {
	# Summ results
        my_folder = "/opt/sysadmws-utils/backup_check";
        system("awk '{ print $1 + " total_errors "}' < " my_folder "/errors_count.txt > " my_folder "/errors_count.txt.new && mv -f " my_folder "/errors_count.txt.new " my_folder "/errors_count.txt");
        system("awk '{ print $1 + " total_ok "}' < " my_folder "/ok_count.txt > " my_folder "/ok_count.txt.new && mv -f " my_folder "/ok_count.txt.new " my_folder "/ok_count.txt");
	# Total errors
	if (total_errors == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " rsnapshot_backup and backup_check configs compared OK: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " rsnapshot_backup config contains backups being not checked: " total_errors);
		exit(1);
	}
}
