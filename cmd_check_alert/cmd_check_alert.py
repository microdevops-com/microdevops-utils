#!/opt/sysadmws/misc/shebang_python_switcher.sh
# -*- coding: utf-8 -*-

import sys
import os
import time
import subprocess
import yaml
import socket
import logging
from logging.handlers import RotatingFileHandler
try:
    import json
except ImportError:
    import simplejson as json
try:
    import argparse
    ARGPARSE = True
except ImportError:
    ARGPARSE = False
# subprocess.run python < 3.5 workaround
# https://stackoverflow.com/a/40590445
try:
    from subprocess import run
except ImportError:
    import subprocess
    def run(*popenargs, **kwargs):
        input = kwargs.pop("input", None)
        check = kwargs.pop("handle", False)

        if input is not None:
            if 'stdin' in kwargs:
                raise ValueError('stdin and input arguments may not both be used.')
            kwargs['stdin'] = subprocess.PIPE

        process = subprocess.Popen(*popenargs, **kwargs)
        try:
            stdout, stderr = process.communicate(input)
        except:
            process.kill()
            process.wait()
            raise
        retcode = process.poll()
        if check and retcode:
            raise subprocess.CalledProcessError(
                retcode, process.args, output=stdout, stderr=stderr)
        return retcode, stdout, stderr
import threading
import signal
import random
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

# Constants
WORK_DIR = "/opt/sysadmws/cmd_check_alert"
CONFIG_FILE = "cmd_check_alert.yaml"
LOG_DIR = "/opt/sysadmws/cmd_check_alert/log"
LOG_FILE = "cmd_check_alert.log"
LOGO = "✓ ➔ ✉"
NAME = "cmd_check_alert"
NOTIFY_DEVILRY_CMD = "/opt/sysadmws/notify_devilry/notify_devilry.py"
LOOP_SLEEP = 0.1
START_TIME = datetime.now()
FNULL = open(os.devnull, 'w')
SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SELF_SERVICE = "cmd_check_alert"
SELF_ORIGIN = "cmd_check_alert.py"

# Funcs

def send_notify_devilry(notify):
    notify_data = json.dumps(notify, ensure_ascii=False).encode()
    logger.info("Sending notify to notify_devilry: {notify}".format(notify=notify_data))
    run_cmd = NOTIFY_DEVILRY_CMD
    if args.force_send:
        run_cmd = run_cmd + " --force-send"
    run(run_cmd, input=notify_data, shell=True, stdout=FNULL)

# Load YAML config
def load_yaml_config(d, f):
    # Get in the env
    j2_env = Environment(loader=FileSystemLoader(d), trim_blocks=True)
    # Our config is a template
    template = j2_env.get_template(f)
    # Set vars inside config file and render
    current_date = datetime.now().strftime("%Y%m%d")
    current_time = datetime.now().strftime("%H%M%S")
    logger.info("Loading YAML config {0}/{1}".format(d, f))
    logger.info("current_date = {0}".format(current_date))
    logger.info("current_time = {0}".format(current_time))
    config = yaml.load(template.render(
        current_date = int(current_date),
        current_time = int(current_time)
    ), Loader=yaml.SafeLoader)
    return config

def suppress_oserror(f):
    def inner(*args, **kwargs):
        try:
            f(*args, **kwargs)
        except OSError as e:
            if e.errno == 2:
                pass
            else:
                raise
    return inner
RotatingFileHandler.doRollover = suppress_oserror(RotatingFileHandler.doRollover)
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
    if ARGPARSE:

        parser = argparse.ArgumentParser(description="Run check commands and send their alert notifications to notify_devilry.")
        parser.add_argument("--debug", dest="debug", help="enable debug", action="store_true")
        parser.add_argument("--force-send", dest="force_send", help="force sending to notify_devilry", action="store_true")
        parser.add_argument("--yaml", dest="yaml", help="use file FILE relative to {work_dir} instead of default {config}".format(work_dir=WORK_DIR, config=CONFIG_FILE), nargs=1, metavar=("FILE"))
        args = parser.parse_args()
    
        # Enable debug
        if args.debug:
            console_handler.setLevel(logging.DEBUG)

    else:

        # Always debug mode if no argparse
        console_handler.setLevel(logging.DEBUG)
    
    # Catch exception to logger
    try:
        logger.info(LOGO)

        # Load YAML config
        if args.yaml is not None:
            config_file = args.yaml[0]
        else:
            config_file = CONFIG_FILE
        config = load_yaml_config(WORK_DIR, config_file)

        # Check if enabled in config
        if config["enabled"] != True:
            logger.error("{name} not enabled in config, exiting".format(name=NAME))
            sys.exit(1)

        logger.info("Starting {name}".format(name=NAME))

        # Set SELF_HOSTNAME
        if "hostname_override" in config:
            SELF_HOSTNAME = config["hostname_override"]
        else:
            SELF_HOSTNAME = socket.gethostname()

        check_procs = {}
        check_threads = {}
        timedout_checks = {}
        resources_per_env_used = {}


        # Thread func to run check cmd
        # We cannot use subprocess.run - as we need to save process pid to global dict before communicate to kill it after timeout from another thread
        def run_check(name, cmd, check):
            logger.info("Running check {name} with command {cmd}".format(name=name, cmd=cmd))

            # custom PATH env for cases when cron runs with poor PATH
            check_env = os.environ.copy()
            check_env["PATH"] = "/usr/local/sbin:/usr/sbin:/sbin:/snap/bin:" + check_env["PATH"]

            # preexec_fn sets independent process group for check cmd children, all them could be killed together
            process = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable="/bin/bash", env=check_env)

            # Save process to global dict for further killing
            check_procs[name] = process

            # Communicate with process and get data from it
            try:
                stdout, stderr = process.communicate(None)
            except:
                process.kill()
                process.wait()
                raise
            retcode = process.poll()
            stdout = stdout.decode()
            stderr = stderr.decode()
            logger.info("Check retcode: {retcode}".format(retcode=retcode))
            logger.info("Check stdout:")
            logger.info(stdout)
            logger.info("Check stderr:")
            logger.info(stderr)
            
            # Prepare notify data
            notify = {}
            if retcode == 0:
                notify["severity"] = SEVERITY_OK
            else:
                # severity_per_retcode in check
                if "severity_per_retcode" in check and retcode in check["severity_per_retcode"]:
                    notify["severity"] = check["severity_per_retcode"][retcode]
                #  severity_per_retcode in check for str hack
                elif "severity_per_retcode" in check and str(retcode) in check["severity_per_retcode"]:
                    notify["severity"] = check["severity_per_retcode"][str(retcode)]
                # severity_per_retcode in defaults
                elif "severity_per_retcode" in config["defaults"] and retcode in config["defaults"]["severity_per_retcode"]:
                    notify["severity"] = config["defaults"]["severity_per_retcode"][retcode]
                # severity_per_retcode in defaults for str hack
                elif "severity_per_retcode" in config["defaults"] and str(retcode) in config["defaults"]["severity_per_retcode"]:
                    notify["severity"] = config["defaults"]["severity_per_retcode"][str(retcode)]
                # severity in check
                elif "severity" in check:
                    notify["severity"] = check["severity"]
                # severity in defaults
                elif "severity" in config["defaults"]:
                    notify["severity"] = config["defaults"]["severity"]
                # fallback to major severity in the end
                else:
                    notify["severity"] = SEVERITY_CRITICAL
            notify["resource"] = check["resource"].replace("__hostname__", SELF_HOSTNAME)
            if name in timedout_checks:
                notify["event"] = "cmd_check_alert_cmd_timeout"
                notify["correlate"] = ["cmd_check_alert_cmd_ok", "cmd_check_alert_cmd_retcode_not_zero"]
            else:
                if retcode == 0:
                    notify["event"] = "cmd_check_alert_cmd_ok"
                    notify["correlate"] = ["cmd_check_alert_cmd_retcode_not_zero", "cmd_check_alert_cmd_timeout"]
                else:
                    notify["event"] = "cmd_check_alert_cmd_retcode_not_zero"
                    notify["correlate"] = ["cmd_check_alert_cmd_ok", "cmd_check_alert_cmd_timeout"]
            notify["value"] = str(retcode)

            # override with in check
            if "group" in check:
                notify["group"] = check["group"]
            # default group
            elif "group" in config["defaults"]:
                notify["group"] = config["defaults"]["group"]
            else:
                notify["group"] = SELF_HOSTNAME

            notify["attributes"] = {}
            notify["attributes"]["check name"] = name
            notify["attributes"]["check cmd"] = check["cmd"]
            notify["attributes"]["check retcode"] = str(retcode)
            notify["attributes"]["check host"] = SELF_HOSTNAME
            if name in timedout_checks:
                notify["attributes"]["check killed after timeout"] = str(timedout_checks[name])
            notify["text"] = "stdout:\n{stdout}\nstderr:\n{stderr}".format(stdout=stdout, stderr=stderr)
            notify["origin"] = SELF_ORIGIN

            # default service
            if "service" in config["defaults"]:
                notify["service"] = config["defaults"]["service"]
            # override with in check
            if "service" in check:
                notify["service"] = check["service"]

            # default type
            if "type" in config["defaults"]:
                notify["type"] = config["defaults"]["type"]
            # override with in check
            if "type" in check:
                notify["type"] = check["type"]

            # default environment
            if "environment" in config["defaults"]:
                notify["environment"] = config["defaults"]["environment"]
            # override with in check
            if "environment" in check:
                notify["environment"] = check["environment"]

            # default client
            if "client" in config["defaults"]:
                notify["client"] = config["defaults"]["client"]
            # override with in check
            if "client" in check:
                notify["client"] = check["client"]

            # default location
            if "location" in config["defaults"]:
                notify["attributes"]["location"] = config["defaults"]["location"]
            # override with in check
            if "location" in check:
                notify["attributes"]["location"] = check["location"]

            # default description
            if "description" in config["defaults"]:
                notify["attributes"]["description"] = config["defaults"]["description"]
            # override with in check
            if "description" in check:
                notify["attributes"]["description"] = check["description"]

            # Send notify_devilry
            send_notify_devilry(notify)

        # Thread func to timeout main check thread
        def timeout_check(name, thread, timeout):
            # Check timeout
            thread.join(timeout)
            # Kill check process group
            if thread.is_alive():

                # Wait for main thread to save process to global dict
                while name not in check_procs:
                    time.sleep(LOOP_SLEEP)
                logger.info("Check {name} cmd process pid {pid} should be killed by timeout, sending SIGKILL".format(name=name, pid=check_procs[name].pid))
                
                # Save to timedout_checks
                timedout_checks[name] = timeout

                # Process can finish by itself between is_alive() and killpg(), this could lead to exception
                try:
                    os.killpg(check_procs[name].pid, signal.SIGKILL)
                except OSError:
                    logger.warning("Process died by itself before killpg()")
            
            # Loop until thread is dead after its process is killed
            while thread.is_alive():
                time.sleep(LOOP_SLEEP)
            # Pop thread from check_threads
            logger.info("Check {name} thread is not alive anymore".format(name=name))
            check_threads.pop(name)
        
        # Shuffle checks to avoid same checks to be killed by global time limit
        check_list = list(config["checks"].items())
        random.shuffle(check_list)

        time_limit_warning = False
        same_resources_warning = False

        # Loop over checks
        for check_name, check in check_list:

            # Any check could fail
            try:

                # Skip disabled checks
                if "disabled" in check and check["disabled"]:
                    logger.info("Check {name} did not run because it is disabled".format(name=check_name))
                    continue

                # Resource definition in checks should be unique per environment, otherwise check makes no sense and events overwrite each other, check this
                env_to_check = check["environment"] if "environment" in check else "__NO_ENV"
                if env_to_check not in resources_per_env_used:
                    resources_per_env_used[env_to_check] = []
                if check["resource"] in resources_per_env_used[env_to_check]:
                    logger.warning("Check {name} did not run because its environment/resource already used in other check".format(name=check_name))
                    same_resources_warning = True
                    continue
                else:
                    resources_per_env_used[env_to_check].append(check["resource"])

                # Wait until available thread slot
                logger.info("Thread limit usage: {used}/{max}, waiting for available slot".format(used=len(check_threads), max=config["limits"]["threads"]))
                # We are checking >= instead of == beacuse we can overcome thread limit in some race condition
                while len(check_threads) >= config["limits"]["threads"]:
                    time.sleep(LOOP_SLEEP)
                logger.info("Thread slot available, starting new thread")
                
                # Calc seconds left until total script time limit
                running_seconds = int((datetime.now() - START_TIME).total_seconds())
                seconds_left = config["limits"]["time"] - running_seconds

                # Run checks only if at least 1 second left
                if seconds_left >= 1:
                    
                    thread = threading.Thread(target=run_check, args=[check_name, check["cmd"], check])
                    thread.start()
                    check_threads[check_name] = thread

                    # Decide which timeout to use
                    check_timeout = check["timeout"] if "timeout" in check else config["defaults"]["timeout"]
                    logger.info("Check {name} timeout to use: {timeout}".format(name=check_name, timeout=check_timeout))
                    logger.info("Total script run time: {time}, time limit: {limit}, seconds left: {left}".format(time=running_seconds, limit=config["limits"]["time"], left=seconds_left))
                    
                    # Override timeout to use if seconds left is smaller
                    if check_timeout > seconds_left:
                        logger.info("Seconds left for total script run is less than check timeout, forcing timeout to {left}".format(left=seconds_left))
                        check_timeout = seconds_left

                    # Start thread to check timeout for the main thread
                    timeout_check_thread = threading.Thread(target=timeout_check, args=[check_name, thread, check_timeout])
                    timeout_check_thread.start()

                else:
                    
                    logger.warning("Check {name} did not run because time left to total time limit is less than 1 second".format(name=check_name))
                    time_limit_warning = True

            # Reroute catched exception to log
            except Exception as e:
                logger.exception(e)

        # Send time limit warning
        if time_limit_warning:
            
            # Prepare notify data
            notify = {}
            notify["severity"] = SEVERITY_WARNING
            notify["service"] = SELF_SERVICE
            notify["resource"] = SELF_HOSTNAME
            notify["event"] = "cmd_check_alert_time_limit_warning"
            notify["value"] = "not ok"
            notify["group"] = SELF_HOSTNAME
            notify["text"] = "Some cmd_check_alert checks on server {server} did not run because time left to total time limit is less than 1 second".format(server=SELF_HOSTNAME)
            notify["origin"] = SELF_ORIGIN
            notify["correlate"] = ["cmd_check_alert_time_limit_ok"]

        else:
            
            # Prepare notify data
            notify = {}
            notify["severity"] = SEVERITY_OK
            notify["service"] = SELF_SERVICE
            notify["resource"] = SELF_HOSTNAME
            notify["event"] = "cmd_check_alert_time_limit_ok"
            notify["value"] = "ok"
            notify["group"] = SELF_HOSTNAME
            notify["text"] = "All cmd_check_alert checks on server {server} run in time limit".format(server=SELF_HOSTNAME)
            notify["origin"] = SELF_ORIGIN
            notify["correlate"] = ["cmd_check_alert_time_limit_warning"]

        # Send notify_devilry
        send_notify_devilry(notify)

        # Send same resources warning
        if same_resources_warning:
            
            # Prepare notify data
            notify = {}
            notify["severity"] = SEVERITY_WARNING
            notify["service"] = SELF_SERVICE
            notify["resource"] = SELF_HOSTNAME
            notify["event"] = "cmd_check_alert_same_resources_warning"
            notify["value"] = "not ok"
            notify["group"] = SELF_HOSTNAME
            notify["text"] = "Some cmd_check_alert checks on server {server} did not run because they have same resource per environment and could overwrite events of each other".format(server=SELF_HOSTNAME)
            notify["origin"] = SELF_ORIGIN
            notify["correlate"] = ["cmd_check_alert_same_resources_ok"]

        else:
            
            # Prepare notify data
            notify = {}
            notify["severity"] = SEVERITY_OK
            notify["service"] = SELF_SERVICE
            notify["resource"] = SELF_HOSTNAME
            notify["event"] = "cmd_check_alert_same_resources_ok"
            notify["value"] = "ok"
            notify["group"] = SELF_HOSTNAME
            notify["text"] = "All cmd_check_alert checks on server {server} have unique resource per environment".format(server=SELF_HOSTNAME)
            notify["origin"] = SELF_ORIGIN
            notify["correlate"] = ["cmd_check_alert_same_resources_warning"]

        # Send notify_devilry
        send_notify_devilry(notify)

    # Reroute catched exception to log
    except Exception as e:
        logger.exception(e)

    logger.info("Finished {name}".format(name=NAME))
