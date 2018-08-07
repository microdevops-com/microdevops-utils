BEGIN {
	total_lines	= 0;
	total_errors	= 0;
	total_ok        = 0;
	check_backup_skip_mysql_warning	= 0;
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
        if (match($0, /^# check_backup_skip_mysql_warning: True$/)) {
                check_backup_skip_mysql_warning = 1;
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
	db_name		= $2;
	db_sub_name	= $3;
	dump_file	= $4;

	# Apply hostname_filter
	if (hostname_filter != "") {
		if (host_name != hostname_filter) {
			next;
		}
	}

	# Check dump dir or file existance
	if (system("test -d " dump_file) == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump dir found: '" dump_file "' on line " FNR);
		}
		if (system("test -f " dump_file "/" db_sub_name) == 0) {
			dump_file = dump_file "/" db_sub_name;
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: Dump file inside dir found: '" dump_file "' on line " FNR);
			}
		} else if (system("test -f " dump_file "/" db_sub_name ".gz") == 0) {
			dump_file = dump_file "/" db_sub_name ".gz";
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: Dump file inside dir found: '" dump_file "' on line " FNR);
			}
		} else {
			print_timestamp(); print("ERROR: Dump file inside dir missing: '" dump_file "/" db_sub_name "[.gz]' on line " FNR);
			total_errors = total_errors + 1;
			next;
		}
	} else if (system("test -f " dump_file) == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump file found: '" dump_file "' on line " FNR);
		}
	} else {
		print_timestamp(); print("ERROR: Dump file missing: '" dump_file "' on line " FNR);
		total_errors = total_errors + 1;
		next;
	}

        # Print some stats
	if (show_notices >= 1) {
		print_timestamp();
		printf("NOTICE: Dump file stats: " host_name "/" db_sub_name " ");
		system("ls -h -s " gensub("/.sync/", "/daily.1/", "g", dump_file) " | awk '{print $1}' | tr -d '\n'");
		printf(" -> ");
		system("ls -h -s " dump_file " | awk '{print $1}'");
	}

	# Analyze dump file
	if (!dump_file_analyze[dump_file, "analyzed"]) {
		if ((dump_file != "") && (system("test -e " dump_file) == 0)) {
			# Construct command for the part of the dump
			if (match(dump_file, /.*\.gz$/)) {
				dump_cat_cmd = "zcat " dump_file;
			} else {
				dump_cat_cmd = "cat " dump_file;
			}
			# Read lines of dump file
			while ((dump_cat_cmd | getline dump_file_line) > 0) {
				if (match(dump_file_line, /^CREATE DATABASE/)) {
					# Save DB name and its lines = 0
					if (match(dump_file_line, /`(.+)`/, dump_file_line_sub)) {
						dump_file_analyze[dump_file, "databases"][dump_file_line_sub[1]] = 0;
					}
				}
				# Inc lines count for DB
				if (match(dump_file_line, /^INSERT INTO/)) {
					dump_file_analyze[dump_file, "databases"][dump_file_line_sub[1]]++;
				}
				# Save dump date
				if (match(dump_file_line, /^-- Dump completed on (.+)$/, dump_file_date)) {
					dump_file_analyze[dump_file, "date"] = dump_file_date[1];
				}
			}
			close(dump_cat_cmd);
			# Set as analyzed
			dump_file_analyze[dump_file, "analyzed"] = 1; 
		}
	}

	# Calculate diff between dates
	secs_now_cmd = "date '+%s'";
	secs_now_cmd | getline secs_now;
	close(secs_now_cmd);
	if (dump_file_analyze[dump_file, "date"] != "") {
		secs_dfa_date_cmd = "date -d '" dump_file_analyze[dump_file, "date"] "' '+%s'";
		secs_dfa_date_cmd | getline secs_dfa_date;
		close(secs_dfa_date_cmd);
	} else {
		secs_dfa_date = 0;
	}

	# Check DB in dump
	if (dump_file_analyze[dump_file, "databases"][db_sub_name] < 1) {
		print_timestamp(); print("ERROR: Dump file contains < 1 INSERTS for DB: " host_name "/" db_sub_name ", file: '" dump_file "' on line " FNR);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump contains " dump_file_analyze[dump_file, "databases"][db_sub_name] " INSERTS for DB: " host_name "/" db_sub_name ", file: '" dump_file "' on line " FNR);
		}
		total_ok = total_ok + 1;
	}
	# Check dump date
	if ((secs_now - secs_dfa_date) > 86400) {
		print_timestamp(); print("ERROR: Dump file date older than one day: '" dump_file_analyze[dump_file, "date"] "', file: '" dump_file "' on line " FNR);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump file date OK: '" dump_file_analyze[dump_file, "date"] "', file: '" dump_file "' on line " FNR);
		}
		total_ok = total_ok + 1;
	}
}
END {
        # Total lines check
        if ((total_lines == 0) && (check_backup_skip_mysql_warning == 0))  {
                print_timestamp(); print("WARNING: Backup server " checked_host_name " mysql backup check txt config empty");
        }
        if ((total_lines > 0) && (check_backup_skip_mysql_warning == 1))  {
                print_timestamp(); print("WARNING: Backup server " checked_host_name " mysql backup check txt config not empty but you have check_backup_skip_mysql_warning: True set");
        }
	# Summ results
        my_folder = "/opt/sysadmws/rsnapshot_backup";
        system("awk '{ print $1 + " total_errors "}' < " my_folder "/check_backup_error_count.txt > " my_folder "/check_backup_error_count.txt.new && mv -f " my_folder "/check_backup_error_count.txt.new " my_folder "/check_backup_error_count.txt");
        system("awk '{ print $1 + " total_ok "}' < " my_folder "/check_backup_ok_count.txt > " my_folder "/check_backup_ok_count.txt.new && mv -f " my_folder "/check_backup_ok_count.txt.new " my_folder "/check_backup_ok_count.txt");
	# Total errors
	if (total_errors == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " mysql backups checked OK: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " mysql backup errors found: " total_errors);
		exit(1);
	}
}
