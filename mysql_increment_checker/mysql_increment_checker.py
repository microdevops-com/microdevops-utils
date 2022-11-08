#!/opt/sysadmws/misc/shebang_python_switcher.sh
import json
import yaml
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
    pwd = os.path.dirname(os.path.abspath(__file__))
    configfile = pwd + "/mysql_increment_checker.yaml"

    config = {"auto_increment_ratio": 70, "my_cred": "~/.my.cnf"}

    if os.path.exists(configfile):
        with open(configfile, "r") as f:
             config.update(yaml.safe_load(f))

    if not os.path.exists(os.path.expanduser(config["my_cred"])):
        _ = config.pop("my_cred")

    return config


def fetch_increment_status(config):
    query = """
            SELECT
              TABLE_SCHEMA,
              TABLE_NAME,
              ROUND(AUTO_INCREMENT / (
                CASE DATA_TYPE
                  WHEN 'tinyint' THEN 255
                  WHEN 'smallint' THEN 65535
                  WHEN 'mediumint' THEN 16777215
                  WHEN 'int' THEN 4294967295
                  WHEN 'bigint' THEN 18446744073709551615
                END >> IF(LOCATE('unsigned', COLUMN_TYPE) > 0, 0, 1)
              ) * 100) AS AUTO_INCREMENT_RATIO
            FROM
              INFORMATION_SCHEMA.COLUMNS
              INNER JOIN INFORMATION_SCHEMA.TABLES USING (TABLE_SCHEMA, TABLE_NAME)
            WHERE
              TABLE_SCHEMA NOT IN ('mysql', 'INFORMATION_SCHEMA', 'performance_schema')
              AND EXTRA='auto_increment'
              HAVING AUTO_INCREMENT_RATIO >= {}
            """

    warnings.filterwarnings("ignore", category=MySQLdb.Warning)
    try:
        con = MySQLdb.connect(read_default_file=config.get("my_cred", ""))
        cur = con.cursor(MySQLdb.cursors.DictCursor)
        cur.execute(query.format(config["auto_increment_ratio"]))
        status = cur.fetchall()
        con.close()
        return status
    except Exception as e:
        if len(e.args) > 1 and isinstance(e.args[0], int) and e.args[0] == 2002:
            sys.exit(0)
        else:
            raise

def process_status(status):
    _text = ""
    _max = 0

    if status:
        for entry in status:
            _text += entry["TABLE_SCHEMA"] + "." + entry["TABLE_NAME"] + ": " +  str(entry["AUTO_INCREMENT_RATIO"]) + "\n"
            if int(entry["AUTO_INCREMENT_RATIO"]) > _max:
                _max = int(entry["AUTO_INCREMENT_RATIO"])
        return {"text": _text, "max": _max}, False
    else:
        return {"text": _text, "max": _max}, True

def process_check(message, ok):

    hostname = socket.gethostname()
    response = {"service": "database", "resource": hostname + ":mysql-inc-field-usage"}

    if ok:
        response.update(
            {
                "severity": "ok",
                "event": "mysql_increment_checker_ok",
                "origin": "mysql_increment_checker.py",
                "text": "Mysql replication ok detected",
                "correlate": ["mysql_increment_checker_error"],
            }
        )
    else:
        response.update(
            {
                "severity": "critical",
                "service": "database",
                "event": "mysql_increment_checker_error",
                "origin": "mysql_increment_checker.py",
                "text": "Mysql replication error detected",
                "correlate": ["mysql_increment_checker_ok"],
            }
        )
    response.update({"value": message["max"],
                     "text": message["text"]})
    return response



if __name__ == "__main__":
    config = read_config()
    increment_status = fetch_increment_status(config)
    message, ok = process_status(increment_status)
    check = process_check(message, ok)
    p = subprocess.Popen(
        ["/opt/sysadmws/notify_devilry/notify_devilry.py"], stdin=subprocess.PIPE
    )
    p.communicate(input=json.dumps(check, ensure_ascii=False).encode())
