BEGIN {
	total_errors	= 0;
	total_ok        = 0;
	# Get my hostname
	hn_cmd = "hostname -f";
	hn_cmd | getline checked_host_name;
	close(hn_cmd);
}

# Func to print timestamp at the beginning of line
function print_timestamp() {
	system("date '+%F %T ' | tr -d '\n'");
}

{
	# Assign variables

	# Check if enabled
	if (row_enabled != "true") {
		next;
	}

	# Assign variables
	host_name			= row_host;
	host_path			= row_source;
	backup_dst			= row_path;
	backup_type			= row_type;
	backup_min_file_size		= check_min_file_size;
	backup_file_type		= check_file_type;
	backup_last_file_age		= check_last_file_age;
	backup_files_total		= check_files_total;
	backup_files_mask		= check_files_mask;
	
	# Expand macro values
	delete host_path_arr;
	if (host_path == "UBUNTU") {
		host_path_arr[1] = "/etc";
		host_path_arr[2] = "/home";
		host_path_arr[3] = "/root";
		host_path_arr[4] = "/var/spool/cron";
		host_path_arr[5] = "/var/lib/dpkg";
		host_path_arr[6] = "/usr/local";
		host_path_arr[7] = "/opt/sysadmws";
	} else if (host_path == "DEBIAN") {
		host_path_arr[1] = "/etc";
		host_path_arr[2] = "/home";
		host_path_arr[3] = "/root";
		host_path_arr[4] = "/var/spool/cron";
		host_path_arr[5] = "/var/lib/dpkg";
		host_path_arr[6] = "/usr/local";
		host_path_arr[7] = "/opt/sysadmws";
	} else if (host_path == "CENTOS") {
		host_path_arr[1] = "/etc";
		host_path_arr[2] = "/home";
		host_path_arr[3] = "/root";
		host_path_arr[4] = "/var/spool/cron";
		host_path_arr[5] = "/var/lib/rpm";
		host_path_arr[6] = "/usr/local";
		host_path_arr[7] = "/opt/sysadmws";
	} else {
		host_path_arr[1] = host_path;
	}
	for (jj in host_path_arr) {
		host_path = host_path_arr[jj];

		# Construct path
		if (backup_type == "RSYNC_NATIVE") {
                        strip_first_dir_cmd = "echo '" host_path "' | cut -d'/' -f3-";
                        strip_first_dir_cmd | getline stripped_host_path;
                        close(strip_first_dir_cmd);
			backup_dst_full = backup_dst "/.sync/rsnapshot/" stripped_host_path;
		} else if (backup_type == "RSYNC_SSH") {
			backup_dst_full = backup_dst "/.sync/rsnapshot" host_path;
		}
		# Construct find cmd
		find_cmd = "find " backup_dst_full " -type f -regex '.*/" backup_files_mask "'";
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: find cmd: " find_cmd);
		}

		# Read files from find
		delete find_files;
		i = 0;
		while ((find_cmd | getline find_line) > 0) {
			i++;
			find_files[i] = find_line;
		}
		close (find_cmd);

		# Check files count
		if (i < backup_files_total) {
			print_timestamp(); print("ERROR: Found only " i " files instead of " backup_files_total ", path: '" backup_dst_full "' on config item " row_number);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: Files qty OK: " i ", path: '" backup_dst_full "' on config item " row_number);
			}
			total_ok = total_ok + 1;
		}

		# Get files max mtime, size and types
		max_secs = 0;
		max_secs_file = "";
		for (cur_file in find_files) {
			# Max mtime
			secs_file_cmd = "stat -c %Y '" find_files[cur_file] "'";
			secs_file_cmd | getline secs_file;
			close(secs_file_cmd);
			if (secs_file > max_secs) {
				max_secs = secs_file;
				max_secs_file = find_files[cur_file];
				
			}
			# Size
			size_file_cmd = "stat -c %s '" find_files[cur_file] "'";
			size_file_cmd | getline size_file;
			close(size_file_cmd);
			if (size_file < backup_min_file_size) {
				print_timestamp(); print("ERROR: File size: " size_file " < " backup_min_file_size " minimal size, file: '" find_files[cur_file] "' on config item " row_number);
				total_errors = total_errors + 1;
			} else {
				if (show_notices == 1) {
					print_timestamp(); print("NOTICE: File size OK: " size_file " >= " backup_min_file_size " minimal size, file: '" find_files[cur_file] "' on config item " row_number);
				}
				total_ok = total_ok + 1;
			}
			# Type
			file_file_cmd = "file -b '" find_files[cur_file] "'";
			file_file_cmd | getline file_file;
			close(file_file_cmd);
			if (!match(file_file, backup_file_type)) {
				print_timestamp(); print("ERROR: File type mismatch: '" file_file "' != '" backup_file_type "', file: '" find_files[cur_file] "' on config item " row_number);
				total_errors = total_errors + 1;
			} else {
				if (show_notices == 1) {
					print_timestamp(); print("NOTICE: File type OK: '" file_file "' == '" backup_file_type "', file: '" find_files[cur_file] "' on config item " row_number);
				}
				total_ok = total_ok + 1;
			}
		}
		# Calculate diff between dates
		secs_now_cmd = "date '+%s'";
		secs_now_cmd | getline secs_now;
		close(secs_now_cmd);
		if (max_secs_file != "") {
			secs_readable_cmd = "stat -c %y '" max_secs_file "'";
			secs_readable_cmd | getline secs_readable;
			close(secs_readable_cmd);
			if ((secs_now - max_secs) > (backup_last_file_age * 86400)) {
				print_timestamp(); print("ERROR: Last file is older than " backup_last_file_age " day(s): '" secs_readable "', file: '" max_secs_file "' on config item " row_number);
				total_errors = total_errors + 1;
			} else {
				if (show_notices == 1) {
					print_timestamp(); print("NOTICE: Last file age (" backup_last_file_age " day(s)) OK: '" secs_readable "', file: '" max_secs_file "' on config item " row_number);
				}
				total_ok = total_ok + 1;
			}
		} else {
			print_timestamp(); print("ERROR: Last file not found on config item " row_number);
			total_errors = total_errors + 1;
		}
	}
}
END {
        # Summ results
        my_folder = "/opt/sysadmws/rsnapshot_backup";
        system("awk '{ print $1 + " total_errors "}' < " my_folder "/check_backup_error_count.txt > " my_folder "/check_backup_error_count.txt.new && mv -f " my_folder "/check_backup_error_count.txt.new " my_folder "/check_backup_error_count.txt");
        system("awk '{ print $1 + " total_ok "}' < " my_folder "/check_backup_ok_count.txt > " my_folder "/check_backup_ok_count.txt.new && mv -f " my_folder "/check_backup_ok_count.txt.new " my_folder "/check_backup_ok_count.txt");
	# Total errors
	if (total_errors == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " backups file age OK checks: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " backup file age errors found: " total_errors);
		exit(1);
	}
}
