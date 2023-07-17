#!/opt/sysadmws/misc/shebang_python_switcher.sh -u
# -*- coding: utf-8 -*-

# -u - for unbuffered output https://docs.python.org/2/using/cmdline.html#cmdoption-u
# Otherwise output is getting mixed in pipelines

import os
import sys
import yaml
import textwrap
import logging
from logging.handlers import RotatingFileHandler
import argparse
from datetime import datetime
import socket
import lockfile
import time
import subprocess
import re
import gzip
import tarfile

# Constants
LOGO="rsnapshot_backup"
WORK_DIR = "/opt/sysadmws/rsnapshot_backup"
CONFIG_FILE = "rsnapshot_backup.yaml"
LOG_DIR = "/opt/sysadmws/rsnapshot_backup/log"
LOG_FILE = "rsnapshot_backup.log"
SELF_HOSTNAME = socket.gethostname()
# Keep lock file in /run tmpfs - for stale lock file cleanup on reboot
LOCK_FILE = "/run/rsnapshot_backup"
RSNAPSHOT_CONF = "/opt/sysadmws/rsnapshot_backup/rsnapshot.conf"
RSNAPSHOT_PASSWD = "/opt/sysadmws/rsnapshot_backup/rsnapshot.passwd"
DATA_EXPAND = {
    "UBUNTU": ["/etc","/home","/root","/var/spool/cron","/var/lib/dpkg","/usr/local","/opt/sysadmws","/opt/microdevops"],
    "DEBIAN": ["/etc","/home","/root","/var/spool/cron","/var/lib/dpkg","/usr/local","/opt/sysadmws","/opt/microdevops"],
    "CENTOS": ["/etc","/home","/root","/var/spool/cron","/var/lib/rpm","/usr/local","/opt/sysadmws","/opt/microdevops"]
}

# Functions

def log_and_print(kind, text, logger):
    # Replace words that trigger error detection in pipelines
    text_safe = text.replace("False", "F_alse")
    if kind == "NOTICE":
        logger.info(text)
    if kind == "ERROR":
        logger.info(text)
    sys.stderr.write(datetime.now().strftime("%F %T"))
    sys.stderr.write(" {kind}: ".format(kind=kind))
    sys.stderr.write(text_safe)
    sys.stderr.write("\n")

def run_cmd(cmd):

    process = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
    try:
        process.communicate(None)
    except:
        process.kill()
        process.wait()
        raise

    retcode = process.poll()

    return retcode

def run_cmd_pipe(cmd):

    process = subprocess.Popen(cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(None)
    except:
        process.kill()
        process.wait()
        raise

    retcode = process.poll()
    stdout = stdout.decode()
    stderr = stderr.decode()

    return retcode, stdout, stderr

# Main

if __name__ == "__main__":

    # Set default encoding for python 2.x (no need in python 3.x)
    if sys.version_info[0] < 3:
        reload(sys)
        sys.setdefaultencoding("utf-8")

    # Set logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    if not os.path.isdir(LOG_DIR):
        os.mkdir(LOG_DIR, 0o755)
    log_handler = RotatingFileHandler("{0}/{1}".format(LOG_DIR, LOG_FILE), maxBytes=10485760, backupCount=10, encoding="utf-8")
    os.chmod("{0}/{1}".format(LOG_DIR, LOG_FILE), 0o600)
    log_handler.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    formatter = logging.Formatter(fmt='%(asctime)s %(filename)s %(name)s %(process)d/%(threadName)s %(levelname)s: %(message)s', datefmt="%Y-%m-%d %H:%M:%S %Z")
    log_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    logger.addHandler(console_handler)

    # Set parser and parse args

    parser = argparse.ArgumentParser(description="{LOGO} functions.".format(LOGO=LOGO))

    parser.add_argument("--debug", dest="debug", help="enable debug", action="store_true")
    parser.add_argument("--config", dest="config", help="override config")
    parser.add_argument("--item-number", dest="item_number", help="run only for config item NUMBER", nargs=1, metavar=("NUMBER"))
    parser.add_argument("--host", dest="host", help="run only for items with HOST", nargs=1, metavar=("HOST"))
    parser.add_argument("--ignore-lock", dest="ignore_lock", help="ignore locking to allow many instances of rsnapshot_backup.py in the same time (use only for testing)", action="store_true")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sync", dest="sync", help="prepare rsnapshot configs and run sync, we use sync_first rsnapshot option", action="store_true")
    group.add_argument("--rotate-hourly", dest="rotate_hourly", help="prepare rsnapshot configs and run hourly rotate", action="store_true")
    group.add_argument("--rotate-daily", dest="rotate_daily", help="prepare rsnapshot configs and run daily rotate", action="store_true")
    group.add_argument("--rotate-weekly", dest="rotate_weekly", help="prepare rsnapshot configs and run weekly rotate", action="store_true")
    group.add_argument("--rotate-monthly", dest="rotate_monthly", help="prepare rsnapshot configs and run monthly rotate", action="store_true")
    group.add_argument("--check", dest="check", help="run checks for rsnapshot backups", action="store_true")

    if len(sys.argv) > 1:
        args = parser.parse_args()
    else:
        parser.print_help()
        sys.exit(1)

    # Enable debug
    if args.debug:
        console_handler.setLevel(logging.DEBUG)

    # Catch exception to logger
    try:

        # Load YAML config
        if args.config:
            # Override config
            logger.info("Loading YAML config {config_file}".format(config_file=args.config))
            with open("{config_file}".format(config_file=args.config), 'r') as yaml_file:
                config = yaml.load(yaml_file, Loader=yaml.SafeLoader)
        else:
            logger.info("Loading YAML config {work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE))
            with open("{work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE), 'r') as yaml_file:
                config = yaml.load(yaml_file, Loader=yaml.SafeLoader)

        # Check if enabled in config
        if config["enabled"] != True:
            logger.info("{LOGO} not enabled in config, exiting".format(LOGO=LOGO))
            sys.exit(0)

        log_and_print("NOTICE", "Starting {LOGO} on {hostname}".format(LOGO=LOGO, hostname=SELF_HOSTNAME), logger)

        # Chdir to work dir
        os.chdir(WORK_DIR)

        # Lock before trying to run, exception and exit on timeout is ok
        if not args.ignore_lock:
            lock = lockfile.LockFile(LOCK_FILE)
        try:

            # timeout=0 = do not wait if locked
            if not args.ignore_lock:
                lock.acquire(timeout=0)

            errors = 0
            oks = 0
            paths_processed = []

            # Loop backup items
            for item in config["items"]:

                if not item["enabled"]:
                    continue

                # Apply filters
                if args.item_number is not None:
                    if str(item["number"]) != str(args.item_number[0]):
                        continue
                if args.host is not None:
                    if item["host"] != str(args.host[0]):
                        continue

                # Backup items errors should not stop other items
                try:

                    log_and_print("NOTICE", "Processing item number {number}: {item}".format(number=item["number"], item=item), logger)

                    # Item defaults

                    if "retain_daily" not in item:
                        item["retain_daily"] = 7
                    if "retain_weekly" not in item:
                        item["retain_weekly"] = 4
                    if "retain_monthly" not in item:
                        item["retain_monthly"] = 3

                    if "connect_user" not in item:
                        item["connect_user"] = "root"

                    if "validate_hostname" not in item:
                        item["validate_hostname"] = True

                    if "mysql_noevents" not in item:
                        item["mysql_noevents"] = False
                    if "postgresql_noclean" not in item:
                        item["postgresql_noclean"] = False

                    if "native_txt_check" not in item:
                        item["native_txt_check"] = False
                    if "native_10h_limit" not in item:
                        item["native_10h_limit"] = False

                    if args.debug:
                        item["verbosity_level"] = 5
                        item["rsync_verbosity_args"] = "--human-readable --progress"
                    else:
                        item["verbosity_level"] = 2
                        item["rsync_verbosity_args"] = ""

                    if "rsync_args" not in item:
                        item["rsync_args"] = ""

                    if "mysql_dump_dir" not in item:
                        item["mysql_dump_dir"] = "/var/backups/mysql"
                    if "postgresql_dump_dir" not in item:
                        item["postgresql_dump_dir"] = "/var/backups/postgresql"
                    if "mongodb_dump_dir" not in item:
                        item["mongodb_dump_dir"] = "/var/backups/mongodb"

                    if "dump_prefix_cmd" not in item:
                        item["dump_prefix_cmd"] = ""

                    if "mysqldump_args" not in item:
                        item["mysqldump_args"] = ""
                    if "pg_dump_args" not in item:
                        item["pg_dump_args"] = ""
                    if "mongo_args" not in item:
                        item["mongo_args"] = ""
                    # For backward compatibility:
                    # if only mongo_args is set use it for mongo and mongodump
                    # if mongodump_args is set use them separately
                    if "mongodump_args" not in item:
                        item["mongodump_args"] = item["mongo_args"]

                    if "xtrabackup_throttle" not in item:
                        item["xtrabackup_throttle"] = "20" # 20 MB IO limit by default https://www.percona.com/doc/percona-xtrabackup/2.3/advanced/throttling_backups.html
                    if "xtrabackup_parallel" not in item:
                        item["xtrabackup_parallel"] = "2"
                    if "xtrabackup_compress_threads" not in item:
                        item["xtrabackup_compress_threads"] = "2"
                    if "xtrabackup_args" not in item:
                        item["xtrabackup_args"] = ""

                    if "mysqlsh_connect_args" not in item:
                        item["mysqlsh_connect_args"] = ""
                    if "mysqlsh_args" not in item:
                        item["mysqlsh_args"] = ""
                    if "mysqlsh_max_rate" not in item:
                        item["mysqlsh_max_rate"] = "20M" # 20 MB IO limit by default
                    if "mysqlsh_bytes_per_chunk" not in item:
                        item["mysqlsh_bytes_per_chunk"] = "100M"
                    if "mysqlsh_threads" not in item:
                        item["mysqlsh_threads"] = "2"

                    # Check before_backup_check and skip item if failed
                    # It is needed for both rotations and sync
                    if "before_backup_check" in item:
                        log_and_print("NOTICE", "Executing local before_backup_check on item number {number}:".format(number=item["number"]), logger)
                        log_and_print("NOTICE", "{cmd}".format(cmd=item["before_backup_check"]), logger)
                        try:
                            retcode = run_cmd(item["before_backup_check"])
                            if retcode == 0:
                                log_and_print("NOTICE", "Local execution of before_backup_check succeeded on item number {number}".format(number=item["number"]), logger)
                            else:
                                log_and_print("ERROR", "Local execution of before_backup_check failed on item number {number}, skipping item with error".format(number=item["number"]), logger)
                                errors += 1
                                continue
                        except Exception as e:
                            logger.exception(e)
                            raise Exception("Caught exception on subprocess.run execution")

                    # Rotations
                    if args.rotate_hourly or args.rotate_daily or args.rotate_weekly or args.rotate_monthly:

                        if args.rotate_hourly:
                            rsnapshot_command = "hourly"
                        if args.rotate_daily:
                            rsnapshot_command = "daily"
                        if args.rotate_weekly:
                            rsnapshot_command = "weekly"
                        if args.rotate_monthly:
                            rsnapshot_command = "monthly"

                        # Process paths from many items only once on rotations
                        if item["path"] in paths_processed:
                            log_and_print("NOTICE", "Path {path} on item number {number} already rotated, skipping".format(path=item["path"], number=item["number"]), logger)
                            continue
                        paths_processed.append(item["path"])

                        with open(RSNAPSHOT_CONF, "w") as file_to_write:
                            file_to_write.write(textwrap.dedent(
                                """\
                                config_version	1.2
                                snapshot_root	{snapshot_root}
                                cmd_cp		/bin/cp
                                cmd_rm		/bin/rm
                                cmd_rsync	/usr/bin/rsync
                                cmd_ssh		/usr/bin/ssh
                                cmd_logger	/usr/bin/logger
                                {retain_hourly_comment}retain		hourly	{retain_hourly}
                                retain		daily	{retain_daily}
                                retain		weekly	{retain_weekly}
                                retain		monthly	{retain_monthly}
                                verbose		{verbosity_level}
                                loglevel	3
                                logfile		/opt/sysadmws/rsnapshot_backup/rsnapshot.log
                                lockfile	/opt/sysadmws/rsnapshot_backup/rsnapshot.pid
                                sync_first	1
                                # any backup definition enough for rotation
                                backup		/etc/		rsnapshot/
                                """
                            ).format(
                                snapshot_root=item["path"],
                                retain_hourly_comment="" if "retain_hourly" in item else "#",
                                retain_hourly=item["retain_hourly"] if "retain_hourly" in item else "NONE",
                                retain_daily=item["retain_daily"],
                                retain_weekly=item["retain_weekly"],
                                retain_monthly=item["retain_monthly"],
                                verbosity_level=item["verbosity_level"]
                            ))
                        
                        # Run rsnapshot
                        if "rsnapshot_prefix_cmd" in item:
                            rsnapshot_prefix_cmd = "{rsnapshot_prefix_cmd} ".format(rsnapshot_prefix_cmd=item["rsnapshot_prefix_cmd"])
                        else:
                            rsnapshot_prefix_cmd = ""
                        log_and_print("NOTICE", "Running {rsnapshot_prefix_cmd}rsnapshot -c {conf} {command} on item number {number}".format(
                            rsnapshot_prefix_cmd=rsnapshot_prefix_cmd,
                            conf=RSNAPSHOT_CONF,
                            command=rsnapshot_command,
                            number=item["number"]
                        ), logger)
                        try:
                            retcode = run_cmd("{rsnapshot_prefix_cmd}rsnapshot -c {conf} {command}".format(
                                rsnapshot_prefix_cmd=rsnapshot_prefix_cmd,
                                conf=RSNAPSHOT_CONF,
                                command=rsnapshot_command
                            ))
                            if retcode == 0:
                                log_and_print("NOTICE", "Rsnapshot succeeded on item number {number}".format(number=item["number"]), logger)
                            else:
                                log_and_print("ERROR", "Rsnapshot failed on item number {number}".format(number=item["number"]), logger)
                                errors += 1
                        except Exception as e:
                            logger.exception(e)
                            raise Exception("Caught exception on subprocess.run execution")
                    
                    # Sync
                    if args.sync:

                        # With retries we cannot show error word in output text, otherwise an error will be detected
                        rsnapshot_error_filter = "sed -e 's/ERROR/E.ROR/g' -e 's/Error/E.ror/g' -e 's/error/e.ror/g'"

                        if item["type"] in ["RSYNC_SSH", "MYSQL_SSH", "POSTGRESQL_SSH", "MONGODB_SSH"]:

                            ssh_args = "-o BatchMode=yes -o StrictHostKeyChecking=no"

                            if ":" in item["connect"]:
                                item["connect_host"] = item["connect"].split(":")[0]
                                item["connect_port"] = item["connect"].split(":")[1]
                            else:
                                item["connect_host"] = item["connect"]
                                item["connect_port"] = 22
                            
                            # Check SSH

                            log_and_print("NOTICE", "Checking remote SSH on item number {number}:".format(number=item["number"]), logger)
                            try:
                                retcode = run_cmd("ssh {ssh_args} -p {port} {user}@{host} 'hostname'".format(ssh_args=ssh_args, port=item["connect_port"], user=item["connect_user"], host=item["connect_host"]))
                                if retcode == 0:
                                    log_and_print("NOTICE", "SSH without password succeeded on item number {number}".format(number=item["number"]), logger)
                                else:

                                    if item["host"] == SELF_HOSTNAME:

                                        log_and_print("NOTICE", "Loopback connect detected on item number {number}, trying to add server key to authorized".format(number=item["number"]), logger)
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e
                                            
                                            if [[ ! -e /root/.ssh/id_rsa.pub ]]; then
                                                    ssh-keygen -b 4096 -f /root/.ssh/id_rsa -q -N ''
                                            fi
                                            
                                            if [[ ! -e /root/.ssh/authorized_keys ]]; then
                                                    cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys
                                                    chmod 600 /root/.ssh/authorized_keys
                                            fi
                                            
                                            if ! grep -q "$(cat /root/.ssh/id_rsa.pub)" /root/.ssh/authorized_keys; then
                                                    cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys
                                                    chmod 600 /root/.ssh/authorized_keys
                                            fi
                                            """
                                        )
                                        try:
                                            retcode = run_cmd(script)
                                            if retcode == 0:
                                                log_and_print("NOTICE", "Loopback authorization script succeeded on item number {number}".format(number=item["number"]), logger)
                                            else:
                                                log_and_print("ERROR", "Loopback authorization script failed on item number {number}, not doing sync".format(number=item["number"]), logger)
                                                errors += 1
                                                continue
                                        except Exception as e:
                                            logger.exception(e)
                                            raise Exception("Caught exception on subprocess.run execution")
                                        
                                        log_and_print("NOTICE", "Checking again remote SSH on item number {number}:".format(number=item["number"]), logger)
                                        try:
                                            retcode = run_cmd("ssh {ssh_args} -p {port} {user}@{host} 'hostname'".format(ssh_args=ssh_args, port=item["connect_port"], user=item["connect_user"], host=item["connect_host"]))
                                            if retcode == 0:
                                                log_and_print("NOTICE", "SSH without password succeeded on item number {number}".format(number=item["number"]), logger)
                                            else:
                                                log_and_print("ERROR", "SSH without password failed on item number {number}, not doing sync".format(number=item["number"]), logger)
                                                errors += 1
                                                continue
                                        except Exception as e:
                                            logger.exception(e)
                                            raise Exception("Caught exception on subprocess.run execution")

                                    else:
                                        log_and_print("ERROR", "SSH without password failed on item number {number}, not doing sync".format(number=item["number"]), logger)
                                        errors += 1
                                        continue
                            
                            except Exception as e:
                                logger.exception(e)
                                raise Exception("Caught exception on subprocess.run execution")

                            # Validate hostname
                            if item["validate_hostname"]:
                                log_and_print("NOTICE", "Hostname validation required on item number {number}".format(number=item["number"]), logger)
                                try:
                                    retcode, stdout, stderr = run_cmd_pipe("ssh {ssh_args} -p {port} {user}@{host} 'hostname'".format(ssh_args=ssh_args, port=item["connect_port"], user=item["connect_user"], host=item["connect_host"]))
                                    if retcode == 0:
                                        hostname_received = stdout.lstrip().rstrip()
                                        if hostname_received == item["host"]:
                                            log_and_print("NOTICE", "Remote hostname {hostname} received and validated on item number {number}".format(hostname=hostname_received, number=item["number"]), logger)
                                        else:
                                            log_and_print("ERROR", "Remote hostname {hostname} received, {expected} expected and validation failed on item number {number}, not doing sync".format(hostname=hostname_received, expected=item["host"], number=item["number"]), logger)
                                            errors += 1
                                            continue
                                    else:
                                        log_and_print("ERROR", "Remote hostname validation failed on item number {number}, not doing sync".format(number=item["number"]), logger)
                                        errors += 1
                                        continue
                                except Exception as e:
                                    logger.exception(e)
                                    raise Exception("Caught exception on subprocess.run execution")

                            # Exec exec_before_rsync
                            if "exec_before_rsync" in item:
                                log_and_print("NOTICE", "Executing remote exec_before_rsync on item number {number}".format(number=item["number"]), logger)
                                log_and_print("NOTICE", "{cmd}".format(cmd=item["exec_before_rsync"]), logger)
                                try:
                                    retcode = run_cmd("ssh {ssh_args} -p {port} {user}@{host} '{cmd}'".format(ssh_args=ssh_args, port=item["connect_port"], user=item["connect_user"], host=item["connect_host"], cmd=item["exec_before_rsync"]))
                                    if retcode == 0:
                                        log_and_print("NOTICE", "Remote execution of exec_before_rsync succeeded on item number {number}".format(number=item["number"]), logger)
                                    else:
                                        log_and_print("ERROR", "Remote execution of exec_before_rsync failed on item number {number}, but script continues".format(number=item["number"]), logger)
                                        errors += 1
                                except Exception as e:
                                    logger.exception(e)
                                    raise Exception("Caught exception on subprocess.run execution")

                            # DB dumps before rsync

                            if item["type"] in ["MYSQL_SSH", "POSTGRESQL_SSH", "MONGODB_SSH"]:

                                # Generic grep filter for excludes
                                if "exclude" in item:
                                    grep_db_filter = "| grep -v"
                                    for db_to_exclude in item["exclude"]:
                                        grep_db_filter += " -e {db_to_exclude}".format(db_to_exclude=db_to_exclude)
                                else:
                                    grep_db_filter = ""

                                if item["type"] == "MYSQL_SSH":

                                    if "mysql_dump_type" in item and item["mysql_dump_type"] == "xtrabackup":

                                        if "exclude" in item:
                                            databases_exclude = "--databases-exclude=\""
                                            databases_exclude += " ".join(item["exclude"])
                                            databases_exclude += "\""
                                        else:
                                            databases_exclude = ""

                                        xtrabackup_output_filter = 'grep -v -e "log scanned up to" -e "Skipping" -e "Compressing" -e "...done"'

                                        if item["source"] == "ALL":
                                            script_dump_part = textwrap.dedent(
                                                """\
                                                if [[ ! -d {mysql_dump_dir}/all.xtrabackup ]]; then
                                                        {dump_prefix_cmd} xtrabackup --backup --compress --throttle={xtrabackup_throttle} --parallel={xtrabackup_parallel} --compress-threads={xtrabackup_compress_threads} --target-dir={mysql_dump_dir}/all.xtrabackup {databases_exclude} {xtrabackup_args} 2>&1 | {xtrabackup_output_filter}
                                                fi
                                                """
                                            ).format(
                                                xtrabackup_throttle=item["xtrabackup_throttle"],
                                                xtrabackup_parallel=item["xtrabackup_parallel"],
                                                xtrabackup_compress_threads=item["xtrabackup_compress_threads"],
                                                mysql_dump_dir=item["mysql_dump_dir"],
                                                databases_exclude=databases_exclude,
                                                dump_prefix_cmd=item["dump_prefix_cmd"],
                                                xtrabackup_args=item["xtrabackup_args"],
                                                xtrabackup_output_filter=xtrabackup_output_filter
                                            )
                                        else:
                                            script_dump_part = textwrap.dedent(
                                                """\
                                                if [[ ! -d {mysql_dump_dir}/{source}.xtrabackup ]]; then
                                                        {dump_prefix_cmd} xtrabackup --backup --compress --throttle={xtrabackup_throttle} --parallel={xtrabackup_parallel} --compress-threads={xtrabackup_compress_threads} --target-dir={mysql_dump_dir}/{source}.xtrabackup --databases={source} {xtrabackup_args} 2>&1 | {xtrabackup_output_filter}
                                                fi
                                                """
                                            ).format(
                                                xtrabackup_throttle=item["xtrabackup_throttle"],
                                                xtrabackup_parallel=item["xtrabackup_parallel"],
                                                xtrabackup_compress_threads=item["xtrabackup_compress_threads"],
                                                mysql_dump_dir=item["mysql_dump_dir"],
                                                source=item["source"],
                                                dump_prefix_cmd=item["dump_prefix_cmd"],
                                                xtrabackup_args=item["xtrabackup_args"],
                                                xtrabackup_output_filter=xtrabackup_output_filter
                                            )

                                        # If hourly retains are used keep dumps only for 59 minutes
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e

                                            ssh {ssh_args} -p {port} {user}@{host} '
                                                set -x
                                                set -e
                                                set -o pipefail
                                                mkdir -p {mysql_dump_dir}
                                                chmod 700 {mysql_dump_dir}
                                                while [[ -d {mysql_dump_dir}/dump.lock ]]; do
                                                        sleep 5
                                                done
                                                mkdir {mysql_dump_dir}/dump.lock
                                                trap "rm -rf {mysql_dump_dir}/dump.lock" 0
                                                cd {mysql_dump_dir}
                                                find {mysql_dump_dir} -type d -name "*.xtrabackup" -mmin +{mmin} -exec rm -rf {{}} +
                                                {script_dump_part}
                                            '
                                            """
                                        ).format(
                                            ssh_args=ssh_args,
                                            port=item["connect_port"],
                                            user=item["connect_user"],
                                            host=item["connect_host"],
                                            mysql_dump_dir=item["mysql_dump_dir"],
                                            mmin="59" if "retain_hourly" in item else "720",
                                            script_dump_part=script_dump_part
                                        )

                                    elif "mysql_dump_type" in item and item["mysql_dump_type"] == "mysqlsh":

                                        if "exclude" in item:
                                            databases_exclude = "--excludeSchemas="
                                            databases_exclude += ",".join(item["exclude"])
                                        else:
                                            databases_exclude = ""

                                        # Regex dots are to hide words that produce false positive
                                        mysqlsh_output_filter = 'grep -v -e "dump may f..l with an e...r" -e "Writing DDL" -e "Data dump for" -e "Found e...rs loading plugins" -e "Preparing data dump for" -e "Could not select a column to be used as an index"'

                                        if item["source"] == "ALL":
                                            script_dump_part = textwrap.dedent(
                                                """\
                                                if [[ ! -d {mysql_dump_dir}/all.mysqlsh ]]; then
                                                        {dump_prefix_cmd} mysqlsh {mysqlsh_connect_args} -- util dump-instance {mysql_dump_dir}/all.mysqlsh --maxRate={mysqlsh_max_rate} --bytesPerChunk={mysqlsh_bytes_per_chunk} --threads={mysqlsh_threads} {databases_exclude} {mysqlsh_args} 2>&1 | {mysqlsh_output_filter}
                                                fi
                                                """
                                            ).format(
                                                mysql_dump_dir=item["mysql_dump_dir"],
                                                dump_prefix_cmd=item["dump_prefix_cmd"],
                                                mysqlsh_connect_args=item["mysqlsh_connect_args"],
                                                mysqlsh_max_rate=item["mysqlsh_max_rate"],
                                                mysqlsh_bytes_per_chunk=item["mysqlsh_bytes_per_chunk"],
                                                mysqlsh_threads=item["mysqlsh_threads"],
                                                databases_exclude=databases_exclude,
                                                mysqlsh_args=item["mysqlsh_args"],
                                                mysqlsh_output_filter=mysqlsh_output_filter
                                            )
                                        else:
                                            script_dump_part = textwrap.dedent(
                                                """\
                                                if [[ ! -d {mysql_dump_dir}/{source}.mysqlsh ]]; then
                                                        {dump_prefix_cmd} mysqlsh {mysqlsh_connect_args} -- util dump-schemas {source} --outputUrl={mysql_dump_dir}/{source}.mysqlsh --maxRate={mysqlsh_max_rate} --bytesPerChunk={mysqlsh_bytes_per_chunk} --threads={mysqlsh_threads} {mysqlsh_args} 2>&1 | {mysqlsh_output_filter}
                                                fi
                                                """
                                            ).format(
                                                mysql_dump_dir=item["mysql_dump_dir"],
                                                source=item["source"],
                                                dump_prefix_cmd=item["dump_prefix_cmd"],
                                                mysqlsh_connect_args=item["mysqlsh_connect_args"],
                                                mysqlsh_max_rate=item["mysqlsh_max_rate"],
                                                mysqlsh_bytes_per_chunk=item["mysqlsh_bytes_per_chunk"],
                                                mysqlsh_threads=item["mysqlsh_threads"],
                                                mysqlsh_args=item["mysqlsh_args"],
                                                mysqlsh_output_filter=mysqlsh_output_filter
                                            )

                                        # If hourly retains are used keep dumps only for 59 minutes
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e

                                            ssh {ssh_args} -p {port} {user}@{host} '
                                                set -x
                                                set -e
                                                set -o pipefail
                                                mkdir -p {mysql_dump_dir}
                                                chmod 700 {mysql_dump_dir}
                                                while [[ -d {mysql_dump_dir}/dump.lock ]]; do
                                                        sleep 5
                                                done
                                                mkdir {mysql_dump_dir}/dump.lock
                                                trap "rm -rf {mysql_dump_dir}/dump.lock" 0
                                                cd {mysql_dump_dir}
                                                find {mysql_dump_dir} -type d -name "*.mysqlsh" -mmin +{mmin} -exec rm -rf {{}} +
                                                {script_dump_part}
                                            '
                                            """
                                        ).format(
                                            ssh_args=ssh_args,
                                            port=item["connect_port"],
                                            user=item["connect_user"],
                                            host=item["connect_host"],
                                            mysql_dump_dir=item["mysql_dump_dir"],
                                            mmin="59" if "retain_hourly" in item else "720",
                                            script_dump_part=script_dump_part
                                        )

                                    else:

                                        if item["source"] == "ALL":
                                            script_dump_part = textwrap.dedent(
                                                """\
                                                mysql --defaults-file=/etc/mysql/debian.cnf --skip-column-names --batch -e "SHOW DATABASES;" | grep -v -e information_schema -e performance_schema {grep_db_filter} > {mysql_dump_dir}/db_list.txt
                                                for db in $(cat {mysql_dump_dir}/db_list.txt); do
                                                        if [[ ! -f {mysql_dump_dir}/$db.gz ]]; then
                                                                {dump_prefix_cmd} mysqldump --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --skip-lock-tables {mysql_events} --databases $db --max_allowed_packet=1G {mysqldump_args} | gzip > {mysql_dump_dir}/$db.gz
                                                        fi
                                                done
                                                """
                                            ).format(
                                                mysql_dump_dir=item["mysql_dump_dir"],
                                                mysql_events="" if item["mysql_noevents"] else "--events",
                                                dump_prefix_cmd=item["dump_prefix_cmd"],
                                                mysqldump_args=item["mysqldump_args"],
                                                grep_db_filter=grep_db_filter
                                            )
                                        else:
                                            script_dump_part = textwrap.dedent(
                                                """\
                                                if [[ ! -f {mysql_dump_dir}/{source}.gz ]]; then
                                                        {dump_prefix_cmd} mysqldump --defaults-file=/etc/mysql/debian.cnf --force --opt --single-transaction --quick --skip-lock-tables {mysql_events} --databases {source} --max_allowed_packet=1G {mysqldump_args} | gzip > {mysql_dump_dir}/{source}.gz
                                                fi
                                                """
                                            ).format(
                                                mysql_dump_dir=item["mysql_dump_dir"],
                                                mysql_events="" if item["mysql_noevents"] else "--events",
                                                dump_prefix_cmd=item["dump_prefix_cmd"],
                                                mysqldump_args=item["mysqldump_args"],
                                                grep_db_filter=grep_db_filter,
                                                source=item["source"]
                                            )

                                        # If hourly retains are used keep dumps only for 59 minutes
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e

                                            ssh {ssh_args} -p {port} {user}@{host} '
                                                set -x
                                                set -e
                                                set -o pipefail
                                                mkdir -p {mysql_dump_dir}
                                                chmod 700 {mysql_dump_dir}
                                                while [[ -d {mysql_dump_dir}/dump.lock ]]; do
                                                        sleep 5
                                                done
                                                mkdir {mysql_dump_dir}/dump.lock
                                                trap "rm -rf {mysql_dump_dir}/dump.lock" 0
                                                cd {mysql_dump_dir}
                                                find {mysql_dump_dir} -type f -name "*.gz" -mmin +{mmin} -delete
                                                {script_dump_part}
                                            '
                                            """
                                        ).format(
                                            ssh_args=ssh_args,
                                            port=item["connect_port"],
                                            user=item["connect_user"],
                                            host=item["connect_host"],
                                            mysql_dump_dir=item["mysql_dump_dir"],
                                            mmin="59" if "retain_hourly" in item else "720",
                                            script_dump_part=script_dump_part
                                        )

                                if item["type"] == "POSTGRESQL_SSH":

                                    # --verbose is needed for Completed on signature in dumps, and sdterr shouldn't be redirected to /dev/null
                                    # and it produces a lot of noise, we need to filter it
                                    # 2>&1 cannot be used before | gzip
                                    # grep output should be put into stderr again
                                    # https://unix.stackexchange.com/questions/3514/how-to-grep-standard-error-stream-stderr
                                    # allow pg_dump.*: connecting just to see what it does
                                    pg_dump_filter = "grep -v -e \"pg_dump.*: creating\" -e \"pg_dump.*: executing\" -e \"pg_dump.*: last built-in\" -e \"pg_dump.*: reading\" -e \"pg_dump.*: identifying\" -e \"pg_dump.*: finding\" -e \"pg_dump.*: flagging\" -e \"pg_dump.*: saving\" -e \"pg_dump.*: dropping\" -e \"pg_dump.*: dumping\" -e \"pg_dump.*: running\" -e \"pg_dump.*: processing\" >&2"

                                    if item["source"] == "ALL":
                                        script_dump_part = textwrap.dedent(
                                            """\
                                            su - postgres -c "echo SELECT datname FROM pg_database | psql --no-align -t template1" {grep_db_filter} | grep -v -e template0 -e template1 > {postgresql_dump_dir}/db_list.txt
                                            for db in $(cat {postgresql_dump_dir}/db_list.txt); do
                                                    if [[ ! -f {postgresql_dump_dir}/$db.gz ]]; then
                                                            su - postgres -c "{dump_prefix_cmd} pg_dump --create {postgresql_clean} {pg_dump_args} --verbose $db" 2> >({pg_dump_filter}) | gzip > {postgresql_dump_dir}/$db.gz
                                                    fi
                                            done
                                            """
                                        ).format(
                                            postgresql_dump_dir=item["postgresql_dump_dir"],
                                            postgresql_clean="" if item["postgresql_noclean"] else "--clean",
                                            dump_prefix_cmd=item["dump_prefix_cmd"],
                                            pg_dump_args=item["pg_dump_args"],
                                            grep_db_filter=grep_db_filter,
                                            pg_dump_filter=pg_dump_filter
                                        )
                                    else:
                                        script_dump_part = textwrap.dedent(
                                            """\
                                            if [[ ! -f {postgresql_dump_dir}/{source}.gz ]]; then
                                                    su - postgres -c "{dump_prefix_cmd} pg_dump --create {postgresql_clean} {pg_dump_args} --verbose {source}" 2> >({pg_dump_filter}) | gzip > {postgresql_dump_dir}/{source}.gz
                                            fi
                                            """
                                        ).format(
                                            postgresql_dump_dir=item["postgresql_dump_dir"],
                                            postgresql_clean="" if item["postgresql_noclean"] else "--clean",
                                            dump_prefix_cmd=item["dump_prefix_cmd"],
                                            pg_dump_args=item["pg_dump_args"],
                                            grep_db_filter=grep_db_filter,
                                            source=item["source"],
                                            pg_dump_filter=pg_dump_filter
                                        )

                                    # If hourly retains are used keep dumps only for 59 minutes
                                    script = textwrap.dedent(
                                        """\
                                        #!/bin/bash
                                        set -e

                                        ssh {ssh_args} -p {port} {user}@{host} '
                                            set -x
                                            set -e
                                            set -o pipefail
                                            mkdir -p {postgresql_dump_dir}
                                            chmod 700 {postgresql_dump_dir}
                                            while [[ -d {postgresql_dump_dir}/dump.lock ]]; do
                                                    sleep 5
                                            done
                                            mkdir {postgresql_dump_dir}/dump.lock
                                            trap "rm -rf {postgresql_dump_dir}/dump.lock" 0
                                            cd {postgresql_dump_dir}
                                            find {postgresql_dump_dir} -type f -name "*.gz" -mmin +{mmin} -delete
                                            su - postgres -c "pg_dumpall --clean --schema-only --verbose" 2> >({pg_dump_filter}) | gzip > {postgresql_dump_dir}/globals.gz
                                            {script_dump_part}
                                        '
                                        """
                                    ).format(
                                        ssh_args=ssh_args,
                                        port=item["connect_port"],
                                        user=item["connect_user"],
                                        host=item["connect_host"],
                                        postgresql_dump_dir=item["postgresql_dump_dir"],
                                        mmin="59" if "retain_hourly" in item else "720",
                                        script_dump_part=script_dump_part,
                                        pg_dump_filter=pg_dump_filter
                                    )

                                if item["type"] == "MONGODB_SSH":

                                    if item["source"] == "ALL":
                                        script_dump_part = textwrap.dedent(
                                            """\
                                            echo show dbs | mongo --quiet {mongo_args} | cut -f1 -d" " | grep -v -e local {grep_db_filter} > {mongodb_dump_dir}/db_list.txt
                                            for db in $(cat {mongodb_dump_dir}/db_list.txt); do
                                                    if [[ ! -f {mongodb_dump_dir}/$db.tar.gz ]]; then
                                                            {dump_prefix_cmd} mongodump --quiet {mongodump_args} --out {mongodb_dump_dir} --dumpDbUsersAndRoles --db $db
                                                            cd {mongodb_dump_dir}
                                                            tar zcvf {mongodb_dump_dir}/$db.tar.gz $db
                                                            rm -rf {mongodb_dump_dir}/$db
                                                    fi
                                            done
                                            """
                                        ).format(
                                            mongodb_dump_dir=item["mongodb_dump_dir"],
                                            dump_prefix_cmd=item["dump_prefix_cmd"],
                                            mongo_args=item["mongo_args"],
                                            mongodump_args=item["mongodump_args"],
                                            grep_db_filter=grep_db_filter
                                        )
                                    else:
                                        script_dump_part = textwrap.dedent(
                                            """\
                                            if [[ ! -f {mongodb_dump_dir}/{source}.tar.gz ]]; then
                                                    {dump_prefix_cmd} mongodump --quiet {mongodump_args} --out {mongodb_dump_dir} --dumpDbUsersAndRoles --db {source}
                                                    cd {mongodb_dump_dir}
                                                    tar zcvf {mongodb_dump_dir}/{source}.tar.gz {source}
                                                    rm -rf {mongodb_dump_dir}/{source}
                                            fi
                                            """
                                        ).format(
                                            mongodb_dump_dir=item["mongodb_dump_dir"],
                                            dump_prefix_cmd=item["dump_prefix_cmd"],
                                            mongo_args=item["mongo_args"],
                                            mongodump_args=item["mongodump_args"],
                                            grep_db_filter=grep_db_filter,
                                            source=item["source"]
                                        )

                                    # If hourly retains are used keep dumps only for 59 minutes
                                    script = textwrap.dedent(
                                        """\
                                        #!/bin/bash
                                        set -e

                                        ssh {ssh_args} -p {port} {user}@{host} '
                                            set -x
                                            set -e
                                            set -o pipefail
                                            mkdir -p {mongodb_dump_dir}
                                            chmod 700 {mongodb_dump_dir}
                                            while [[ -d {mongodb_dump_dir}/dump.lock ]]; do
                                                    sleep 5
                                            done
                                            mkdir {mongodb_dump_dir}/dump.lock
                                            trap "rm -rf {mongodb_dump_dir}/dump.lock" 0
                                            cd {mongodb_dump_dir}
                                            find {mongodb_dump_dir} -type f -name "*.tar.gz" -mmin +{mmin} -delete
                                            {script_dump_part}
                                        '
                                        """
                                    ).format(
                                        ssh_args=ssh_args,
                                        port=item["connect_port"],
                                        user=item["connect_user"],
                                        host=item["connect_host"],
                                        mongodb_dump_dir=item["mongodb_dump_dir"],
                                        mmin="59" if "retain_hourly" in item else "720",
                                        script_dump_part=script_dump_part
                                    )

                                log_and_print("NOTICE", "Running remote dump on item number {number}:".format(number=item["number"]), logger)
                                try:
                                    retcode = run_cmd(script)
                                    if retcode == 0:
                                        log_and_print("NOTICE", "Remote dump succeeded on item number {number}".format(number=item["number"]), logger)
                                    else:
                                        log_and_print("ERROR", "Remote dump failed on item number {number}, not doing sync".format(number=item["number"]), logger)
                                        errors += 1
                                        continue
                                except Exception as e:
                                    logger.exception(e)
                                    raise Exception("Caught exception on subprocess.run execution")

                                # Remove partially downloaded dumps
                                log_and_print("NOTICE", "Removing partially downloaded dummps if any on item number {number}:".format(number=item["number"]), logger)
                                if item["type"] == "MYSQL_SSH":
                                    if "mysql_dump_type" in item and item["mysql_dump_type"] == "xtrabackup":
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e
                                            if [[ -d {snapshot_root}/.sync/rsnapshot{mysql_dump_dir} ]]; then
                                                find {snapshot_root}/.sync/rsnapshot{mysql_dump_dir} -type f -name "*.qp.*" -delete
                                            fi
                                            """
                                        ).format(
                                            snapshot_root=item["path"],
                                            mysql_dump_dir=item["mysql_dump_dir"]
                                        )
                                    elif "mysql_dump_type" in item and item["mysql_dump_type"] == "mysqlsh":
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e
                                            if [[ -d {snapshot_root}/.sync/rsnapshot{mysql_dump_dir} ]]; then
                                                find {snapshot_root}/.sync/rsnapshot{mysql_dump_dir} -type f -name "*.zst" -delete
                                            fi
                                            """
                                        ).format(
                                            snapshot_root=item["path"],
                                            mysql_dump_dir=item["mysql_dump_dir"]
                                        )
                                    else:
                                        script = textwrap.dedent(
                                            """\
                                            #!/bin/bash
                                            set -e
                                            rm -f {snapshot_root}/.sync/rsnapshot{mysql_dump_dir}/.*.gz.*
                                            """
                                        ).format(
                                            snapshot_root=item["path"],
                                            mysql_dump_dir=item["mysql_dump_dir"]
                                        )
                                if item["type"] == "POSTGRESQL_SSH":
                                    script = textwrap.dedent(
                                        """\
                                        #!/bin/bash
                                        set -e
                                        rm -f {snapshot_root}/.sync/rsnapshot{postgresql_dump_dir}/.*.gz.*
                                        """
                                    ).format(
                                        snapshot_root=item["path"],
                                        postgresql_dump_dir=item["postgresql_dump_dir"]
                                    )
                                if item["type"] == "MONGODB_SSH":
                                    script = textwrap.dedent(
                                        """\
                                        #!/bin/bash
                                        set -e
                                        rm -f {snapshot_root}/.sync/rsnapshot{mongodb_dump_dir}/.*.tar.gz.*
                                        """
                                    ).format(
                                        snapshot_root=item["path"],
                                        mongodb_dump_dir=item["mongodb_dump_dir"]
                                    )
                                try:
                                    retcode = run_cmd(script)
                                    if retcode == 0:
                                        log_and_print("NOTICE", "Removing partially downloaded dummps command succeeded on item number {number}".format(number=item["number"]), logger)
                                    else:
                                        log_and_print("ERROR", "Removing partially downloaded dummps command failed on item number {number}, but script continues".format(number=item["number"]), logger)
                                        errors += 1
                                except Exception as e:
                                    logger.exception(e)
                                    raise Exception("Caught exception on subprocess.run execution")

                            # Populate backup lines in config

                            conf_backup_line_template = textwrap.dedent(
                                """\
                                backup		{user}@{host}:{source}/	rsnapshot/{tab_before_rsync_long_args}{rsync_long_args}
                                """
                            )
                            conf_backup_lines = ""

                            if item["type"] == "RSYNC_SSH":

                                if item["source"] in DATA_EXPAND:
                                    for source in DATA_EXPAND[item["source"]]:
                                        if not ("exclude" in item and source in item["exclude"]):
                                            conf_backup_lines += conf_backup_line_template.format(
                                                user=item["connect_user"],
                                                host=item["connect_host"],
                                                source=source,
                                                tab_before_rsync_long_args="\t" if source == "/opt/sysadmws" else "",
                                                rsync_long_args="+rsync_long_args=--exclude=/opt/sysadmws/bulk_log --exclude=log" if source == "/opt/sysadmws" else ""
                                            )
                                else:
                                    conf_backup_lines += conf_backup_line_template.format(
                                        user=item["connect_user"],
                                        host=item["connect_host"],
                                        source=item["source"],
                                        tab_before_rsync_long_args="",
                                        rsync_long_args=""
                                    )

                            if item["type"] == "MYSQL_SSH":
                                # We do not need rsync compression as xtrabackup or mysqlsh dumps are already compressed
                                # With compress it takes 10-12 times longer
                                conf_backup_lines += conf_backup_line_template.format(
                                    user=item["connect_user"],
                                    host=item["connect_host"],
                                    source=item["mysql_dump_dir"],
                                    tab_before_rsync_long_args="\t" if "mysql_dump_type" in item and (item["mysql_dump_type"] == "xtrabackup" or item["mysql_dump_type"] == "mysqlsh") else "",
                                    rsync_long_args="+rsync_long_args=--no-compress" if "mysql_dump_type" in item and (item["mysql_dump_type"] == "xtrabackup" or item["mysql_dump_type"] == "mysqlsh") else ""
                                )
                            if item["type"] == "POSTGRESQL_SSH":
                                conf_backup_lines += conf_backup_line_template.format(
                                    user=item["connect_user"],
                                    host=item["connect_host"],
                                    source=item["postgresql_dump_dir"],
                                    tab_before_rsync_long_args="",
                                    rsync_long_args=""
                                )
                            if item["type"] == "MONGODB_SSH":
                                conf_backup_lines += conf_backup_line_template.format(
                                    user=item["connect_user"],
                                    host=item["connect_host"],
                                    source=item["mongodb_dump_dir"],
                                    tab_before_rsync_long_args="",
                                    rsync_long_args=""
                                )

                            # Save config
                            with open(RSNAPSHOT_CONF, "w") as file_to_write:
                                file_to_write.write(textwrap.dedent(
                                    """\
                                    config_version	1.2
                                    snapshot_root	{snapshot_root}
                                    cmd_cp		/bin/cp
                                    cmd_rm		/bin/rm
                                    cmd_rsync	/usr/bin/rsync
                                    cmd_ssh		/usr/bin/ssh
                                    cmd_logger	/usr/bin/logger
                                    {retain_hourly_comment}retain		hourly	{retain_hourly}
                                    retain		daily	{retain_daily}
                                    retain		weekly	{retain_weekly}
                                    retain		monthly	{retain_monthly}
                                    verbose		{verbosity_level}
                                    loglevel	3
                                    logfile		/opt/sysadmws/rsnapshot_backup/rsnapshot.log
                                    lockfile	/opt/sysadmws/rsnapshot_backup/rsnapshot.pid
                                    ssh_args	{ssh_args} -p {port}
                                    rsync_long_args	-az --delete --delete-excluded --numeric-ids --relative {rsync_verbosity_args} {rsync_args}
                                    sync_first	1
                                    {conf_backup_lines}
                                    """
                                ).format(
                                    snapshot_root=item["path"],
                                    retain_hourly_comment="" if "retain_hourly" in item else "#",
                                    retain_hourly=item["retain_hourly"] if "retain_hourly" in item else "NONE",
                                    retain_daily=item["retain_daily"],
                                    retain_weekly=item["retain_weekly"],
                                    retain_monthly=item["retain_monthly"],
                                    verbosity_level=item["verbosity_level"],
                                    port=item["connect_port"],
                                    ssh_args=ssh_args,
                                    rsync_verbosity_args=item["rsync_verbosity_args"],
                                    rsync_args=item["rsync_args"],
                                    conf_backup_lines=conf_backup_lines
                                ))
                        
                            # Run rsnapshot
                            if "rsnapshot_prefix_cmd" in item:
                                rsnapshot_prefix_cmd = "{rsnapshot_prefix_cmd} ".format(rsnapshot_prefix_cmd=item["rsnapshot_prefix_cmd"])
                            else:
                                rsnapshot_prefix_cmd = ""
                            log_and_print("NOTICE", "Running {rsnapshot_prefix_cmd}rsnapshot -c {conf} sync on item number {number}".format(
                                rsnapshot_prefix_cmd=rsnapshot_prefix_cmd,
                                conf=RSNAPSHOT_CONF,
                                number=item["number"]
                            ), logger)
                            try:

                                if "retries" in item:
                                    times_to_run_max = 1 + item["retries"]
                                else:
                                    times_to_run_max = 1

                                rsnapshot_run_times = 0

                                while True:

                                    retcode = run_cmd("{rsnapshot_prefix_cmd}rsnapshot -c {conf} sync 2> >({rsnapshot_error_filter})".format(
                                        rsnapshot_prefix_cmd=rsnapshot_prefix_cmd,
                                        conf=RSNAPSHOT_CONF,
                                        rsnapshot_error_filter=rsnapshot_error_filter
                                    ))
                                    rsnapshot_run_times += 1

                                    if retcode == 0 or retcode == 2:
                                        break

                                    if rsnapshot_run_times >= times_to_run_max:
                                        break
                                    
                                    log_and_print("NOTICE", "Rsnapshot retry {retry} on item number {number}".format(retry=rsnapshot_run_times, number=item["number"]), logger)

                                if retcode == 2:
                                    log_and_print("NOTICE", "Rsnapshot succeeded with WARNINGs on item number {number}, but we consider it is OK".format(number=item["number"]), logger)
                                elif retcode == 0:
                                    log_and_print("NOTICE", "Rsnapshot succeeded on item number {number}".format(number=item["number"]), logger)
                                else:
                                    log_and_print("ERROR", "Rsnapshot failed on item number {number}".format(number=item["number"]), logger)
                                    errors += 1
                            except Exception as e:
                                logger.exception(e)
                                raise Exception("Caught exception on subprocess.run execution")

                            # Exec exec_after_rsync
                            if "exec_after_rsync" in item:
                                log_and_print("NOTICE", "Executing remote exec_after_rsync on item number {number}".format(number=item["number"]), logger)
                                log_and_print("NOTICE", "{cmd}".format(cmd=item["exec_after_rsync"]), logger)
                                try:
                                    retcode = run_cmd("ssh {ssh_args} -p {port} {user}@{host} '{cmd}'".format(ssh_args=ssh_args, port=item["connect_port"], user=item["connect_user"], host=item["connect_host"], cmd=item["exec_after_rsync"]))
                                    if retcode == 0:
                                        log_and_print("NOTICE", "Remote execution of exec_after_rsync succeeded on item number {number}".format(number=item["number"]), logger)
                                    else:
                                        log_and_print("ERROR", "Remote execution of exec_after_rsync failed on item number {number}, but script continues".format(number=item["number"]), logger)
                                        errors += 1
                                except Exception as e:
                                    logger.exception(e)
                                    raise Exception("Caught exception on subprocess.run execution")

                        elif item["type"] in ["RSYNC_NATIVE"]:

                            if ":" in item["connect"]:
                                item["connect_host"] = item["connect"].split(":")[0]
                                item["connect_port"] = item["connect"].split(":")[1]
                            else:
                                item["connect_host"] = item["connect"]
                                item["connect_port"] = 873

                            # Check connect password
                            if "connect_password" not in item:
                                log_and_print("ERROR", "No Rsync password provided for native rsync on item number {number}, not doing sync".format(number=item["number"]), logger)
                                errors += 1
                                continue

                            # Save connect password to file
                            with open(RSNAPSHOT_PASSWD, "w") as file_to_write:
                                file_to_write.write(item["connect_password"])
                            os.chmod(RSNAPSHOT_PASSWD, 0o600)
                            
                            # Check remote .backup existance, if no file - skip to next. Remote windows rsync server can give empty set in some cases, which can lead to backup to be erased.
                            # --timeout=900 - if no IO for 15 minutes, rsync will exit
                            if item["native_txt_check"]:
                                log_and_print("NOTICE", "Remote .backup existance check required on item number {number}".format(number=item["number"]), logger)
                                try:
                                    retcode = run_cmd("rsync --timeout=900 --password-file={passwd} rsync://{user}@{host}:{port}{source}/ | grep .backup".format(
                                        passwd=RSNAPSHOT_PASSWD,
                                        user=item["connect_user"],
                                        host=item["connect_host"],
                                        port=item["connect_port"],
                                        source=item["source"]
                                    ))
                                    if retcode == 0:
                                        log_and_print("NOTICE", "Remote .backup existance check succeeded on item number {number}".format(number=item["number"]), logger)
                                    else:
                                        log_and_print("ERROR", "Remote .backup existance check failed on item number {number}, not doing sync".format(number=item["number"]), logger)
                                        errors += 1
                                        continue
                                except Exception as e:
                                    logger.exception(e)
                                    raise Exception("Caught exception on subprocess.run execution")

                            # Save config
                            with open(RSNAPSHOT_CONF, "w") as file_to_write:
                                file_to_write.write(textwrap.dedent(
                                    """\
                                    config_version	1.2
                                    snapshot_root	{snapshot_root}
                                    cmd_cp		/bin/cp
                                    cmd_rm		/bin/rm
                                    cmd_rsync	/usr/bin/rsync
                                    cmd_ssh		/usr/bin/ssh
                                    cmd_logger	/usr/bin/logger
                                    {retain_hourly_comment}retain		hourly	{retain_hourly}
                                    retain		daily	{retain_daily}
                                    retain		weekly	{retain_weekly}
                                    retain		monthly	{retain_monthly}
                                    verbose		{verbosity_level}
                                    loglevel	3
                                    logfile		/opt/sysadmws/rsnapshot_backup/rsnapshot.log
                                    lockfile	/opt/sysadmws/rsnapshot_backup/rsnapshot.pid
                                    rsync_long_args	-az --delete --delete-excluded --no-owner --no-group --numeric-ids --relative --timeout=900 --password-file={passwd} {rsync_verbosity_args} {rsync_args}
                                    sync_first	1
                                    backup		rsync://{user}@{host}:{port}{source}/		rsnapshot/
                                    """
                                ).format(
                                    snapshot_root=item["path"],
                                    retain_hourly_comment="" if "retain_hourly" in item else "#",
                                    retain_hourly=item["retain_hourly"] if "retain_hourly" in item else "NONE",
                                    retain_daily=item["retain_daily"],
                                    retain_weekly=item["retain_weekly"],
                                    retain_monthly=item["retain_monthly"],
                                    verbosity_level=item["verbosity_level"],
                                    passwd=RSNAPSHOT_PASSWD,
                                    rsync_verbosity_args=item["rsync_verbosity_args"],
                                    rsync_args=item["rsync_args"],
                                    user=item["connect_user"],
                                    host=item["connect_host"],
                                    port=item["connect_port"],
                                    source=item["source"]
                                ))

                            # Run rsnapshot
                            if "rsnapshot_prefix_cmd" in item:
                                rsnapshot_prefix_cmd = "{rsnapshot_prefix_cmd} ".format(rsnapshot_prefix_cmd=item["rsnapshot_prefix_cmd"])
                            else:
                                rsnapshot_prefix_cmd = ""
                            if item["native_10h_limit"]:
                                timeout_cmd = "timeout --preserve-status -k 60 10h "
                            else:
                                timeout_cmd = ""
                            log_and_print("NOTICE", "Running {timeout_cmd}{rsnapshot_prefix_cmd}rsnapshot -c {conf} sync on item number {number}".format(
                                timeout_cmd=timeout_cmd,
                                rsnapshot_prefix_cmd=rsnapshot_prefix_cmd,
                                conf=RSNAPSHOT_CONF,
                                number=item["number"]
                            ), logger)
                            try:

                                if "retries" in item:
                                    times_to_run_max = 1 + item["retries"]
                                else:
                                    times_to_run_max = 1

                                rsnapshot_run_times = 0

                                while True:

                                    retcode = run_cmd("{timeout_cmd}{rsnapshot_prefix_cmd}rsnapshot -c {conf} sync 2> >({rsnapshot_error_filter})".format(
                                        timeout_cmd=timeout_cmd,
                                        rsnapshot_prefix_cmd=rsnapshot_prefix_cmd,
                                        conf=RSNAPSHOT_CONF,
                                        rsnapshot_error_filter=rsnapshot_error_filter
                                    ))
                                    rsnapshot_run_times += 1

                                    if retcode == 0 or retcode == 2:
                                        break

                                    if rsnapshot_run_times >= times_to_run_max:
                                        break
                                    
                                    log_and_print("NOTICE", "Rsnapshot retry {retry} on item number {number}".format(retry=rsnapshot_run_times, number=item["number"]), logger)

                                if retcode == 2:
                                    log_and_print("NOTICE", "Rsnapshot succeeded with WARNINGs on item number {number}, but we consider it is OK".format(number=item["number"]), logger)
                                elif retcode == 0:
                                    log_and_print("NOTICE", "Rsnapshot succeeded on item number {number}".format(number=item["number"]), logger)
                                else:
                                    log_and_print("ERROR", "Rsnapshot failed on item number {number}".format(number=item["number"]), logger)
                                    errors += 1
                            except Exception as e:
                                logger.exception(e)
                                raise Exception("Caught exception on subprocess.run execution")
                            
                            # Delete password file
                            os.remove(RSNAPSHOT_PASSWD)
                        
                        else:
                            log_and_print("ERROR", "Unknown item type {type} on item number {number}".format(type=item["type"], number=item["number"]), logger)
                            errors += 1

                    # Check
                    if args.check and "checks" in item:

                        for check in item["checks"]:

                            # xtrabackup
                            if item["type"] == "MYSQL_SSH" and check["type"] == "MYSQL" and "mysql_dump_type" in item and item["mysql_dump_type"] == "xtrabackup":

                                if item["source"] == "ALL":
                                    dump_dir = "{path}/.sync/rsnapshot{db_dump_dir}/all.xtrabackup".format(path=item["path"], db_dump_dir=item["mysql_dump_dir"])
                                else:
                                    dump_dir = "{path}/.sync/rsnapshot{db_dump_dir}/{source}.xtrabackup".format(path=item["path"], db_dump_dir=item["mysql_dump_dir"], source=item["source"])

                                # Check dump dir exists
                                if os.path.isdir(dump_dir):

                                        log_and_print("NOTICE", "{dump_dir} dump dir exists on item number {number}".format(dump_dir=dump_dir, number=item["number"]), logger)
                                        oks += 1

                                        # Check ibdata1.qp at least 1 Mb
                                        ibdata1_file = "{dump_dir}/ibdata1.qp".format(dump_dir=dump_dir)
                                        if os.path.exists(ibdata1_file) and os.stat(ibdata1_file).st_size > 100000:
                                            log_and_print("NOTICE", "Found {ibdata1_file} file larger than 100 Kb in dump dir on item number {number}".format(ibdata1_file=ibdata1_file, number=item["number"]), logger)
                                            oks += 1
                                        else:
                                            log_and_print("ERROR", "Found no {ibdata1_file} file larger than 100 Kb in dump dir on item number {number}".format(ibdata1_file=ibdata1_file, number=item["number"]), logger)
                                            errors += 1

                                        # Read xtrabackup_info.qp
                                        xtrabackup_info_fie = "{dump_dir}/xtrabackup_info.qp".format(dump_dir=dump_dir)
                                        qpress_cmd = "qpress -do {xtrabackup_info_fie}".format(xtrabackup_info_fie=xtrabackup_info_fie)
                                        xtrabackup_end_time = None
                                        if os.path.exists(xtrabackup_info_fie):

                                            log_and_print("NOTICE", "Found {xtrabackup_info_fie} file in dump dir on item number {number}".format(xtrabackup_info_fie=xtrabackup_info_fie, number=item["number"]), logger)
                                            oks += 1

                                            try:

                                                retcode, stdout, stderr = run_cmd_pipe(qpress_cmd)
                                                if retcode == 0:

                                                    for xtrabackup_info_line in stdout.split("\n"):
                                                        if xtrabackup_info_line.lstrip().rstrip().split(" = ")[0] == "end_time":
                                                            xtrabackup_end_time = xtrabackup_info_line.lstrip().rstrip().split(" = ")[1]

                                                else:
                                                    log_and_print("ERROR", "qpress cmd failed on item number {number}".format(number=item["number"]), logger)
                                                    errors += 1

                                            except Exception as e:
                                                logger.exception(e)
                                                raise Exception("Caught exception on subprocess.run execution")

                                        else:
                                            log_and_print("NOTICE", "Found no {xtrabackup_info_fie} file in dump dir on item number {number}".format(xtrabackup_info_fie=xtrabackup_info_fie, number=item["number"]), logger)
                                            errors += 1

                                        # Check xtrabackup end_time
                                        if xtrabackup_end_time is not None:
                                            seconds_between_end_time_and_now = (datetime.now() - datetime.strptime(xtrabackup_end_time, "%Y-%m-%d %H:%M:%S")).total_seconds()
                                            # Dump files shouldn't be older than 1 day
                                            if seconds_between_end_time_and_now < 60*60*24:
                                                log_and_print("NOTICE", "Dump xtrabackup end_time signature age {seconds} secs is less than 1d for the dump dir {dump_dir} on item number {number}".format(seconds=int(seconds_between_end_time_and_now), dump_dir=dump_dir, number=item["number"]), logger)
                                                oks += 1
                                            else:
                                                log_and_print("ERROR", "Dump xtrabackup end_time signature age {seconds} secs is more than 1d for the dump dir {dump_dir} on item number {number}".format(seconds=int(seconds_between_end_time_and_now), dump_dir=dump_dir, number=item["number"]), logger)
                                                errors += 1
                                        else:
                                            log_and_print("ERROR", "There is no xtrabackup end_time signature in file {xtrabackup_info_fie} on item number {number}".format(xtrabackup_info_fie=xtrabackup_info_fie, number=item["number"]), logger)
                                            errors += 1

                                else:
                                    log_and_print("ERROR", "{dump_dir} dump dir is missing on item number {number}".format(dump_dir=dump_dir, number=item["number"]), logger)
                                    errors += 1

                            # mysqlsh
                            if item["type"] == "MYSQL_SSH" and check["type"] == "MYSQL" and "mysql_dump_type" in item and item["mysql_dump_type"] == "mysqlsh":

                                if item["source"] == "ALL":
                                    dump_dir = "{path}/.sync/rsnapshot{db_dump_dir}/all.mysqlsh".format(path=item["path"], db_dump_dir=item["mysql_dump_dir"])
                                else:
                                    dump_dir = "{path}/.sync/rsnapshot{db_dump_dir}/{source}.mysqlsh".format(path=item["path"], db_dump_dir=item["mysql_dump_dir"], source=item["source"])

                                # Check dump dir exists
                                if os.path.isdir(dump_dir):

                                        log_and_print("NOTICE", "{dump_dir} dump dir exists on item number {number}".format(dump_dir=dump_dir, number=item["number"]), logger)
                                        oks += 1

                                        # Read @.done.json
                                        mysqlsh_info_fie = "{dump_dir}/@.done.json".format(dump_dir=dump_dir)
                                        cat_json_cmd = "cat {mysqlsh_info_fie} | grep -e '.end.:'".format(mysqlsh_info_fie=mysqlsh_info_fie)
                                        mysqlsh_end_time = None
                                        if os.path.exists(mysqlsh_info_fie):

                                            log_and_print("NOTICE", "Found {mysqlsh_info_fie} file in dump dir on item number {number}".format(mysqlsh_info_fie=mysqlsh_info_fie, number=item["number"]), logger)
                                            oks += 1

                                            try:

                                                retcode, stdout, stderr = run_cmd_pipe(cat_json_cmd)
                                                if retcode == 0:

                                                    for mysqlsh_info_line in stdout.split("\n"):
                                                        if '"end":' in mysqlsh_info_line.lstrip().rstrip():
                                                            mysqlsh_end_time = mysqlsh_info_line.lstrip().rstrip().replace('"end": "', "").replace('",', "")

                                                else:
                                                    log_and_print("ERROR", "cat cmd failed on item number {number}".format(number=item["number"]), logger)
                                                    errors += 1

                                            except Exception as e:
                                                logger.exception(e)
                                                raise Exception("Caught exception on subprocess.run execution")

                                        else:
                                            log_and_print("NOTICE", "Found no {mysqlsh_info_fie} file in dump dir on item number {number}".format(mysqlsh_info_fie=mysqlsh_info_fie, number=item["number"]), logger)
                                            errors += 1

                                        # Check mysqlsh end time
                                        if mysqlsh_end_time is not None:
                                            seconds_between_end_time_and_now = (datetime.now() - datetime.strptime(mysqlsh_end_time, "%Y-%m-%d %H:%M:%S")).total_seconds()
                                            # Dump files shouldn't be older than 1 day
                                            if seconds_between_end_time_and_now < 60*60*24:
                                                log_and_print("NOTICE", "Dump @.done.json end time signature age {seconds} secs is less than 1d for the dump dir {dump_dir} on item number {number}".format(seconds=int(seconds_between_end_time_and_now), dump_dir=dump_dir, number=item["number"]), logger)
                                                oks += 1
                                            else:
                                                log_and_print("ERROR", "Dump @.done.json end time signature age {seconds} secs is more than 1d for the dump dir {dump_dir} on item number {number}".format(seconds=int(seconds_between_end_time_and_now), dump_dir=dump_dir, number=item["number"]), logger)
                                                errors += 1
                                        else:
                                            log_and_print("ERROR", "There is no @.done.json end time signature in file {mysqlsh_info_fie} on item number {number}".format(mysqlsh_info_fie=mysqlsh_info_fie, number=item["number"]), logger)
                                            errors += 1

                                else:
                                    log_and_print("ERROR", "{dump_dir} dump dir is missing on item number {number}".format(dump_dir=dump_dir, number=item["number"]), logger)
                                    errors += 1

                            # Native DB dumps have similiar logic
                            if (
                                    (item["type"] == "MYSQL_SSH" and check["type"] == "MYSQL" and not ("mysql_dump_type" in item and (item["mysql_dump_type"] == "xtrabackup" or item["mysql_dump_type"] == "mysqlsh")))
                                    or
                                    (item["type"] == "POSTGRESQL_SSH" and check["type"] == "POSTGRESQL")
                                    or
                                    (item["type"] == "MONGODB_SSH" and check["type"] == "MONGODB")
                                ):

                                sources_to_check = []

                                if check["type"] == "MYSQL":
                                    db_dump_dir = item["mysql_dump_dir"]
                                    db_dump_ext = "gz"
                                elif check["type"] == "POSTGRESQL":
                                    db_dump_dir = item["postgresql_dump_dir"]
                                    db_dump_ext = "gz"
                                elif check["type"] == "MONGODB":
                                    db_dump_dir = item["mongodb_dump_dir"]
                                    db_dump_ext = "tar.gz"

                                if item["source"] == "ALL":

                                    db_list_file_path = "{path}/.sync/rsnapshot{db_dump_dir}/db_list.txt".format(path=item["path"], db_dump_dir=db_dump_dir)

                                    if os.path.exists(db_list_file_path):
                                        with open(db_list_file_path, "r") as db_list_file:
                                            while True:
                                                db_list_file_line = db_list_file.readline().rstrip()
                                                if not db_list_file_line:
                                                    break
                                                if "empty_db" in check:
                                                    if db_list_file_line not in check["empty_db"]:
                                                        sources_to_check.append(db_list_file_line)
                                                else:
                                                    sources_to_check.append(db_list_file_line)
                                    else:
                                        log_and_print("ERROR", "{db_list_file_path} file is missing on item number {number}".format(db_list_file_path=db_list_file_path, number=item["number"]), logger)
                                        errors += 1

                                else:
                                    sources_to_check.append(item["source"])
                                
                                # Check sources
                                for source in sources_to_check:

                                    dump_file = "{path}/.sync/rsnapshot{db_dump_dir}/{source}.{db_dump_ext}".format(path=item["path"], db_dump_dir=db_dump_dir, source=source, db_dump_ext=db_dump_ext)

                                    # Check dump file exists
                                    if os.path.exists(dump_file):

                                        log_and_print("NOTICE", "{dump_file} dump file exists on item number {number}".format(dump_file=dump_file, number=item["number"]), logger)
                                        oks += 1

                                        # With MYSQL and POSTGRESQL we read dump files
                                        if check["type"] in ["MYSQL", "POSTGRESQL"]:

                                            dump_file_lines_number = 0
                                            dump_file_inserts = 0
                                            dump_completed_date = None
                                            with gzip.open(dump_file, "r") as dump_file_file:
                                                while True:
                                                    dump_file_lines_number += 1
                                                    dump_file_line = dump_file_file.readline()
                                                    if not dump_file_line:
                                                        log_and_print("NOTICE", "Read {dump_file_lines_number} lines in dump file {dump_file} on item number {number}".format(dump_file_lines_number=dump_file_lines_number, dump_file=dump_file, number=item["number"]), logger)
                                                        break
                                                    if check["type"] == "MYSQL" and re.match("^INSERT INTO", dump_file_line.decode(errors="ignore")):
                                                        dump_file_inserts += 1
                                                    elif check["type"] == "POSTGRESQL" and re.match("^COPY.*FROM stdin", dump_file_line.decode(errors="ignore")):
                                                        dump_file_inserts += 1
                                                    elif check["type"] == "MYSQL" and re.match("^-- Dump completed on", dump_file_line.decode(errors="ignore")):
                                                        re_match = re.match("^-- Dump completed on (.+)$", dump_file_line.decode(errors="ignore"))
                                                        if re_match:
                                                            dump_completed_date = re_match.group(1)
                                                    elif check["type"] == "POSTGRESQL" and re.match("^-- Completed on", dump_file_line.decode(errors="ignore")):
                                                        re_match = re.match("^-- Completed on (.+)$", dump_file_line.decode(errors="ignore"))
                                                        if re_match:
                                                            dump_completed_date = re_match.group(1)

                                            # Check dump inserts
                                            if dump_file_inserts > 0:
                                                log_and_print("NOTICE", "Found {dump_file_inserts} inserts in dump file {dump_file} on item number {number}".format(dump_file_inserts=dump_file_inserts, dump_file=dump_file, number=item["number"]), logger)
                                                oks += 1
                                            else:
                                                log_and_print("ERROR", "Found 0 inserts in dump file {dump_file} on item number {number}".format(dump_file=dump_file, number=item["number"]), logger)
                                                errors += 1

                                            # Check dump completed date
                                            if dump_completed_date is not None:
                                                if check["type"] == "MYSQL":
                                                    seconds_between_dump_completed_date_and_now = (datetime.now() - datetime.strptime(dump_completed_date, "%Y-%m-%d %H:%M:%S")).total_seconds()
                                                elif check["type"] == "POSTGRESQL":
                                                    seconds_between_dump_completed_date_and_now = (datetime.now() - datetime.strptime(dump_completed_date, "%Y-%m-%d %H:%M:%S %Z")).total_seconds()
                                                # Dump files shouldn't be older than 1 day
                                                if seconds_between_dump_completed_date_and_now < 60*60*24:
                                                    log_and_print("NOTICE", "Dump completion signature age {seconds} secs is less than 1d for the dump file {dump_file} on item number {number}".format(seconds=int(seconds_between_dump_completed_date_and_now), dump_file=dump_file, number=item["number"]), logger)
                                                    oks += 1
                                                else:
                                                    log_and_print("ERROR", "Dump completion signature age {seconds} secs is more than 1d for the dump file {dump_file} on item number {number}".format(seconds=int(seconds_between_dump_completed_date_and_now), dump_file=dump_file, number=item["number"]), logger)
                                                    errors += 1
                                            else:
                                                log_and_print("ERROR", "There is no dump completion signature in dump file {dump_file} on item number {number}".format(dump_file_inserts=dump_file_inserts, dump_file=dump_file, number=item["number"]), logger)
                                                errors += 1

                                        # With MONGODB we read tar archive
                                        elif check["type"] in ["MONGODB"]:

                                            tarfile_bsons_number = 0
                                            tarfile_non_zero_sized_bson_date = None
                                            tarfile_non_zero_sized_bsons_number = 0
                                            with tarfile.open(dump_file, "r") as dump_file_file:
                                                for tarfile_member in dump_file_file.getmembers():
                                                    if "bson" in tarfile_member.name:
                                                        tarfile_bsons_number += 1
                                                        if tarfile_member.size > 0:
                                                            tarfile_non_zero_sized_bsons_number += 1
                                                            tarfile_non_zero_sized_bson_date = datetime.fromtimestamp(tarfile_member.mtime)
                                            log_and_print("NOTICE", "Found {tarfile_bsons_number} bsons in dump file {dump_file} on item number {number}".format(tarfile_bsons_number=tarfile_bsons_number, dump_file=dump_file, number=item["number"]), logger)

                                            # Check non zero sized bsons
                                            if tarfile_non_zero_sized_bsons_number > 0:
                                                log_and_print("NOTICE", "Found {tarfile_non_zero_sized_bsons_number} non zero sized bsons in dump file {dump_file} on item number {number}".format(tarfile_non_zero_sized_bsons_number=tarfile_non_zero_sized_bsons_number, dump_file=dump_file, number=item["number"]), logger)
                                                oks += 1
                                            else:
                                                log_and_print("ERROR", "Found 0 non zero sized bsons in dump file {dump_file} on item number {number}".format(dump_file=dump_file, number=item["number"]), logger)
                                                errors += 1

                                            # Check dump completed date
                                            if tarfile_non_zero_sized_bson_date is not None:
                                                seconds_between_tarfile_non_zero_sized_bson_date_and_now = (datetime.now() - tarfile_non_zero_sized_bson_date).total_seconds()
                                                # Dump files shouldn't be older than 1 day
                                                if seconds_between_tarfile_non_zero_sized_bson_date_and_now < 60*60*24:
                                                    log_and_print("NOTICE", "Dump bsons age {seconds} secs is less than 1d for the dump file {dump_file} on item number {number}".format(seconds=int(seconds_between_tarfile_non_zero_sized_bson_date_and_now), dump_file=dump_file, number=item["number"]), logger)
                                                    oks += 1
                                                else:
                                                    log_and_print("ERROR", "Dump bsons age {seconds} secs is more than 1d for the dump file {dump_file} on item number {number}".format(seconds=int(seconds_between_tarfile_non_zero_sized_bson_date_and_now), dump_file=dump_file, number=item["number"]), logger)
                                                    errors += 1

                                    else:
                                        log_and_print("ERROR", "{dump_file} dump file is missing on item number {number}".format(dump_file=dump_file, number=item["number"]), logger)
                                        errors += 1

                            # .backup and FILE_AGE
                            if item["type"] in ["RSYNC_SSH", "RSYNC_NATIVE"]:

                                sources_to_check = []

                                # Expand paths to check for RSYNC_SSH
                                if item["type"] == "RSYNC_SSH":

                                    if item["source"] in DATA_EXPAND:
                                        for source in DATA_EXPAND[item["source"]]:
                                            if not ("exclude" in item and source in item["exclude"]):
                                                sources_to_check.append(source)
                                    else:
                                        sources_to_check.append(item["source"])

                                # For RSYNC_NATIVE we need to strip first dir path (share name) from source
                                if item["type"] == "RSYNC_NATIVE":
                                    sources_to_check.append("/{path}".format(path="/".join(item["source"].split("/")[2:])))

                                # Check sources
                                for source in sources_to_check:

                                    # FILE_AGE
                                    if check["type"] == "FILE_AGE":

                                        find_cmd = "find {item_path}/.sync/rsnapshot{source} -type f -regex '.*/{mask}'".format(item_path=item["path"], source=source, mask=check["files_mask"])
                                        log_and_print("NOTICE", "find cmd: {find_cmd} on item number {number}".format(find_cmd=find_cmd, number=item["number"]), logger)

                                        try:
                                            retcode, stdout, stderr = run_cmd_pipe(find_cmd)
                                            if retcode == 0:

                                                # Process find results

                                                file_list = stdout
                                                file_list_file_count = 0
                                                file_list_last_file_timestamp = 0
                                                file_list_last_file_datetime = None
                                                file_list_last_file = None

                                                for file_list_file in file_list.split("\n"):
                                                    if len(file_list_file) > 0:
                                                        file_list_file_count += 1

                                                        # Find last file
                                                        file_list_file_timestamp = os.path.getmtime(file_list_file)
                                                        if file_list_file_timestamp > file_list_last_file_timestamp:
                                                            file_list_last_file_timestamp = file_list_file_timestamp
                                                            file_list_last_file_datetime = datetime.fromtimestamp(file_list_file_timestamp)
                                                            file_list_last_file = file_list_file

                                                        # Check min_file_size
                                                        file_list_file_size = os.stat(file_list_file).st_size
                                                        if file_list_file_size >= check["min_file_size"]:
                                                            log_and_print("NOTICE", "File {file_count} {file_list_file} size {size} is not less than needed {min_file_size} on item number {number}".format(file_count=file_list_file_count, size=file_list_file_size, file_list_file=file_list_file, min_file_size=check["min_file_size"], number=item["number"]), logger)
                                                            oks += 1
                                                        else:
                                                            log_and_print("ERROR", "File {file_count} {file_list_file} size {size} is less than needed {min_file_size} on item number {number}".format(file_count=file_list_file_count, size=file_list_file_size, file_list_file=file_list_file, min_file_size=check["min_file_size"], number=item["number"]), logger)
                                                            errors += 1

                                                        # Check file_type
                                                        try:
                                                            ft_retcode, ft_stdout, ft_stderr = run_cmd_pipe("file -b '{file_list_file}'".format(file_list_file=file_list_file))
                                                            if ft_retcode == 0:
                                                                file_type_received = ft_stdout.lstrip().rstrip()
                                                                if re.match(check["file_type"], file_type_received):
                                                                    log_and_print("NOTICE", "File {file_count} {file_list_file} type {file_type_received} matched needed {check_file_type} on item number {number}".format(file_count=file_list_file_count, file_list_file=file_list_file, file_type_received=file_type_received, check_file_type=check["file_type"], number=item["number"]), logger)
                                                                    oks += 1
                                                                else:
                                                                    log_and_print("ERROR", "File {file_count} {file_list_file} type {file_type_received} mismatched needed {check_file_type} on item number {number}".format(file_count=file_list_file_count, file_list_file=file_list_file, file_type_received=file_type_received, check_file_type=check["file_type"], number=item["number"]), logger)
                                                                    errors += 1
                                                            else:
                                                                log_and_print("ERROR", "Getting file {file_list_file} type failed on item number {number}".format(file_list_file=file_list_file, number=item["number"]), logger)
                                                                errors += 1
                                                        except Exception as e:
                                                            logger.exception(e)
                                                            raise Exception("Caught exception on subprocess.run execution")

                                                # Check files_total
                                                if file_list_file_count >= check["files_total"]:
                                                    log_and_print("NOTICE", "Found {file_list_file_count} of needed {files_total} files on item number {number}".format(file_list_file_count=file_list_file_count, files_total=check["files_total"], number=item["number"]), logger)
                                                    oks += 1
                                                else:
                                                    log_and_print("ERROR", "Found {file_list_file_count} of needed {files_total} files on item number {number}".format(file_list_file_count=file_list_file_count, files_total=check["files_total"], number=item["number"]), logger)
                                                    errors += 1

                                                # Check files_total_max, this check is optional
                                                if "files_total_max" in check:
                                                    if file_list_file_count <= check["files_total_max"]:
                                                        log_and_print("NOTICE", "Found {file_list_file_count} of max {files_total_max} files on item number {number}".format(file_list_file_count=file_list_file_count, files_total_max=check["files_total_max"], number=item["number"]), logger)
                                                        oks += 1
                                                    else:
                                                        log_and_print("ERROR", "Found {file_list_file_count} of max {files_total_max} files on item number {number}".format(file_list_file_count=file_list_file_count, files_total_max=check["files_total_max"], number=item["number"]), logger)
                                                        errors += 1

                                                # Check last_file_age
                                                if file_list_file_count > 0:
                                                    seconds_between_file_list_last_file_datetime_and_now = (datetime.now() - file_list_last_file_datetime).total_seconds()
                                                    if seconds_between_file_list_last_file_datetime_and_now < check["last_file_age"]*60*60*24:
                                                        log_and_print("NOTICE", "Last file {file_list_last_file} date {date} is not older than allowed {last_file_age} days old on item number {number}".format(file_list_last_file=file_list_last_file, date=file_list_last_file_datetime, last_file_age=check["last_file_age"], number=item["number"]), logger)
                                                        oks += 1
                                                    else:
                                                        log_and_print("ERROR", "Last file {file_list_last_file} date {date} is older than allowed {last_file_age} days old on item number {number}".format(file_list_last_file=file_list_last_file, date=file_list_last_file_datetime, last_file_age=check["last_file_age"], number=item["number"]), logger)
                                                        errors += 1

                                            else:
                                                log_and_print("ERROR", "find cmd failed on item number {number}".format(number=item["number"]), logger)
                                                errors += 1

                                        except Exception as e:
                                            logger.exception(e)
                                            raise Exception("Caught exception on subprocess.run execution")

                                    # .backup
                                    if check["type"] in [".backup", "s3/.backup"]:

                                        # Construct path
                                        check_file = "{item_path}/.sync/rsnapshot{source}/.backup".format(item_path=item["path"], source=source)

                                        # Check check file existance
                                        if os.path.exists(check_file):

                                            log_and_print("NOTICE", ".backup file exists on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                            oks += 1

                                            # Gather check file data
                                            check_file_dict = {}
                                            with open(check_file, "r") as check_file_file:
                                                while True:
                                                    check_file_line = check_file_file.readline().rstrip()
                                                    if not check_file_line:
                                                        break
                                                    check_file_line_key = check_file_line.split(": ")[0]
                                                    check_file_line_val = check_file_line.split(": ")[1]
                                                    check_file_dict[check_file_line_key] = check_file_line_val

                                            if check["type"] == ".backup":

                                                # Check file Host
                                                if "Host" in check_file_dict:
                                                    if check_file_dict["Host"].lower() == item["host"].lower():
                                                        log_and_print("NOTICE", ".backup file host {file_host} matched {item_host} on item number {number}: {check_file}".format(file_host=check_file_dict["Host"], item_host=item["host"], number=item["number"], check_file=check_file), logger)
                                                        oks += 1
                                                    else:
                                                        log_and_print("ERROR", ".backup file host {file_host} mismatched {item_host} on item number {number}: {check_file}".format(file_host=check_file_dict["Host"], item_host=item["host"], number=item["number"], check_file=check_file), logger)
                                                        errors += 1
                                                else:
                                                    log_and_print("ERROR", ".backup file doesn't contain Host on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                                    errors += 1

                                                # Check file Path
                                                if "Path" in check_file_dict:

                                                    # Path could be defined in check
                                                    if "path" in check:
                                                        path_to_check = check["path"]
                                                    else:
                                                        path_to_check = source

                                                    if check_file_dict["Path"] == path_to_check:
                                                        log_and_print("NOTICE", ".backup file path {file_path} matched {item_path} on item number {number}: {check_file}".format(file_path=check_file_dict["Path"], item_path=path_to_check, number=item["number"], check_file=check_file), logger)
                                                        oks += 1
                                                    else:
                                                        log_and_print("ERROR", ".backup file path {file_path} mismatched {item_path} on item number {number}: {check_file}".format(file_path=check_file_dict["Path"], item_path=path_to_check, number=item["number"], check_file=check_file), logger)
                                                        errors += 1
                                                else:
                                                    log_and_print("ERROR", ".backup file doesn't contain Path on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                                    errors += 1

                                            elif check["type"] == "s3/.backup":

                                                # Check file Bucket
                                                if "Bucket" in check_file_dict:
                                                    if check_file_dict["Bucket"] == check["s3_bucket"]:
                                                        log_and_print("NOTICE", ".backup file bucket {file_bucket} matched s3 {check_bucket} on item number {number}: {check_file}".format(file_bucket=check_file_dict["Bucket"], check_bucket=check["s3_bucket"], number=item["number"], check_file=check_file), logger)
                                                        oks += 1
                                                    else:
                                                        log_and_print("ERROR", ".backup file bucket {file_bucket} mismatched s3 {check_bucket} on item number {number}: {check_file}".format(file_bucket=check_file_dict["Bucket"], check_bucket=check["s3_bucket"], number=item["number"], check_file=check_file), logger)
                                                        errors += 1
                                                else:
                                                    log_and_print("ERROR", ".backup file doesn't contain Bucket on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                                    errors += 1

                                                # Check file Path
                                                if "Path" in check_file_dict:

                                                    if check_file_dict["Path"] == check["s3_path"]:
                                                        log_and_print("NOTICE", ".backup file path {file_path} matched s3 {check_path} on item number {number}: {check_file}".format(file_path=check_file_dict["Path"], check_path=check["s3_path"], number=item["number"], check_file=check_file), logger)
                                                        oks += 1
                                                    else:
                                                        log_and_print("ERROR", ".backup file path {file_path} mismatched s3 {check_path} on item number {number}: {check_file}".format(file_path=check_file_dict["Path"], check_path=check["s3_path"], number=item["number"], check_file=check_file), logger)
                                                        errors += 1
                                                else:
                                                    log_and_print("ERROR", ".backup file doesn't contain Path on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                                    errors += 1

                                            # Check file UTC 
                                            if "UTC" in check_file_dict:
                                                seconds_between_check_file_utc_and_now = (datetime.now() - datetime.strptime(check_file_dict["UTC"], "%Y-%m-%d %H:%M:%S")).total_seconds()
                                                # .backups files shouldn't be older than 1 day
                                                if seconds_between_check_file_utc_and_now < 60*60*24:
                                                    log_and_print("NOTICE", ".backup file date age {seconds} secs is less than 1d on item number {number}: {check_file}".format(seconds=int(seconds_between_check_file_utc_and_now), number=item["number"], check_file=check_file), logger)
                                                    oks += 1
                                                else:
                                                    log_and_print("ERROR", ".backup file date age {seconds} secs is more than 1d on item number {number}: {check_file}".format(seconds=int(seconds_between_check_file_utc_and_now), number=item["number"], check_file=check_file), logger)
                                                    errors += 1
                                            else:
                                                log_and_print("ERROR", ".backup file doesn't contain UTC on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                                errors += 1
                                            
                                            # Check file backup hosts to find self
                                            if "Backup 1 Host" in check_file_dict and "Backup 1 Path" in check_file_dict:
                                                check_file_backup_item = 1
                                                backup_host_found = False
                                                backup_host_path_found = False
                                                while True:
                                                    if "Backup {n} Host".format(n=check_file_backup_item) in check_file_dict and "Backup {n} Path".format(n=check_file_backup_item) in check_file_dict:
                                                        if check_file_dict["Backup {n} Host".format(n=check_file_backup_item)] == SELF_HOSTNAME:
                                                            backup_host_found = True
                                                            if check_file_dict["Backup {n} Path".format(n=check_file_backup_item)] == item["path"]:
                                                                backup_host_path_found = True
                                                        check_file_backup_item += 1
                                                    else:
                                                        break
                                                if backup_host_found and backup_host_path_found:
                                                    log_and_print("NOTICE", ".backup file backup host {host} and path {path} are found on item number {number}: {check_file}".format(host=SELF_HOSTNAME, path=item["path"], number=item["number"], check_file=check_file), logger)
                                                    oks += 1
                                                else:
                                                    log_and_print("ERROR", ".backup file backup host {host} and path {path} are not found on item number {number}: {check_file}".format(host=SELF_HOSTNAME, path=item["path"], number=item["number"], check_file=check_file), logger)
                                                    errors += 1
                                            else:
                                                log_and_print("ERROR", ".backup file doesn't contain at least one backup host/path on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                                errors += 1

                                        else:
                                            log_and_print("ERROR", ".backup file is missing on item number {number}: {check_file}".format(number=item["number"], check_file=check_file), logger)
                                            errors += 1

                except Exception as e:
                    logger.error("Caught exception, but not interrupting")
                    logger.exception(e)
                    errors += 1

            # Exit with error if there were errors
            if errors > 0:
                # Show oks if --check
                if args.check:
                    log_and_print("ERROR", "{LOGO} on {hostname}, checks ok: {oks}, errors found: {errors}".format(LOGO=LOGO, hostname=SELF_HOSTNAME, oks=oks, errors=errors), logger)
                else:
                    log_and_print("ERROR", "{LOGO} on {hostname} errors found: {errors}".format(LOGO=LOGO, hostname=SELF_HOSTNAME, errors=errors), logger)
                raise Exception("There were errors")
            else:
                # Show oks if --check
                if args.check:
                    # errros == 0 and oks == 0 => not good
                    if oks == 0:
                        # Check items count in config, substract by 1 because of the "default" item
                        # Print ok if there are no items in config, but print error if there are items in config and zero checks were done
                        if len(config["items"]) - 1 == 0:
                            log_and_print("NOTICE", "{LOGO} on {hostname}, zero checks made, but it is ok for the empty config".format(LOGO=LOGO, hostname=SELF_HOSTNAME), logger)
                        else:
                            log_and_print("ERROR", "{LOGO} on {hostname}, checks ok: 0, errors found: 0, zero checks made".format(LOGO=LOGO, hostname=SELF_HOSTNAME), logger)
                            raise Exception("Zero checks made")
                    else:
                        log_and_print("NOTICE", "{LOGO} on {hostname}, checks ok: {oks}, finished OK".format(LOGO=LOGO, hostname=SELF_HOSTNAME, oks=oks), logger)
                else:
                    log_and_print("NOTICE", "{LOGO} on {hostname} finished OK".format(LOGO=LOGO, hostname=SELF_HOSTNAME), logger)

        finally:
            if not args.ignore_lock:
                lock.release()

    # Reroute catched exception to log
    except Exception as e:
        logger.exception(e)
        logger.info("Finished {LOGO} with errors".format(LOGO=LOGO))
        sys.exit(1)

    logger.info("Finished {LOGO}".format(LOGO=LOGO))
