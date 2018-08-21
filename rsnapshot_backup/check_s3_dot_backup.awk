BEGIN {
	total_errors	= 0;
	total_ok	= 0;
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
	# Check if enabled
	if (row_enabled != "true") {
		next;
	}

	# Assign variables
	host_name	= row_host;
	host_path	= row_source;
	backup_dst	= row_path;
	backup_type	= row_type;
	s3_bucket	= check_s3_bucket;
	s3_path		= check_s3_path;

	# Clear variables
	chf_bucket = ""; chf_path = ""; chf_date = ""; chf_backup_host = ""; chf_backup_path = "";
	# Construct path
	check_file = backup_dst "/.sync/rsnapshot" host_path "/.backup";
	check_dir = backup_dst "/.sync/rsnapshot" host_path;

	# Print some stats
	if (show_notices >= 1) {
		print_timestamp();
		printf("NOTICE: Dir stats: " host_name host_path " ");
		daily_check_dir = gensub("/.sync/", "/daily.1/", "g", check_dir);
		system("( [ -d " daily_check_dir " ] && du -sh " daily_check_dir " || echo 0 ) | awk '{print $1}' | tr -d '\n'");
		printf("/");
		system("[ -d " daily_check_dir " ] && ( find " daily_check_dir " -type f | wc -l | tr -d '\n' ) || ( echo 0 | tr -d '\n' )");
		printf(" -> ");
		system("( [ -d " check_dir " ] && du -sh " check_dir " || echo 0 ) | awk '{print $1}' | tr -d '\n'");
		printf("/");
		system("[ -d " check_dir " ] && ( find " check_dir " -type f | wc -l ) || ( echo 0 )");
	}

	# Check check file existance
	if (system("test ! -e " check_file) == 0) {
		print_timestamp(); print("ERROR: s3/.backup file missing: '" check_file "' on line " row_number);
		total_errors = total_errors + 1;
		next;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: s3/.backup file exists: '" check_file "' on line " row_number);
		}
		total_ok = total_ok + 1;
	}
	# Read variables from check file
	delete line_array;
	backup_hosts_num = 0;
	if ((check_file != "") && (system("test -e " check_file) == 0)) {
		while ((getline check_file_line < check_file) > 0) {
			split(check_file_line, line_array, ": ");
			sub(/\r/, "", line_array[2]);
			if (line_array[1] == "Bucket") chf_bucket = line_array[2]
			else if (line_array[1] == "Path") chf_path = line_array[2]
			else if (line_array[1] == "UTC") chf_date = line_array[2]
			else if (line_array[1] == "Backup Host") chf_backup_host = line_array[2]
			else if (line_array[1] == "Backup Path") chf_backup_path = line_array[2]
			else if (match(line_array[1], /Backup .+ Host/)) {
				backup_hosts_num = backup_hosts_num + 1;
				backup_number = (gensub(/Backup (.+) Host/, "\\1", "g", line_array[1]));
				chf_backup_arr[backup_number]["host"] = line_array[2];
			} else if (match(line_array[1], /Backup .+ Path/)) {
				backup_number = (gensub(/Backup (.+) Path/, "\\1", "g", line_array[1]));
				chf_backup_arr[backup_number]["path"] = line_array[2];
			}
		}
		close(check_file);
	}
	
	# Check variables to be correct
	if (s3_bucket != chf_bucket) {
		print_timestamp(); print("ERROR: s3/.backup file S3 bucket mismatch: '" s3_bucket "' != '" chf_bucket "', file: '" check_file "' on line " row_number);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: s3/.backup file S3 bucket match: '" s3_bucket "' == '" chf_bucket "', file: '" check_file "' on line " row_number);
		}
		total_ok = total_ok + 1;
	}
	if (s3_path != chf_path) {
		print_timestamp(); print("ERROR: s3/.backup file S3 path mismatch: '" s3_path "' != '" chf_path "', file: '" check_file "' on line " row_number);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: s3/.backup file S3 path match: '" s3_path "' == '" chf_path "', file: '" check_file "' on line " row_number);
		}
		total_ok = total_ok + 1;
	}
	# Calculate diff between dates
	secs_now_cmd = "date '+%s'";
	secs_now_cmd | getline secs_now;
	close(secs_now_cmd);
	secs_chf_date_cmd = "date -u -d '" chf_date "' '+%s'";
	secs_chf_date_cmd | getline secs_chf_date;
	close(secs_chf_date_cmd);
	if ((secs_now - secs_chf_date) > 86400) {
		print_timestamp(); print("ERROR: s3/.backup file date older than one day: '" chf_date "', file: '" check_file "' on line " row_number);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: s3/.backup file date OK: '" chf_date "', file: '" check_file "' on line " row_number);
		}
		total_ok = total_ok + 1;
	}
	if (backup_hosts_num > 0) {
		backup_host_found = 0;
		for (backup_num = 1; backup_num <= backup_hosts_num; backup_num++) {
			if ((checked_host_name == chf_backup_arr[backup_num]["host"]) && (backup_dst == chf_backup_arr[backup_num]["path"])) {
				backup_host_found = 1;
			}
		}
		if (backup_host_found == 0) {
			print_timestamp(); print("ERROR: s3/.backup file backup host not found: '" checked_host_name " + "backup_dst"', file: '" check_file "' on line " row_number);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: s3/.backup file backup host found: '" checked_host_name " + "backup_dst"', file: '" check_file "' on line " row_number);
			}
			total_ok = total_ok + 1;
		}
	} else {
		if (checked_host_name != chf_backup_host) {
			print_timestamp(); print("ERROR: s3/.backup file backup host mismatch: '" checked_host_name "' != '" chf_backup_host "', file: '" check_file "' on line " row_number);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: s3/.backup file backup host match: '" checked_host_name "' == '" chf_backup_host "', file: '" check_file "' on line " row_number);
			}
			total_ok = total_ok + 1;
		}
		if (backup_dst != chf_backup_path) {
			print_timestamp(); print("ERROR: s3/.backup file backup path mismatch: '" backup_dst "' != '" chf_backup_path "', file: '" check_file "' on line " row_number);
			total_errors = total_errors + 1;
		} else {
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: s3/.backup file backup path match: '" backup_dst "' == '" chf_backup_path "', file: '" check_file "' on line " row_number);
			}
			total_ok = total_ok + 1;
		}
	}
	# So if it is ok
	if (show_notices == 1) {
		print_timestamp(); print("NOTICE: s3/.backup file check done: '" check_file "' on line " row_number);
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
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " check file backups OK checks: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " check file backup errors found: " total_errors);
		exit(1);
	}
}
