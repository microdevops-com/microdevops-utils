BEGIN {
	total_lines	= 0;
	total_errors	= 0;
	total_ok	= 0;
	backup_check_skip_check_file_warning	= 0;
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
        if (match($0, /^# backup_check_skip_check_file_warning: True$/)) {
                backup_check_skip_check_file_warning = 1;
                next;
        }

	# Skip commnets
	if ((substr($0, 1, 1) == "#") || (NF == "0")) {
		next;
	}

	# Count total non comment lines
	total_lines++;

	# Assign variables
	host_name	= $1;
	host_path	= $2;
	backup_dst	= $3;
	backup_dst_type	= $4;
	host_name_alias	= $7;

	# Apply hostname_filter
	if (hostname_filter != "") {
		if (host_name != hostname_filter) {
			next;
		}
	}

	# Expand macro values
	delete host_path_arr;
	if (host_path == "UBUNTU") {
		host_path_arr[1] = "/etc";
		host_path_arr[2] = "/home";
		host_path_arr[3] = "/root";
		host_path_arr[4] = "/var/log";
		host_path_arr[5] = "/var/spool/cron";
		host_path_arr[6] = "/usr/local";
		host_path_arr[7] = "/lib/ufw";
		host_path_arr[8] = "/opt/sysadmws-utils";
	} else if (host_path == "DEBIAN") {
		host_path_arr[1] = "/etc";
		host_path_arr[2] = "/home";
		host_path_arr[3] = "/root";
		host_path_arr[4] = "/var/log";
		host_path_arr[5] = "/var/spool/cron";
		host_path_arr[6] = "/usr/local";
		host_path_arr[7] = "/lib/ufw";
		host_path_arr[8] = "/opt/sysadmws-utils";
	} else if (host_path == "CENTOS") {
		host_path_arr[1] = "/etc";
		host_path_arr[2] = "/home";
		host_path_arr[3] = "/root";
		host_path_arr[4] = "/var/log";
		host_path_arr[5] = "/var/spool/cron";
		host_path_arr[6] = "/usr/local";
		host_path_arr[7] = "/opt/sysadmws-utils";
	} else {
		host_path_arr[1] = host_path;
	}
	for (jj in host_path_arr) {
		host_path = host_path_arr[jj];
		# Clear variables
		chf_host = ""; chf_path = ""; chf_date = "1970-01-01 00:00:00"; chf_backup_host = ""; chf_backup_path = ""; chf_backup_path_type = "";
		# Construct path
		if (backup_dst_type == "Absolute") {
			check_file = backup_dst "/.backup_check";
			check_dir = backup_dst;
		} else if (backup_dst_type == "Relative") {
			check_file = backup_dst "/" host_path "/.backup_check";
			check_dir = backup_dst "/" host_path;
		}

		# Print some stats
		if (show_notices >= 1) {
			print_timestamp();
			printf("NOTICE: Dir stats: " host_name host_path " ");
			system("du -sh " gensub("/.sync/", "/daily.1/", "g", check_dir) " | awk '{print $1}' | tr -d '\n'");
			printf("/");
			system("find " gensub("/.sync/", "/daily.1/", "g", check_dir) " -type f | wc -l | tr -d '\n'");
			printf(" -> ");
			system("du -sh " check_dir " | awk '{print $1}' | tr -d '\n'");
			printf("/");
			system("find " check_dir " -type f | wc -l");
		}

		# Check check file existance
		if (system("test ! -e " check_file) == 0) {
			print_timestamp(); print("ERROR: Check file missing: '" check_file "' on line " FNR);
			total_errors = total_errors + 1;
			continue;
		}
		# Read variables from check file
		delete line_array;
		backup_hosts_num = 0;
		if ((check_file != "") && (system("test -e " check_file) == 0)) {
			while ((getline check_file_line < check_file) > 0) {
				split(check_file_line, line_array, ": ");
				sub(/\r/, "", line_array[2]);
				if (line_array[1] == "Host") chf_host = line_array[2]
				else if (line_array[1] == "Path") chf_path = line_array[2]
				else if (line_array[1] == "Date") chf_date = line_array[2]
				else if (line_array[1] == "Backup Host") chf_backup_host = line_array[2]
				else if (line_array[1] == "Backup Path") chf_backup_path = line_array[2]
				else if (line_array[1] == "Backup Path Type") chf_backup_path_type = line_array[2]
				else if (match(line_array[1], /Backup .+ Host/)) {
					backup_hosts_num = backup_hosts_num + 1;
					backup_number = (gensub(/Backup (.+) Host/, "\\1", "g", line_array[1]));
					chf_backup_arr[backup_number]["host"] = line_array[2];
				} else if (match(line_array[1], /Backup .+ Path Type/)) {
					backup_number = (gensub(/Backup (.+) Path Type/, "\\1", "g", line_array[1]));
					chf_backup_arr[backup_number]["path_type"] = line_array[2];
				} else if (match(line_array[1], /Backup .+ Path/)) {
					backup_number = (gensub(/Backup (.+) Path/, "\\1", "g", line_array[1]));
					chf_backup_arr[backup_number]["path"] = line_array[2];
				}
			}
			close(check_file);
		}
		
		# Lowercase hostname and alias
		host_name	= tolower(host_name);
		host_name_alias = tolower(host_name_alias);
		chf_host	= tolower(chf_host);

		# Check variables to be correct
		if ((host_name != chf_host) && (host_name_alias != chf_host)) {
			print_timestamp(); print("ERROR: Check file host mismatch: '" host_name "' != '" chf_host "', nor its alias '" host_name_alias "' != '" chf_host "', file: '" check_file "' on line " FNR);
			total_errors = total_errors + 1;
			continue;
		}
		if (host_path != chf_path) {
			print_timestamp(); print("ERROR: Check file path mismatch: '" host_path "' != '" chf_path "', file: '" check_file "' on line " FNR);
			total_errors = total_errors + 1;
			continue;
		}
		# Calculate diff between dates
		secs_now_cmd = "date '+%s'";
		secs_now_cmd | getline secs_now;
		close(secs_now_cmd);
		secs_chf_date_cmd = "date -d '" chf_date "' '+%s'";
		secs_chf_date_cmd | getline secs_chf_date;
		close(secs_chf_date_cmd);
		if ((secs_now - secs_chf_date) > 86400) {
			print_timestamp(); print("ERROR: Check file date older than one day: '" chf_date "', file: '" check_file "' on line " FNR);
			total_errors = total_errors + 1;
			continue;
		}
		if (backup_hosts_num > 0) {
			backup_host_found = 0;
			for (backup_num = 1; backup_num <= backup_hosts_num; backup_num++) {
				if ((checked_host_name == chf_backup_arr[backup_num]["host"]) && (backup_dst == chf_backup_arr[backup_num]["path"]) && (backup_dst_type == chf_backup_arr[backup_num]["path_type"])) {
					backup_host_found = 1;
				}
			}
			if (backup_host_found == 0) {
				print_timestamp(); print("ERROR: Check file backup host not found: '" checked_host_name " + "backup_dst" + "backup_dst_type"', file: '" check_file "' on line " FNR);
				total_errors = total_errors + 1;
				continue;
			}
		} else {
			if (checked_host_name != chf_backup_host) {
				print_timestamp(); print("ERROR: Check file backup host mismatch: '" checked_host_name "' != '" chf_backup_host "', file: '" check_file "' on line " FNR);
				total_errors = total_errors + 1;
				continue;
			}
			if (backup_dst != chf_backup_path) {
				print_timestamp(); print("ERROR: Check file backup path mismatch: '" backup_dst "' != '" chf_backup_path "', file: '" check_file "' on line " FNR);
				total_errors = total_errors + 1;
				continue;
			}
			if (backup_dst_type != chf_backup_path_type) {
				print_timestamp(); print("ERROR: Check file backup path type mismatch: '" backup_dst_type "' != '" chf_backup_path_type "', file: '" check_file "' on line " FNR);
				total_errors = total_errors + 1;
				continue;
			}
		}
		# So if it is ok
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Check file OK: '" check_file "' on line " FNR);
		}
		total_ok = total_ok + 1;
	}
}
END {
        # Total lines check
        if ((total_lines == 0) && (backup_check_skip_check_file_warning == 0))  {
                print_timestamp(); print("WARNING: Backup server " checked_host_name " check file backup check txt config empty");
        }
        if ((total_lines > 0) && (backup_check_skip_check_file_warning == 1))  {
                print_timestamp(); print("WARNING: Backup server " checked_host_name " check file backup check txt config not empty but you have backup_check_skip_check_file_warning: True set");
        }
	# Summ results
	my_folder = "/opt/sysadmws-utils/backup_check";
	system("awk '{ print $1 + " total_errors "}' < " my_folder "/errors_count.txt > " my_folder "/errors_count.txt.new && mv -f " my_folder "/errors_count.txt.new " my_folder "/errors_count.txt");
	system("awk '{ print $1 + " total_ok "}' < " my_folder "/ok_count.txt > " my_folder "/ok_count.txt.new && mv -f " my_folder "/ok_count.txt.new " my_folder "/ok_count.txt");
	# Total errors
	if (total_errors == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " check file backups checked OK: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " check file backup errors found: " total_errors);
		exit(1);
	}
}
