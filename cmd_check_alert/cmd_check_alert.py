import sys
try:
    assert sys.version_info >= (3,5)
except AssertionError:
    # TODO: run command that would work on python lower than 3.5
    print("error, python version is lower than needed")
    sys.exit(1)

import os
import sys
import time
import json
import subprocess

# notify_devilry.py mandatory data
# '{"host": "'$HOSTNAME'", "from": "notify_devilry_test.sh", "type": "notify devilry test", "status": "OK"}'

force_send = False                                                            # send even if retcode if 0
local_default_timeout = 15


# some global variables
_hostname            = os.uname()[1]
_filename            = os.path.basename(__file__)
_type                = ""
_status_ok           = "OK"
_status_err          = "ERR"
_notify_devilry_path = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else '/opt/sysadmws/notify_devilry/notify_devilry.py'

curr_dir             = os.path.dirname(os.path.realpath(__file__))                     # current script directory absolute path
config_file          = curr_dir + "/" + _filename.split(".")[0] + ".conf.json"  # conf file name


def parse_config(filename):
    with open(filename,"r") as f:
        config = json.load(f)

    if config['enabled'] != True:
        print("Checks is disabled in config")
        sys.exit(0)

    flat_config = {}
    config_default_timeout = 0


    if config['cmd_checks']:
        if 'config' in config:
            config_default_timeout = config['config'].get('default_timeout', local_default_timeout)
    
        for check_name, check_content in config['cmd_checks'].items():
            timeout = check_content.get('timeout', config_default_timeout)
            check_cmd = check_content['cmd']
            flat_config.update({check_name: {'check_cmd': check_cmd, 'timeout': timeout}})
    else:
        print("error, checks in config is empty")
        sys.exit(1)
    return flat_config


def run_checks(checks_data):
    check_results = {}
    for check_name, check_content in checks_data.items():
        try:
            at = time.strftime("%c")
            process = subprocess.run(check_content['check_cmd'], 
                                     timeout=check_content['timeout'],
                                     shell=True,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        except subprocess.TimeoutExpired:
            check_results.update({
                    check_name: {
                        "check_cmd": check_content['check_cmd'],
                        "timeout": check_content['timeout'],
                        "at": at,
                        "status": "Operation timed out",
                        "retcode": "",
                        "stdout": "",
                        "stderr": ""
                    }
                }
            )
        else:
            check_results.update({
                    check_name: {
                        "check_cmd": process.args,
                        "at": at,
                        "status": _status_ok if process.returncode == 0 else _status_err,
                        "retcode": process.returncode,
                        "stdout": process.stdout.decode().strip(),
                        "stderr": process.stderr.decode().strip()
                    }
                }
            )
    return check_results


def send_check_results(notify_path, check_results):
    for name in check_results:
        if check_results[name]['retcode'] != 0 or force_send:
            check_result_list =  [('host', _hostname), 
                                          ('from', _filename),
                                          ('type', _type + name),
                                          ('at', check_results[name]['at']), 
                                          ('status', check_results[name]['status']), 
                                          ('timeout', check_results[name].get('timeout','')), 
                                          ('check_cmd', check_results[name]['check_cmd']),
                                          ('retcode', check_results[name]['retcode']),
                                          ('stdout', check_results[name]['stdout']),
                                          ('stderr', check_results[name]['stderr'])]
            stdin_dict = {}

            # clear empty values
            for kv in check_result_list:
                key, value = kv
                if value:
                    stdin_dict.update({key: value})

            stdin_data = json.dumps(stdin_dict,ensure_ascii=False).encode()
            subprocess.run(notify_path, input=stdin_data, shell=True)


if __name__ == "__main__":
    config = parse_config(config_file)
    resp = run_checks(config)
    send_check_results(_notify_devilry_path, resp)
    sys.exit(0)
