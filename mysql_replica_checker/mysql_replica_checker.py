#!/opt/sysadmws/misc/shebang_python_switcher.sh
import json
import os
import socket
import subprocess
import sys
import warnings

try:
    import MySQLdb, MySQLdb.cursors
except:
    sys.exit(65)


def read_config():
    pwd = os.path.abspath(os.getcwd())
    configfile = pwd + "/mysql_replica_checker.conf"

    config = {"BEHIND_MASTER_THR": 30, "MY_CRED": "~/.my.cnf"}

    if os.path.exists(configfile):
        with open(configfile, "r") as f:
            text = f.read()

        for line in text.split("\n"):
            if not "=" in line or line.startswith("#"):
                continue
            try:
                pos = line.index("#")
                line = line[0:pos]
            except:
                pass
            k, v = line.strip().split("=")
            k, v = k.strip(), v.strip().replace('"', "").replace("'", "")
            if k == "BEHIND_MASTER_THR":
                v = int(v)
            if k == "MY_CRED":
                v = v.replace("--defaults-file=", "")
            config.update({k: v})

    if not os.path.exists(os.path.expanduser(config["MY_CRED"])):
        _ = config.pop("MY_CRED")

    return config


def fetch_mysql_status(config):
    warnings.filterwarnings("ignore", category = MySQLdb.Warning)
    try:
        con = MySQLdb.connect(read_default_file=config.get("MY_CRED", ""))
        cur = con.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("show slave status")
        status = cur.fetchall()
        con.close()
        return status
    except Exception as e:
        if len(e.args) > 1 and isinstance(e.args[0], int) and e.args[0] == 2002:
            sys.exit(0)
        else:
            raise


def check_slave(config, status_slave):

    errors = []
    message = {}

    status_ok = {
        "Last_IO_Errno": 0,
        "Last_IO_Error": "",
        "Last_SQL_Errno": 0,
        "Last_SQL_Error": "",
        "Slave_IO_Running": "Yes",
        "Slave_SQL_Running": "Yes",
    }

    status_ok["Seconds_Behind_Master"] = config.get("BEHIND_MASTER_THR")

    master_host = status_slave.get("Master_Host", None)
    try:
        message.update({"master": socket.gethostbyname(master_host)})
    except:
        message.update({"master": master_host})

    for key in status_ok.keys():

        # process Seconds_Behind_Master
        if key == "Seconds_Behind_Master":
            value = status_slave.get(key, None)
            sql_delay = status_slave.get("SQL_Delay", None)
            message.update({key.lower().replace("_", "-"): value})
            message.update({"sql-delay": sql_delay})
            if (
                value is not None
                and isinstance(value, int)
                and sql_delay is not None
                and isinstance(sql_delay, int)
            ):
                if not (0 <= value - sql_delay <= status_ok[key]):
                    errors.append(key.lower().replace("_", "-"))

        # process simple statuses
        else:
            value = status_slave.get(key, None)
            message.update({key.lower().replace("_", "-"): value})
            if not (value is not None and value == status_ok[key]):
                errors.append(key.lower().replace("_", "-"))

    # add channel-name value to message
    if "Channel_Name" in status_slave.keys():
        message.update({"channel-name": status_slave["Channel_Name"]})

    _m = message
    message = {"errors found in": " ".join(errors)}
    message.update(_m)
    return message, errors == []


def process_check(message, ok, single):

    hostname = socket.gethostname()
    response = {"service": "database"}
    if single:
        response.update({"resource": hostname + ":mysql"})
    else:
        response.update({"resource": hostname + ":mysql-slave-of-" + message["master"]})

    if ok:
        response.update(
            {
                "severity": "ok",
                "event": "mysql_replica_checker_ok",
                "origin": "mysql_replica_checker.sh",
                "text": "Mysql replication ok detected",
                "correlate": ["mysql_replica_checker_error"],
            }
        )
    else:
        response.update(
            {
                "severity": "critical",
                "service": "database",
                "event": "mysql_replica_checker_error",
                "origin": "mysql_replica_checker.sh",
                "text": "Mysql replication error detected",
                "correlate": ["mysql_replica_checker_ok"],
            }
        )
    response.update({"attributes": message})
    return response


if __name__ == "__main__":
    config = read_config()
    mysql_status = fetch_mysql_status(config)
    single = len(mysql_status) == 1

    for i in mysql_status:
        message, ok = check_slave(config, i)
        check = process_check(message, ok, single)
        p = subprocess.Popen(
            ["/opt/sysadmws/notify_devilry/notify_devilry.py"], stdin=subprocess.PIPE
        )
        p.communicate(input=json.dumps(check, ensure_ascii=False).encode())
