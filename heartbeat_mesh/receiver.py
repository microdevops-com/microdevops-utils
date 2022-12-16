#!/opt/sysadmws/misc/shebang_python_switcher.sh
# -*- coding: utf-8 -*-

import os
import sys
import time
from datetime import datetime
import yaml
import logging
from logging.handlers import RotatingFileHandler
import json
import argparse
import zmq
import systemd.daemon
import errno
import socket
import signal
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
try:
    import Queue as queue
except ImportError:
    import queue

# Constants
WORK_DIR = "/opt/sysadmws/heartbeat_mesh"
HEARTBEATS_DIR = "/opt/sysadmws/heartbeat_mesh/heartbeats/current"
HEARTBEATS_HISTORY_DIR = "/opt/sysadmws/heartbeat_mesh/heartbeats/history"
CONFIG_FILE = "receiver.yaml"
LOG_DIR = "/opt/sysadmws/heartbeat_mesh/log"
LOG_FILE = "receiver.log"
LOGO = "💔 ➔ ✉"
NAME = "heartbeat_mesh/receiver"
CHECK_INTERVAL = 60 # senders should send heartbeats each CHECK_INTERVAL seconds
TIMEOUT_JITTER = 60 # jitter for timeout if timeout and send interval are equal
GRACE_PERIOD = CHECK_INTERVAL + 10 # seconds all alive resources have to send their heartbeats
NOTIFY_DEVILRY_CMD = "/opt/sysadmws/notify_devilry/notify_devilry.py"
DEFAULT_PORT = 15987
START_TIME = datetime.now()
FNULL = open(os.devnull, 'w')
SEVERITY_INFORMATIONAL = "informational"
SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_MINOR = "minor"
SEVERITY_MAJOR = "major"
SEVERITY_CRITICAL = "critical"
SELF_SERVICE = "heartbeat"
SELF_HOSTNAME = socket.gethostname()
SELF_ORIGIN = "heartbeat_mesh/receiver.py"
NOTIFY_DEVILRY_SLEEP = 1 # 0.5 results in errors
FREQUENT_LOOP_SLEEP = CHECK_INTERVAL
RARE_LOOP_SLEEP = 60 * 30 # 30 minutes
QUEUE_THRESHOLD = 1000 # max number of notifies in queue before critical exit

# Funcs

def open_file(d, f, mode):
    # Check dir
    if not os.path.isdir(os.path.dirname("{0}/{1}".format(d, f))):
        try:
            os.makedirs(os.path.dirname("{0}/{1}".format(d, f)), 0o755)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(os.path.dirname("{0}/{1}".format(d, f))):
                pass
            else:
                raise
    return open("{0}/{1}".format(d, f), mode)

def send_notify_devilry(notify):
    notify_data = json.dumps(notify, ensure_ascii=False).encode()
    logger.info("Sending notify to notify_devilry: {notify}".format(notify=notify_data))
    run_cmd = NOTIFY_DEVILRY_CMD
    if args.force_send:
        run_cmd = run_cmd + " --force-send"
    run(run_cmd, input=notify_data, shell=True, stdout=FNULL)

# This thread does rare checks, e.g. heartbeat ok and others
def rare_checks_thread():

    logger.info("rare_checks_thread() started but sleeping first for grace period {secs} seconds".format(secs=GRACE_PERIOD))
    time.sleep(GRACE_PERIOD)

    while True:

        # Check iteration start time
        loop_start = int(time.time())

        logger.info("Doing rare checks")

        logger.info("Currently registered heartbeat resources and their data:")

        # Loop heartbeats
        for resource in heartbeats:

            logger.info(heartbeats[resource])
            heartbeat_age_secs = int((datetime.utcnow() - datetime.strptime(heartbeats[resource]["utc"], "%Y-%m-%d %H:%M:%S")).total_seconds())
            logger.info("Heartbeat age in seconds: {secs}".format(secs=heartbeat_age_secs))
            
            hb_timeout_to_use = 60 * (int(heartbeats[resource]["timeout"]) if heartbeats[resource]["timeout"] is not None else int(config["clients"][token_to_client[heartbeats[resource]["token"]]]["timeout"]))
            logger.info("Heartbeat timeout in seconds: {secs}".format(secs=hb_timeout_to_use))
            
            # Notify active heartbeats among currently registered in receiver
            if heartbeat_age_secs <= hb_timeout_to_use + TIMEOUT_JITTER:

                # Notify keys
                notify_client = token_to_client[heartbeats[resource]["token"]]
                # environment
                if resource in config["clients"][notify_client]["resources"] and "environment" in config["clients"][notify_client]["resources"][resource]:
                    notify_environment = config["clients"][notify_client]["resources"][resource]["environment"]
                else:
                    notify_environment = None
                # service
                if resource in config["clients"][notify_client]["resources"] and "service" in config["clients"][notify_client]["resources"][resource]:
                    notify_service = config["clients"][notify_client]["resources"][resource]["service"]
                else:
                    notify_service = SELF_SERVICE
                # location
                if resource in config["clients"][notify_client]["resources"] and "location" in config["clients"][notify_client]["resources"][resource]:
                    notify_location = config["clients"][notify_client]["resources"][resource]["location"]
                else:
                    notify_location = None

                # Prepare notify data
                notify = {}
                notify["severity"] = SEVERITY_OK
                notify["event"] = "heartbeat_mesh_heartbeat_ok"
                notify["text"] = "Resource heartbeat ok"
                notify["correlate"] = ["heartbeat_mesh_heartbeat_timeout"]
                if notify_environment is not None:
                    notify["environment"] = notify_environment
                notify["service"] = notify_service
                notify["resource"] = resource
                notify["value"] = heartbeat_age_secs
                notify["group"] = resource
                notify["origin"] = SELF_ORIGIN
                notify["attributes"] = {}
                notify["attributes"]["receiver"] = SELF_HOSTNAME
                notify["attributes"]["timeout"] = hb_timeout_to_use
                if notify_location is not None:
                    notify["attributes"]["location"] = notify_location
                notify["client"] = notify_client
                
                # Put notify to queue
                notify_queue.put(notify)
                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
        
            # Heartbeats among currently registered in receiver exist in config
            if resource in config["clients"][token_to_client[heartbeats[resource]["token"]]]["resources"]:

                # Notify keys
                notify_client = token_to_client[heartbeats[resource]["token"]]

                # Prepare notify data
                notify = {}
                notify["severity"] = SEVERITY_OK
                notify["event"] = "heartbeat_mesh_heartbeat_config_exist"
                notify["text"] = "Heartbeat registered more than 24h with resource listing in config"
                notify["correlate"] = ["heartbeat_mesh_heartbeat_config_missing"]
                notify["service"] = SELF_SERVICE
                notify["resource"] = resource
                notify["value"] = (datetime.utcnow() - oldest_heartbeats[resource]).days
                notify["group"] = resource
                notify["origin"] = SELF_ORIGIN
                notify["attributes"] = {}
                notify["attributes"]["receiver"] = SELF_HOSTNAME
                notify["client"] = notify_client
                
                # Put notify to queue
                notify_queue.put(notify)
                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
        
            # Else if heartbeats among currently registered in receiver missing in client resources for more than a day
            elif int((datetime.utcnow() - oldest_heartbeats[resource]).total_seconds()) > 60 * 60 * 24:

                # Notify keys
                notify_client = token_to_client[heartbeats[resource]["token"]]

                # Prepare notify data
                notify = {}
                notify["severity"] = SEVERITY_WARNING
                notify["event"] = "heartbeat_mesh_heartbeat_config_missing"
                notify["text"] = "Heartbeat registered more than 24h without resource listing in config"
                notify["correlate"] = ["heartbeat_mesh_heartbeat_config_exist"]
                notify["service"] = SELF_SERVICE
                notify["resource"] = resource
                notify["value"] = (datetime.utcnow() - oldest_heartbeats[resource]).days
                notify["group"] = resource
                notify["origin"] = SELF_ORIGIN
                notify["attributes"] = {}
                notify["attributes"]["receiver"] = SELF_HOSTNAME
                notify["client"] = notify_client
                
                # Put notify to queue
                notify_queue.put(notify)
                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
        
        logger.info("Checking heartbeats for client resources")

        for client in config["clients"]:
            for resource in config["clients"][client]["resources"]:

                # Check found/missing client resources in heartbeats

                # Notify keys
                notify_client = client
                # severity
                if resource in config["clients"][notify_client]["resources"] and "severity" in config["clients"][notify_client]["resources"][resource]:
                    notify_severity = config["clients"][notify_client]["resources"][resource]["severity"]
                elif "severity" in config["clients"][notify_client]:
                    notify_severity = config["clients"][notify_client]["severity"]
                else:
                    notify_severity = SEVERITY_CRITICAL
                # environment
                if resource in config["clients"][notify_client]["resources"] and "environment" in config["clients"][notify_client]["resources"][resource]:
                    notify_environment = config["clients"][notify_client]["resources"][resource]["environment"]
                else:
                    notify_environment = None
                # service
                if resource in config["clients"][notify_client]["resources"] and "service" in config["clients"][notify_client]["resources"][resource]:
                    notify_service = config["clients"][notify_client]["resources"][resource]["service"]
                else:
                    notify_service = SELF_SERVICE
                # location
                if resource in config["clients"][notify_client]["resources"] and "location" in config["clients"][notify_client]["resources"][resource]:
                    notify_location = config["clients"][notify_client]["resources"][resource]["location"]
                else:
                    notify_location = None

                # Prepare notify data
                notify = {}
                if resource not in heartbeats:
                    notify["severity"] = notify_severity
                    notify["event"] = "heartbeat_mesh_heartbeat_not_registered"
                    notify["value"] = "not registered"
                    notify["text"] = "No heartbeats registered for resource from config"
                    notify["correlate"] = ["heartbeat_mesh_heartbeat_registered"]
                else:
                    notify["severity"] = SEVERITY_OK
                    notify["event"] = "heartbeat_mesh_heartbeat_registered"
                    notify["value"] = "registered"
                    notify["text"] = "Heartbeats registered for resource from config"
                    notify["correlate"] = ["heartbeat_mesh_heartbeat_not_registered"]
                if notify_environment is not None:
                    notify["environment"] = notify_environment
                notify["service"] = notify_service
                notify["resource"] = resource
                notify["group"] = resource
                notify["origin"] = SELF_ORIGIN
                notify["attributes"] = {}
                notify["attributes"]["receiver"] = SELF_HOSTNAME
                if notify_location is not None:
                    notify["attributes"]["location"] = notify_location
                notify["client"] = notify_client
            
                # Put notify to queue
                notify_queue.put(notify)
                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
        
        # Get seconds needed to sleep
        sleep_secs = RARE_LOOP_SLEEP - (int(time.time()) - loop_start)

        # Sleep until frequent timeout finishes
        logger.info("Rare thread is going to sleep for {sec} seconds".format(sec=sleep_secs))
        time.sleep(sleep_secs)

# This thread does frequent checks, e.g. heartbeat timeout
def frequent_checks_thread():
    
    logger.info("frequent_checks_thread() started")
    
    while True:
        
        # Check iteration start time
        loop_start = int(time.time())
        
        logger.info("Doing frequent checks")

        # Check grace period these checks
        if int((datetime.now() - START_TIME).total_seconds()) > GRACE_PERIOD:
            logger.info("Grace period {gp} seconds passed".format(gp=GRACE_PERIOD))

            # Check any fresh activity for check interval + jitter
            if any((int((datetime.utcnow() - newest_heartbeats[resource]).total_seconds()) < (CHECK_INTERVAL + TIMEOUT_JITTER)) for resource in newest_heartbeats):

                # Prepare notify data
                notify = {}
                notify["severity"] = SEVERITY_OK
                notify["service"] = SELF_SERVICE
                notify["resource"] = SELF_HOSTNAME
                notify["event"] = "heartbeat_mesh_receiver_activity_ok"
                notify["value"] = "ok"
                notify["group"] = SELF_HOSTNAME
                notify["text"] = "Heartbeats are being received"
                notify["origin"] = SELF_ORIGIN
                notify["correlate"] = ["heartbeat_mesh_receiver_activity_lost"]
                
                # Put notify to queue
                notify_queue.put(notify)
                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))

            else:
                
                # Prepare notify data
                notify = {}
                notify["severity"] = SEVERITY_WARNING
                notify["service"] = SELF_SERVICE
                notify["resource"] = SELF_HOSTNAME
                notify["event"] = "heartbeat_mesh_receiver_activity_lost"
                notify["value"] = "lost"
                notify["group"] = SELF_HOSTNAME
                notify["text"] = "No heartbeats registered on receiver host for more than check interval + jitter"
                notify["origin"] = SELF_ORIGIN
                notify["correlate"] = ["heartbeat_mesh_receiver_activity_ok"]
                
                # Put notify to queue
                notify_queue.put(notify)
                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))

        else:
            logger.info("Grace period {gp} seconds not yet passed".format(gp=GRACE_PERIOD))

        logger.info("Currently registered heartbeat resources and their data:")

        # Once again check if we are not in a condition of lost activity, do not send individual alerts if there is no any heartbeat fresher than check interval + jitter.
        # This false blocks alerts in a situation when all heartbeats truly lost by their fauls, but will prevent from alert storm if fault is on the receiver side.
        # So there must be any alive resources for other resources to be alerted.
        if any((int((datetime.utcnow() - newest_heartbeats[resource]).total_seconds()) < (CHECK_INTERVAL + TIMEOUT_JITTER)) for resource in newest_heartbeats):

            # Loop heartbeats
            for resource in heartbeats:
                
                heartbeat_age_secs = int((datetime.utcnow() - datetime.strptime(heartbeats[resource]["utc"], "%Y-%m-%d %H:%M:%S")).total_seconds())
                logger.info("Heartbeat age in seconds: {secs}".format(secs=heartbeat_age_secs))
                
                hb_timeout_to_use = 60 * (int(heartbeats[resource]["timeout"]) if heartbeats[resource]["timeout"] is not None else int(config["clients"][token_to_client[heartbeats[resource]["token"]]]["timeout"]))
                logger.info("Heartbeat timeout in seconds: {secs}".format(secs=hb_timeout_to_use))
                
                # Notify stale heartbeats among currently registered in receiver
                if heartbeat_age_secs > hb_timeout_to_use + TIMEOUT_JITTER:

                    # Notify keys
                    notify_client = token_to_client[heartbeats[resource]["token"]]
                    # severity
                    if resource in config["clients"][notify_client]["resources"] and "severity" in config["clients"][notify_client]["resources"][resource]:
                        notify_severity = config["clients"][notify_client]["resources"][resource]["severity"]
                    elif "severity" in config["clients"][notify_client]:
                        notify_severity = config["clients"][notify_client]["severity"]
                    else:
                        notify_severity = SEVERITY_CRITICAL
                    # environment
                    if resource in config["clients"][notify_client]["resources"] and "environment" in config["clients"][notify_client]["resources"][resource]:
                        notify_environment = config["clients"][notify_client]["resources"][resource]["environment"]
                    else:
                        notify_environment = None
                    # service
                    if resource in config["clients"][notify_client]["resources"] and "service" in config["clients"][notify_client]["resources"][resource]:
                        notify_service = config["clients"][notify_client]["resources"][resource]["service"]
                    else:
                        notify_service = SELF_SERVICE
                    # location
                    if resource in config["clients"][notify_client]["resources"] and "location" in config["clients"][notify_client]["resources"][resource]:
                        notify_location = config["clients"][notify_client]["resources"][resource]["location"]
                    else:
                        notify_location = None

                    # Prepare notify data
                    notify = {}
                    notify["severity"] = notify_severity
                    notify["event"] = "heartbeat_mesh_heartbeat_timeout"
                    notify["text"] = "Resource heartbeat timed out"
                    notify["correlate"] = ["heartbeat_mesh_heartbeat_ok"]
                    if notify_environment is not None:
                        notify["environment"] = notify_environment
                    notify["service"] = notify_service
                    notify["resource"] = resource
                    notify["value"] = heartbeat_age_secs
                    notify["group"] = resource
                    notify["origin"] = SELF_ORIGIN
                    notify["attributes"] = {}
                    notify["attributes"]["receiver"] = SELF_HOSTNAME
                    notify["attributes"]["timeout"] = hb_timeout_to_use
                    if notify_location is not None:
                        notify["attributes"]["location"] = notify_location
                    notify["client"] = notify_client
                    
                    # Put notify to queue
                    notify_queue.put(notify)
                    logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))

        # Get seconds needed to sleep
        sleep_secs = FREQUENT_LOOP_SLEEP - (int(time.time()) - loop_start)

        # Sleep until frequent timeout finishes
        logger.info("Frequent thread is going to sleep for {sec} seconds".format(sec=sleep_secs))
        time.sleep(sleep_secs)

def notify_thread():
    logger.info("notify_thread() started")
    while True:
        notify = notify_queue.get()
        logger.info("Got notify from queue, queue size: {size}".format(size=notify_queue.qsize()))
        # Check queue size, no sense to send notifies if greater or equal than threshold, send only queue size error and exit
        if notify_queue.qsize() >= QUEUE_THRESHOLD:
            # Prepare notify data
            notify = {}
            notify["severity"] = SEVERITY_CRITICAL
            notify["service"] = SELF_SERVICE
            notify["resource"] = SELF_HOSTNAME
            notify["event"] = "heartbeat_mesh_receiver_queue_threshold_reached"
            notify["value"] = notify_queue.qsize()
            notify["group"] = SELF_HOSTNAME
            notify["text"] = "Receiver notifications queue size reached threshold {threshold}, receiver exited abnormally".format(threshold=QUEUE_THRESHOLD)
            notify["origin"] = SELF_ORIGIN
            logger.error("Queue size {size} became bigger than threshold {threshold}, exiting".format(size=notify_queue.qsize(), threshold=QUEUE_THRESHOLD))
            send_notify_devilry(notify)
            os.kill(os.getpid(), signal.SIGUSR1)
        else:
            # Send notify_devilry
            send_notify_devilry(notify)
        # Sleep not to overwhelm services
        time.sleep(NOTIFY_DEVILRY_SLEEP)

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
    parser = argparse.ArgumentParser(description="Receives heartbeats on tcp port and send their alert notifications to notify_devilry.")
    parser.add_argument("--debug", dest="debug", help="enable debug", action="store_true")
    parser.add_argument("--iface", dest="iface", help="listen iface", default="*")
    parser.add_argument("--port", dest="port", help="listen port", default=DEFAULT_PORT)
    parser.add_argument("--force-send", dest="force_send", help="force sending to notify_devilry", action="store_true")
    parser.add_argument("--no-heartbeat-files", dest="no_heartbeat_files", help="do not save history and current heartbeat files, they are needed only for additional purposes", action="store_true")
    args = parser.parse_args()
    
    # Enable debug
    if args.debug:
        console_handler.setLevel(logging.DEBUG)
    
    # Catch exception to logger
    try:
        logger.info(LOGO)

        # Load YAML config
        logger.info("Loading YAML config {work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE))
        with open("{work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE), 'r') as yaml_file:
            config = yaml.load(yaml_file, Loader=yaml.SafeLoader)

        # Check if enabled in config
        if config["enabled"] != True:
            logger.error("{name} not enabled in config, exiting".format(name=NAME))
            sys.exit(1)

        logger.info("Starting {name} on port {port}".format(name=NAME, port=args.port))

        # Check custom NOTIFY_DEVILRY_SLEEP and QUEUE_THRESHOLD in config
        if "notify_devilry_sleep" in config:
            NOTIFY_DEVILRY_SLEEP = config["notify_devilry_sleep"]
            logger.info("Using custom NOTIFY_DEVILRY_SLEEP {sleep}".format(sleep=NOTIFY_DEVILRY_SLEEP))
        if "queue_threshold" in config:
            QUEUE_THRESHOLD = config["queue_threshold"]
            logger.info("Using custom QUEUE_THRESHOLD {threshold}".format(threshold=QUEUE_THRESHOLD))

        # Transpone clients to token dict
        token_to_client = {}
        for client in config["clients"]:
            # Check token uniq
            if config["clients"][client]["token"] in token_to_client:
                logger.error("Found not unique token {token} for client {client}".format(token=config["clients"][client]["token"], client=client))
                sys.exit(1)
            # Add token
            token_to_client[config["clients"][client]["token"]] = client

        # Global vars
        heartbeats = {}
        oldest_heartbeats = {}
        newest_heartbeats = {}
        checks_last_time = int(time.time())
        
        # Start 0MQ
        logger.info("0MQ version {version}".format(version=zmq.pyzmq_version()))
        context = zmq.Context()
        zmqsocket = context.socket(zmq.PULL)
        zmqsocket.bind("tcp://{iface}:{port}".format(iface=args.iface, port=args.port))

        # Setup notify queue
        notify_queue = queue.Queue()

        # Setup notify_thread. No need to have a pool of threads for notify_devilry as telegram and alerta cant accept to many messages.
        notify_thread = threading.Thread(target=notify_thread)
        # According to docs daemon thread are abruptly stopped at shutdown, but their resources are not useful so it is ok. Daemon threads are stopped on main shutdown.
        notify_thread.setDaemon(True)
        notify_thread.start()
        logger.info("Started notify thread")
        
        # Setup frequent_checks_thread.
        notify_thread = threading.Thread(target=frequent_checks_thread)
        notify_thread.setDaemon(True)
        notify_thread.start()
        logger.info("Started frequent checks thread")
        
        # Setup rare_checks_thread.
        notify_thread = threading.Thread(target=rare_checks_thread)
        notify_thread.setDaemon(True)
        notify_thread.start()
        logger.info("Started rare checks thread")
        
        # SystemD notify
        systemd.daemon.notify('READY=1')

        while True:

            # Each zmq message could fail
            try:

                # Receive zmq message
                heartbeat = zmqsocket.recv_json()
                logger.info("Heartbeat received: {heartbeat}".format(heartbeat=heartbeat))
                
                # Check token and continue only if client for token found
                if "token" in heartbeat and heartbeat["token"] in token_to_client:

                    # Process heartbeat removal if special key sent by sender
                    if "deregister" in heartbeat and heartbeat["deregister"]:
                        
                        logger.info("Deregistration heartbeat for resource {resource} received".format(resource=heartbeat["resource"]))

                        # Remove resource from dicts
                        heartbeats.pop(heartbeat["resource"], None)
                        newest_heartbeats.pop(heartbeat["resource"], None)
                        oldest_heartbeats.pop(heartbeat["resource"], None)
                        logger.info("Host {resource} removed from dicts".format(resource=heartbeat["resource"]))

                        # Remove files
                        file_name = "{0}.{1}".format(heartbeat["resource"].replace(" ", "_").replace(".", "_"), "json")
                        hb_history_dir = "{0}/{1}".format(HEARTBEATS_HISTORY_DIR, token_to_client[heartbeat["token"]].lower())
                        hb_dir = "{0}/{1}".format(HEARTBEATS_DIR, token_to_client[heartbeat["token"]].lower())
                        if not args.no_heartbeat_files:
                            if os.path.exists(hb_history_dir + "/" + file_name):
                                os.remove(hb_history_dir + "/" + file_name)
                                logger.info("Heartbeat history file {dir}/{file_name} removed".format(dir=hb_history_dir, file_name=file_name))
                            if os.path.exists(hb_dir + "/" + file_name):
                                os.remove(hb_dir + "/" + file_name)
                                logger.info("Heartbeat file {dir}/{file_name} removed".format(dir=hb_dir, file_name=file_name))

                        # Send notify about deregistration
                        
                        # Notify keys
                        notify_client = token_to_client[heartbeat["token"]]
                        # environment
                        if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "environment" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                            notify_environment = config["clients"][notify_client]["resources"][heartbeat["resource"]]["environment"]
                        else:
                            notify_environment = None
                        # service
                        if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "service" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                            notify_service = config["clients"][notify_client]["resources"][heartbeat["resource"]]["service"]
                        else:
                            notify_service = SELF_SERVICE
                        # location
                        if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "location" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                            notify_location = config["clients"][notify_client]["resources"][heartbeat["resource"]]["location"]
                        else:
                            notify_location = None

                        # Prepare notify data
                        notify = {}
                        notify["severity"] = SEVERITY_INFORMATIONAL
                        if notify_environment is not None:
                            notify["environment"] = notify_environment
                        notify["service"] = notify_service
                        notify["resource"] = heartbeat["resource"]
                        notify["event"] = "heartbeat_mesh_heartbeat_deregistered"
                        notify["value"] = "deregistered"
                        notify["group"] = heartbeat["resource"]
                        notify["text"] = "Resource heartbeat deregistered"
                        notify["origin"] = SELF_ORIGIN
                        notify["attributes"] = {}
                        notify["attributes"]["receiver"] = SELF_HOSTNAME
                        if notify_location is not None:
                            notify["attributes"]["location"] = notify_location
                        notify["client"] = notify_client
                        
                        # Put notify to queue
                        notify_queue.put(notify)
                        logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))

                        # No other logic on deregister heartbeat
                        continue

                    # Construct data
                    utc_now = datetime.utcnow()
                    heartbeats[heartbeat["resource"]] = {
                        "utc": utc_now.strftime("%F %T"),
                        "resource": heartbeat["resource"],
                        "token": heartbeat["token"],
                        "payload": heartbeat["payload"] if "payload" in heartbeat else None,
                        "timeout": heartbeat["timeout"] if "timeout" in heartbeat else None
                    }

                    # Get json keys
                    logger.info("Heartbeat utc: {utc}".format(utc=heartbeats[heartbeat["resource"]]["utc"]))
                    logger.info("Heartbeat resource: {resource}".format(resource=heartbeats[heartbeat["resource"]]["resource"]))
                    logger.info("Heartbeat token: {token}".format(token=heartbeats[heartbeat["resource"]]["token"]))
                    logger.info("Heartbeat timeout: {timeout}".format(timeout=heartbeats[heartbeat["resource"]]["timeout"]))
                    logger.info("Heartbeat payload: {payload}".format(payload=heartbeats[heartbeat["resource"]]["payload"]))

                    file_name = "{0}.{1}".format(heartbeat["resource"].replace(" ", "_").replace(".", "_"), "json")
                    hb_history_dir = "{0}/{1}".format(HEARTBEATS_HISTORY_DIR, token_to_client[heartbeats[heartbeat["resource"]]["token"]].lower())
                    hb_dir = "{0}/{1}".format(HEARTBEATS_DIR, token_to_client[heartbeats[heartbeat["resource"]]["token"]].lower())

                    # Save history
                    if not args.no_heartbeat_files:
                        with open_file(hb_history_dir, file_name, "a+") as heartbeat_file:
                            json.dump(heartbeats[heartbeat["resource"]], heartbeat_file)
                            heartbeat_file.write("\n")
                            logger.info("Heartbeat appended to the history file: {dir}/{file_name}".format(dir=hb_history_dir, file_name=file_name))
                    
                    # Save current
                    if not args.no_heartbeat_files:
                        with open_file(hb_dir, "{0}.{1}".format(heartbeat["resource"].replace(" ", "_").replace(".", "_"), "json"), "w+") as heartbeat_file:
                            json.dump(heartbeats[heartbeat["resource"]], heartbeat_file)
                            logger.info("Heartbeat written to the file: {dir}/{file_name}".format(dir=hb_dir, file_name=file_name))

                    # Send notify after grace period
                    if int((datetime.now() - START_TIME).total_seconds()) > GRACE_PERIOD:
                        logger.info("Grace period {gp} seconds passed".format(gp=GRACE_PERIOD))

                        # If new resource
                        if heartbeat["resource"] not in newest_heartbeats:

                            # Notify keys
                            notify_client = token_to_client[heartbeat["token"]]
                            # environment
                            if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "environment" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                                notify_environment = config["clients"][notify_client]["resources"][heartbeat["resource"]]["environment"]
                            else:
                                notify_environment = None
                            # service
                            if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "service" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                                notify_service = config["clients"][notify_client]["resources"][heartbeat["resource"]]["service"]
                            else:
                                notify_service = SELF_SERVICE
                            # location
                            if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "location" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                                notify_location = config["clients"][notify_client]["resources"][heartbeat["resource"]]["location"]
                            else:
                                notify_location = None

                            # Prepare notify data
                            notify = {}
                            notify["severity"] = SEVERITY_INFORMATIONAL
                            if notify_environment is not None:
                                notify["environment"] = notify_environment
                            notify["service"] = notify_service
                            notify["resource"] = heartbeat["resource"]
                            notify["event"] = "heartbeat_mesh_heartbeat_new"
                            notify["value"] = "registered"
                            notify["group"] = heartbeat["resource"]
                            notify["text"] = "New resource heartbeat registered"
                            notify["origin"] = SELF_ORIGIN
                            notify["attributes"] = {}
                            notify["attributes"]["receiver"] = SELF_HOSTNAME
                            if notify_location is not None:
                                notify["attributes"]["location"] = notify_location
                            notify["client"] = notify_client
                            
                            # Put notify to queue
                            notify_queue.put(notify)
                            logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
                    
                        # If newest heartbeat is stale and we receive new heartbeat - comeback
                        if heartbeat["resource"] in newest_heartbeats:
                        
                            newest_heartbeat_age_secs = int((datetime.utcnow() - newest_heartbeats[heartbeat["resource"]]).total_seconds())
                            logger.info("Newest heartbeat age in seconds: {secs}".format(secs=newest_heartbeat_age_secs))
                            
                            hb_timeout_to_use = 60 * (int(heartbeats[heartbeat["resource"]]["timeout"]) if heartbeats[heartbeat["resource"]]["timeout"] is not None else int(config["clients"][token_to_client[heartbeats[heartbeat["resource"]]["token"]]]["timeout"]))
                            logger.info("Heartbeat timeout in seconds: {secs}".format(secs=hb_timeout_to_use))

                            # Check if previous hb was stale
                            if newest_heartbeat_age_secs > hb_timeout_to_use + TIMEOUT_JITTER:

                                # Send info comeback

                                # Notify keys
                                notify_client = token_to_client[heartbeat["token"]]
                                # environment
                                if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "environment" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                                    notify_environment = config["clients"][notify_client]["resources"][heartbeat["resource"]]["environment"]
                                else:
                                    notify_environment = None
                                # service
                                if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "service" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                                    notify_service = config["clients"][notify_client]["resources"][heartbeat["resource"]]["service"]
                                else:
                                    notify_service = SELF_SERVICE
                                # location
                                if heartbeat["resource"] in config["clients"][notify_client]["resources"] and "location" in config["clients"][notify_client]["resources"][heartbeat["resource"]]:
                                    notify_location = config["clients"][notify_client]["resources"][heartbeat["resource"]]["location"]
                                else:
                                    notify_location = None

                                # Prepare notify data
                                notify = {}
                                notify["severity"] = SEVERITY_INFORMATIONAL
                                if notify_environment is not None:
                                    notify["environment"] = notify_environment
                                notify["service"] = notify_service
                                notify["resource"] = heartbeat["resource"]
                                notify["event"] = "heartbeat_mesh_heartbeat_comeback"
                                notify["value"] = "comeback"
                                notify["group"] = heartbeat["resource"]
                                notify["text"] = "Heartbeat comeback registered after timeout"
                                notify["origin"] = SELF_ORIGIN
                                notify["attributes"] = {}
                                notify["attributes"]["receiver"] = SELF_HOSTNAME
                                notify["attributes"]["timeout"] = hb_timeout_to_use
                                if notify_location is not None:
                                    notify["attributes"]["location"] = notify_location
                                notify["client"] = notify_client
                                
                                # Put notify to queue
                                notify_queue.put(notify)
                                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
                                
                                # And clean previous timeout

                                # Prepare notify data
                                notify = {}
                                notify["severity"] = SEVERITY_OK
                                notify["event"] = "heartbeat_mesh_heartbeat_ok"
                                notify["text"] = "Resource heartbeat ok"
                                notify["correlate"] = ["heartbeat_mesh_heartbeat_timeout"]
                                if notify_environment is not None:
                                    notify["environment"] = notify_environment
                                notify["service"] = notify_service
                                notify["resource"] = heartbeat["resource"]
                                notify["value"] = 0
                                notify["group"] = heartbeat["resource"]
                                notify["origin"] = SELF_ORIGIN
                                notify["attributes"] = {}
                                notify["attributes"]["receiver"] = SELF_HOSTNAME
                                notify["attributes"]["timeout"] = hb_timeout_to_use
                                if notify_location is not None:
                                    notify["attributes"]["location"] = notify_location
                                notify["client"] = notify_client
                                
                                # Put notify to queue
                                notify_queue.put(notify)
                                logger.info("Put notify to queue, queue size: {size}".format(size=notify_queue.qsize()))
                    
                    else:
                        logger.info("Grace period {gp} seconds not yet passed".format(gp=GRACE_PERIOD))

                    # Save oldest (first) heartbeat
                    if heartbeat["resource"] not in oldest_heartbeats:
                        oldest_heartbeats[heartbeat["resource"]] = utc_now

                    # Save newest (last) heartbeat
                    newest_heartbeats[heartbeat["resource"]] = utc_now

                else:
                    if "token" in heartbeat:
                        logger.warning("Heartbeat resource: {resource}, token: {token} - token not found, ignoring ".format(resource=heartbeat["resource"], token=heartbeat["token"]))
                    else:
                        logger.warning("Heartbeat resource: {resource} has no token, ignoring ".format(resource=heartbeat["resource"]))

            # Reroute catched exception to log
            except Exception as e:
                logger.exception(e)
    
    # Reroute catched exception to log
    except Exception as e:
        logger.exception(e)
