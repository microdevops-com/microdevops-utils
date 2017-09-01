BEGIN {
	total_lines	= 0;
	total_errors	= 0;
	total_ok        = 0;
	backup_check_skip_fresh_files_warning	= 0;
	# Get my hostname
	hn_cmd = "salt-call --local grains.item fqdn 2>&1 | tail -n 1 | sed 's/^ *//'";
	hn_cmd | getline checked_host_name;
	close(hn_cmd);
}

# Func to print timestamp at the beginning of line
function print_timestamp() {
	system("date '+%F %T ' | tr -d '\n'");
}

{
	# Find backup check skip warning
	if (match($0, /^# backup_check_skip_fresh_files_warning: True$/)) {
		backup_check_skip_fresh_files_warning = 1;
		next;
	}
	
	# Skip commnets
	if ((substr($0, 1, 1) == "#") || (NF == "0")) {
		next;
	}

	# Count total non comment lines
	total_lines++;

	# Assign variables
	host_name			= $1;
	host_path			= $2;
	backup_dst			= $3;
	backup_dst_type			= $4;
	backup_min_file_size		= $5;
	backup_file_type		= $6;
	backup_last_file_freshness	= $7;
	backup_files_total		= $8;
	backup_files_mask		= $9;

	# Apply hostname_filter
	if (hostname_filter != "") {
		if (host_name != hostname_filter) {
			next;
		}
	}

	# Construct path
	if (backup_dst_type == "Absolute") {
		backup_dst_full = backup_dst;
	} else if (backup_dst_type == "Relative") {
		backup_dst_full = backup_dst "/" host_path;
	}
	# Construct find cmd
	find_cmd = "find " backup_dst_full " -type f -regex '.*/" backup_files_mask "'";
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
		print_timestamp(); print("ERROR: Found only " i " files instead of " backup_files_total ", path: '" backup_dst_full "' on line " FNR);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Files qty OK: " i ", path: '" backup_dst_full "' on line " FNR);
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
			print_timestamp(); print("ERROR: File size: " size_file " < " backup_min_file_size " minimal size, file: '" find_files[cur_file] "' on line " FNR);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: File size OK: " size_file " >= " backup_min_file_size " minimal size, file: '" find_files[cur_file] "' on line " FNR);
			}
			total_ok = total_ok + 1;
		}
		# Type
		file_file_cmd = "file -b '" find_files[cur_file] "'";
		file_file_cmd | getline file_file;
		close(file_file_cmd);
		if (!match(file_file, backup_file_type)) {
			print_timestamp(); print("ERROR: File type mismatch: '" file_file "' != '" backup_file_type "', file: '" find_files[cur_file] "' on line " FNR);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: File type OK: '" file_file "' == '" backup_file_type "', file: '" find_files[cur_file] "' on line " FNR);
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
		if ((secs_now - max_secs) > (backup_last_file_freshness * 86400)) {
			print_timestamp(); print("ERROR: Freshest file is older than " backup_last_file_freshness " day(s): '" secs_readable "', file: '" max_secs_file "' on line " FNR);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: Freshest file age (" backup_last_file_freshness " day(s)) OK: '" secs_readable "', file: '" max_secs_file "' on line " FNR);
			}
			total_ok = total_ok + 1;
		}
	} else {
		print_timestamp(); print("ERROR: Freshest file not found on line " FNR);
		total_errors = total_errors + 1;
	}
}
END {
	# Total lines check
	if ((total_lines == 0) && (backup_check_skip_fresh_files_warning == 0))  {
		print_timestamp(); print("WARNING: Backup server " checked_host_name " fresh files backup check txt config empty");
	}
	if ((total_lines > 0) && (backup_check_skip_fresh_files_warning == 1))  {
		print_timestamp(); print("WARNING: Backup server " checked_host_name " fresh files backup check txt config not empty but you have backup_check_skip_fresh_files_warning: True set");
	}
        # Summ results
        my_folder = "/opt/sysadmws-utils/backup_check";
        system("awk '{ print $1 + " total_errors "}' < " my_folder "/errors_count.txt > " my_folder "/errors_count.txt.new && mv -f " my_folder "/errors_count.txt.new " my_folder "/errors_count.txt");
        system("awk '{ print $1 + " total_ok "}' < " my_folder "/ok_count.txt > " my_folder "/ok_count.txt.new && mv -f " my_folder "/ok_count.txt.new " my_folder "/ok_count.txt");
	# Total errors
	if (total_errors == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " fresh files backups checked OK: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " fresh files backup errors found: " total_errors);
		exit(1);
	}
}
