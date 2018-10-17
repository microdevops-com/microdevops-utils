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
	# Check if enabled
	if (row_enabled != "true") {
		next;
	}

	# Assign variables
	host_name	= row_host;
	db_name		= row_source;
	dump_dir	= row_path "/.sync/rsnapshot/var/backups/mysql";
	db_sub_name	= row_db_sub_name;

	# Check dump dir or file existance
	if (system("test -d " dump_dir) == 0) {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump dir found: '" dump_dir "' on config item " row_number);
		}
		if (system("test -f " dump_dir "/" db_sub_name) == 0) {
			dump_file = dump_dir "/" db_sub_name;
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: Dump file inside dir found: '" dump_file "' on config item " row_number);
			}
		} else if (system("test -f " dump_dir "/" db_sub_name ".gz") == 0) {
			dump_file = dump_dir "/" db_sub_name ".gz";
			if (show_notices == 1) {
				print_timestamp(); print("NOTICE: Dump file inside dir found: '" dump_file "' on config item " row_number);
			}
		} else {
			print_timestamp(); print("ERROR: Dump file inside dir missing: '" dump_dir "/" db_sub_name "[.gz]' on config item " row_number);
			total_errors = total_errors + 1;
			next;
		}
	} else {
		print_timestamp(); print("ERROR: Dump dir missing: '" dump_dir "' on config item " row_number);
		total_errors = total_errors + 1;
		next;
	}

        # Print some stats
	if (show_notices >= 1) {
		print_timestamp();
		printf("NOTICE: Dump file stats: " host_name "/" db_sub_name " ");
		system("( [ -f '" gensub("/.sync/", "/daily.1/", "g", dump_file) "' ] && ls -h -s " gensub("/.sync/", "/daily.1/", "g", dump_file) " || echo 0 ) | awk '{print $1}' | tr -d '\n'");
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
		print_timestamp(); print("ERROR: Dump file contains < 1 INSERTS for DB: " host_name "/" db_sub_name ", file: '" dump_file "' on config item " row_number);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump contains " dump_file_analyze[dump_file, "databases"][db_sub_name] " INSERTS for DB: " host_name "/" db_sub_name ", file: '" dump_file "' on config item " row_number);
		}
		total_ok = total_ok + 1;
	}
	# Check dump date
	if ((secs_now - secs_dfa_date) > 86400) {
		print_timestamp(); print("ERROR: Dump file date older than one day: '" dump_file_analyze[dump_file, "date"] "', file: '" dump_file "' on config item " row_number);
		total_errors = total_errors + 1;
	} else {
		if (show_notices == 1) {
			print_timestamp(); print("NOTICE: Dump file date OK: '" dump_file_analyze[dump_file, "date"] "', file: '" dump_file "' on config item " row_number);
		}
		total_ok = total_ok + 1;
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
			print_timestamp(); print("NOTICE: Backup server " checked_host_name " mysql backups OK checks: " total_ok);
		}
	} else {
		print_timestamp(); print("ERROR: Backup server " checked_host_name " mysql backup errors found: " total_errors);
		exit(1);
	}
}
