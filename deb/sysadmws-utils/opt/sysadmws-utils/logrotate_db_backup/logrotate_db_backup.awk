BEGIN {
}

# Func to check batch ssh login
function check_ssh(f_host_name, f_host_port) {
	if (show_notices) {
		print_timestamp(); printf("NOTICE: Checking hostname: ");
		ssh_check_cmd = "ssh -o BatchMode=yes -p " f_host_port " " f_host_name " 'hostname'";
	} else {
		ssh_check_cmd = "ssh -o BatchMode=yes -p " f_host_port " " f_host_name " 'hostname' > /opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt 2>&1";
	}
	err = system(ssh_check_cmd);
	if (err != 0) {
		if (!show_notices) system("cat /opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt");
		print_timestamp(); print("ERROR: SSH "f_host_name" port " f_host_port " without password failed");
		return(0);
	} else {
		return(1);
	}
}
# Func to check batch ssh login
function exec_ssh(f_host_name, f_host_port, f_cmd) {
	if (show_notices) {
		print_timestamp(); print("NOTICE: Executing remote command '" f_cmd "', output: ");
		ssh_check_cmd = "ssh -o BatchMode=yes -p " f_host_port " " f_host_name " '" f_cmd "'";
	} else {
		ssh_check_cmd = "ssh -o BatchMode=yes -p " f_host_port " " f_host_name " '" f_cmd "' > /opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt 2>&1";
	}
	err = system(ssh_check_cmd);
	if (err != 0) {
		if (!show_notices) system("cat /opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt");
		print_timestamp(); print("ERROR: Remote execution on " f_host_name " port " f_host_port " of command " f_cmd " failed");
		return(0);
	} else {
		return(1);
	}
}
# Func to print timestamp at the beginning of line
function print_timestamp() {
	system("date '+%F %T ' | tr -d '\n'");
}
# system() wrapper with notices check
function system_wrap(f_cmd) {
	if (!show_notices) {
		f_cmd = f_cmd " 2>&1";
		printf("") > "/opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt";
		ERRNO = 0;
		while ((f_cmd | getline cmd_out_line) > 0) {
			print(cmd_out_line) >> "/opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt";
		}
		err = ERRNO;
		close(f_cmd);
	} else {
		err = system(f_cmd);
	}
	if (err != 0) {
		if (!show_notices) system("cat /opt/sysadmws-utils/logrotate_db_backup/logrotate_db_backup.tmp_out.txt");
	}
	return(err);
}

# Parse config file to an array
{
	# Skip commnets
	if (match($0, /^\s*#.*$/)) {
		next;
	}
	
	# Read targets
	if (match($0, /^(.+):$/, match_arr)) {
		current_target = match_arr[1];
		if (show_notices) {
			print_timestamp(); print("NOTICE: Reading target config: " current_target);
		}
	}
	if (match($0, /^  (.+): (.+)$/, match_arr)) {
		if (match_arr[1] == "dump_type")	targets[current_target]["dump_type"] 		= match_arr[2];
		if (match_arr[1] == "db")		targets[current_target]["db"] 			= match_arr[2];
		if (match_arr[1] == "nice")		targets[current_target]["nice"] 		= match_arr[2];
		if (match_arr[1] == "dump_opts")	targets[current_target]["dump_opts"] 		= match_arr[2];
		if (match_arr[1] == "auth")		targets[current_target]["auth"] 		= match_arr[2];
		if (match_arr[1] == "tables")		targets[current_target]["tables"] 		= match_arr[2];
		if (match_arr[1] == "copies_quantity")	targets[current_target]["copies_quantity"] 	= match_arr[2];
		if (match_arr[1] == "compress")		targets[current_target]["compress"] 		= match_arr[2];
		if (match(match_arr[1], /^(dst)_(.+)$/, match_arr2)) {
			targets[current_target]["dst"][match_arr2[2]] = match_arr[2];
		}
	}
}

END {
	# Loop targets
	for (i in targets) {
		# Check if target_name is set on run argument and run the only one
		if ((target_name != "") && (target_name != i)) continue;
		if (show_notices) {
			print_timestamp(); print("NOTICE: Running target: " i);
		}
		# Check defaults
		if ((targets[i]["dump_type"] != "mysql") && (targets[i]["dump_type"] != "postgresql")) {
			print_timestamp(); print("ERROR: Unknown dump type DB: " targets[i]["dump_type"]);
			continue;
		}
		if (targets[i]["db"] == "") {
			print_timestamp(); print("ERROR: Empty DB name");
			continue;
		}
		if (targets[i]["auth"] == "") {
			print_timestamp(); print("ERROR: Empty auth params");
			continue;
		}
		if ((targets[i]["db"] == "*") && (targets[i]["tables"] != "*")) {
			print_timestamp(); print("ERROR: Table names cannot be used with all databases, use separate targets");
			continue;
		}
		if (targets[i]["copies_quantity"] == "") {
			print_timestamp(); print("ERROR: Empty copies_quantity param");
			continue;
		}
		if (targets[i]["compress"] == "") {
			targets[i]["compress"] = "no";
		}
		if ((targets[i]["compress"] != "yes") && (targets[i]["compress"] != "no")) {
			print_timestamp(); print("ERROR: Unknown compress param (yes or no, please)");
			continue;
		}
		if (length(targets[i]["dst"]) < 1) {
			print_timestamp(); print("ERROR: Empty dst params");
			continue;
		}

		# Local targets first - we need something to rsync to remote
		total_local_dst = 0;
		for (m in targets[i]["dst"]) {
			if (!match(targets[i]["dst"][m], /^(.+):(.+)$/, match_arr3)) {
				# Check local destinations count
				total_local_dst++;
				if (total_local_dst > 1) {
					print_timestamp(); print("ERROR: Second local destination detected, skipping it");
					continue;
				}
				# Save the only local dst to use for remote further
				targets[i]["dst_local"] = "";
				targets[i]["dst_local"] = targets[i]["dst"][m];
				if (show_notices) {
					print_timestamp(); print("NOTICE: Running local destination: " targets[i]["dst_local"]);
				}
				# Make working directory
				system_wrap("mkdir -v -p `dirname " targets[i]["dst"][m] "`");
				# Prepare logrotate config
				system_wrap("echo '" targets[i]["dst"][m] " {' > /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
				system_wrap("echo '	rotate " targets[i]["copies_quantity"] "' >> /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
				if (targets[i]["compress"] == "yes") system_wrap("echo '	compress' >> /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
				system_wrap("echo '}' >> /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
				# Local logrotate
				system_wrap("/usr/sbin/logrotate -v -f /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
				# MySQL dumps
				if (targets[i]["dump_type"] == "mysql") {
					# Nice?
					if (targets[i]["nice"] != "") {
						mysqldump_cmd = "/usr/bin/nice -n " targets[i]["nice"];
					} else {
						mysqldump_cmd = "";
					}
					# Add auth and params
					mysqldump_cmd = mysqldump_cmd " /usr/bin/mysqldump " targets[i]["auth"] " " targets[i]["dump_opts"];
					# Dump all dbs?
					if (targets[i]["db"] == "*") {
						mysqldump_cmd = mysqldump_cmd " --all-databases";
					# Dump specific dbs
					} else {
						# If there is tables - only one db can be dumped
						if (targets[i]["tables"] != "") {
							mysqldump_cmd = mysqldump_cmd " " targets[i]["db"] " " targets[i]["tables"];
						# If there is no tables - several dbs can be dumped
						} else {
							mysqldump_cmd = mysqldump_cmd " --databases " targets[i]["db"];
						}
					}
					# Add dst
					mysqldump_cmd = mysqldump_cmd " > " targets[i]["dst"][m];
					if (show_notices) {
						print_timestamp(); print("NOTICE: Executing '" mysqldump_cmd "', output: ");
					}
					system_wrap(mysqldump_cmd);
				}
				# PostgreSQL dumps
				if (dump_type == "postgresql") {
					print_timestamp(); print("ERROR: Postgresql dumps are not avalable yet");
					continue;
				}
			}
		}
		# Check if there was local dst
		if (targets[i]["dst_local"] != "") {
			# Remote targets
			for (m in targets[i]["dst"]) {
				if (match(targets[i]["dst"][m], /^(.+):(.+)$/, match_arr3)) {
					# Remote
					# Match with :port:
					if (match(targets[i]["dst"][m], /^(.+):(.+):(.+)$/, match_arr4)) {
						dst_host = match_arr4[1];
						dst_port = match_arr4[2];
						dst_path = match_arr4[3];
					} else {
						dst_host = match_arr3[1];
						dst_port = "22";
						dst_path = match_arr3[2];
					}
					if (check_ssh(dst_host, dst_port)) {
						if (show_notices) {
							print_timestamp(); print("NOTICE: Running remote destination: " dst_host ":" dst_path);
						}
						# Make working directory
						exec_ssh(dst_host, dst_port, "mkdir -v -p `dirname " dst_path "`");
						exec_ssh(dst_host, dst_port, "mkdir -v -p /opt/sysadmws-utils/logrotate_db_backup");
						# Remote logrotate
						# Prepare logrotate config
						exec_ssh(dst_host, dst_port, "echo \"" dst_path " {\" > /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
						exec_ssh(dst_host, dst_port, "echo \"	rotate " targets[i]["copies_quantity"] "\" >> /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
						if (targets[i]["compress"] == "yes") exec_ssh(dst_host, dst_port, "echo \"	compress\" >> /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
						exec_ssh(dst_host, dst_port, "echo \"}\" >> /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
						exec_ssh(dst_host, dst_port, "/usr/sbin/logrotate -v -f /opt/sysadmws-utils/logrotate_db_backup/logrotate.conf");
						# Scp local dump to remote
						scp_cmd = "/usr/bin/scp -o BatchMode=yes -P " dst_port " " targets[i]["dst_local"] " " dst_host ":" dst_path;
						if (show_notices) {
							print_timestamp(); print("NOTICE: Executing '" scp_cmd "', output: ");
						}
						system_wrap(scp_cmd);
					}
				}
			}
		} else {
			print_timestamp(); print("ERROR: There was no local dst, nothing to copy remotely");
		}
		if (show_notices) {
			print_timestamp(); print("NOTICE: Target finished: " i);
		}
	}
}
