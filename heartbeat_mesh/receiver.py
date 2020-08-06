#!/usr/bin/python
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
TIMEOUT_JITTER = 2 # jitter for timeout if timeout and send interval are equal
ZMQ_RCVTIMEO = CHECK_INTERVAL * 1000
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
SELF_GROUP = "heartbeat_mesh"
SELF_HOSTNAME = socket.gethostname()
SELF_ORIGIN = "heartbeat_mesh/receiver.py"

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

def do_checks():

    logger.info("Newest heartbeats:")
    logger.info(newest_heartbeats)
    logger.info("Oldest heartbeats:")
    logger.info(oldest_heartbeats)

    # Check no activity at all for 2x check intervals
    if any((int((datetime.utcnow() - newest_heartbeats[resource]).total_seconds()) < (CHECK_INTERVAL * 2)) for resource in newest_heartbeats):

        # Prepare notify data
        notify = {}
        notify["severity"] = SEVERITY_OK
        notify["service"] = SELF_SERVICE
        notify["resource"] = SELF_HOSTNAME
        notify["event"] = "heartbeat_mesh_receiver_activity_ok"
        notify["value"] = "ok"
        notify["group"] = SELF_GROUP
        notify["text"] = "Heartbeats are being received"
        notify["origin"] = SELF_ORIGIN
        notify["correlate"] = ["heartbeat_mesh_receiver_activity_lost"]
        
        # Send notify_devilry
        send_notify_devilry(notify)

    else:
        
        # Prepare notify data
        notify = {}
        notify["severity"] = SEVERITY_WARNING
        notify["service"] = SELF_SERVICE
        notify["resource"] = SELF_HOSTNAME
        notify["event"] = "heartbeat_mesh_receiver_activity_lost"
        notify["value"] = "lost"
        notify["group"] = SELF_GROUP
        notify["text"] = "No heartbeats registered on receiver host for two check intervals"
        notify["origin"] = SELF_ORIGIN
        notify["correlate"] = ["heartbeat_mesh_receiver_activity_ok"]
        
        # Send notify_devilry
        send_notify_devilry(notify)

    logger.info("Currently registered heartbeat resources and their data:")

    for resource in heartbeats:

        logger.info(heartbeats[resource])
        heartbeat_age_secs = int((datetime.utcnow() - datetime.strptime(heartbeats[resource]["utc"], "%Y-%m-%d %H:%M:%S")).total_seconds())
        logger.info("Heartbeat age in seconds: {secs}".format(secs=heartbeat_age_secs))
        
        hb_timeout_to_use = 60 * (int(heartbeats[resource]["timeout"]) if heartbeats[resource]["timeout"] is not None else int(config["clients"][token_to_client[heartbeats[resource]["token"]]]["timeout"]))
        logger.info("Heartbeat timeout in seconds: {secs}".format(secs=hb_timeout_to_use))
        
        # Notify active/stale heartbeats among currently registered in receiver

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
        if heartbeat_age_secs > hb_timeout_to_use + TIMEOUT_JITTER:
            notify["severity"] = notify_severity
            notify["event"] = "heartbeat_mesh_heartbeat_timeout"
            notify["text"] = "Resource heartbeat timed out"
            notify["correlate"] = ["heartbeat_mesh_heartbeat_ok"]
        else:
            notify["severity"] = SEVERITY_OK
            notify["event"] = "heartbeat_mesh_heartbeat_ok"
            notify["text"] = "Resource heartbeat ok"
            notify["correlate"] = ["heartbeat_mesh_heartbeat_timeout"]
        if notify_environment is not None:
            notify["environment"] = notify_environment
        notify["service"] = notify_service
        notify["resource"] = resource
        notify["value"] = heartbeat_age_secs
        notify["group"] = SELF_GROUP
        notify["origin"] = SELF_ORIGIN
        notify["attributes"] = {}
        notify["attributes"]["receiver"] = SELF_HOSTNAME
        notify["attributes"]["timeout"] = hb_timeout_to_use
        if notify_location is not None:
            notify["attributes"]["location"] = notify_location
        notify["client"] = notify_client
        
        # Send notify_devilry
        send_notify_devilry(notify)
    
        # Heartbeats among currently registered in receiver exist/missing in client resources for more than a day
        if int((datetime.utcnow() - oldest_heartbeats[resource]).total_seconds()) > 60 * 60 * 24:

            # Notify keys
            notify_client = token_to_client[heartbeats[resource]["token"]]
            # severity
            if "severity" in config["clients"][notify_client]:
                notify_severity = config["clients"][notify_client]["severity"]
            else:
                notify_severity = SEVERITY_CRITICAL

            # Prepare notify data
            notify = {}
            if resource not in config["clients"][token_to_client[heartbeats[resource]["token"]]]["resources"]:
                notify["severity"] = notify_severity
                notify["event"] = "heartbeat_mesh_heartbeat_config_missing"
                notify["text"] = "Heartbeat registered more than 24h without resource listing in config"
                notify["correlate"] = ["heartbeat_mesh_heartbeat_config_exist"]
            else:
                notify["severity"] = SEVERITY_OK
                notify["event"] = "heartbeat_mesh_heartbeat_config_exist"
                notify["text"] = "Heartbeat registered more than 24h withresource listing in config"
                notify["correlate"] = ["heartbeat_mesh_heartbeat_config_missing"]
            notify["service"] = SELF_SERVICE
            notify["resource"] = resource
            notify["value"] = (datetime.utcnow() - oldest_heartbeats[resource]).days
            notify["group"] = SELF_GROUP
            notify["origin"] = SELF_ORIGIN
            notify["attributes"] = {}
            notify["attributes"]["receiver"] = SELF_HOSTNAME
            notify["client"] = notify_client
            
            # Send notify_devilry
            send_notify_devilry(notify)
    
    # Check grace period for other checks
    if int((datetime.now() - START_TIME).total_seconds()) > GRACE_PERIOD:
        logger.info("Grace period {gp} seconds passed".format(gp=GRACE_PERIOD))

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
                notify["group"] = SELF_GROUP
                notify["origin"] = SELF_ORIGIN
                notify["attributes"] = {}
                notify["attributes"]["receiver"] = SELF_HOSTNAME
                if notify_location is not None:
                    notify["attributes"]["location"] = notify_location
                notify["client"] = notify_client
            
                # Send notify_devilry
                send_notify_devilry(notify)
    
    else:
        logger.info("Grace period {gp} seconds not yet passed".format(gp=GRACE_PERIOD))

    return int(time.time())

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
        
        # Start 0MQ
        logger.info("0MQ version {version}".format(version=zmq.pyzmq_version()))
        context = zmq.Context()
        zmqsocket = context.socket(zmq.PAIR)
        zmqsocket.setsockopt(zmq.RCVTIMEO, ZMQ_RCVTIMEO)
        zmqsocket.bind("tcp://{iface}:{port}".format(iface=args.iface, port=args.port))

        # Transpone clients to token dict
        token_to_client = {}
        for client in config["clients"]:
            # Check token uniq
            if config["clients"][client]["token"] in token_to_client:
                logger.error("Found not unique token {token} for client {client}".format(token=config["clients"][client]["token"], client=client))
                sys.exit(1)
            # Add token
            token_to_client[config["clients"][client]["token"]] = client

        systemd.daemon.notify('READY=1')

        heartbeats = {}
        oldest_heartbeats = {}
        newest_heartbeats = {}
        checks_last_time = int(time.time())

        while True:

            # Each zmq message could fail
            try:

                try:

                    # Receive zmq message
                    message = zmqsocket.recv()
                    heartbeat = json.loads(message)
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
                            notify["group"] = SELF_GROUP
                            notify["text"] = "Resource heartbeat deregistered"
                            notify["origin"] = SELF_ORIGIN
                            notify["attributes"] = {}
                            notify["attributes"]["receiver"] = SELF_HOSTNAME
                            if notify_location is not None:
                                notify["attributes"]["location"] = notify_location
                            notify["client"] = notify_client
                            
                            # Send notify_devilry
                            send_notify_devilry(notify)

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

                            # If new resource
                            if heartbeat["resource"] not in newest_heartbeats:

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
                                notify["event"] = "heartbeat_mesh_heartbeat_new"
                                notify["value"] = "registered"
                                notify["group"] = SELF_GROUP
                                notify["text"] = "New resource heartbeat registered"
                                notify["origin"] = SELF_ORIGIN
                                notify["attributes"] = {}
                                notify["attributes"]["receiver"] = SELF_HOSTNAME
                                if notify_location is not None:
                                    notify["attributes"]["location"] = notify_location
                                notify["client"] = notify_client
                                
                                # Send notify_devilry
                                send_notify_devilry(notify)
                        
                            # If newest heartbeat is stale and we receive new heartbeat
                            if heartbeat["resource"] in newest_heartbeats:
                            
                                newest_heartbeat_age_secs = int((datetime.utcnow() - newest_heartbeats[heartbeat["resource"]]).total_seconds())
                                hb_timeout_to_use = 60 * (int(heartbeats[heartbeat["resource"]]["timeout"]) if heartbeats[heartbeat["resource"]]["timeout"] is not None else int(config["clients"][token_to_client[heartbeats[heartbeat["resource"]]["token"]]]["timeout"]))

                                if newest_heartbeat_age_secs > hb_timeout_to_use + TIMEOUT_JITTER:

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
                                    notify["group"] = SELF_GROUP
                                    notify["text"] = "New heartbeat comeback registered after timeout"
                                    notify["origin"] = SELF_ORIGIN
                                    notify["attributes"] = {}
                                    notify["attributes"]["receiver"] = SELF_HOSTNAME
                                    notify["attributes"]["timeout"] = hb_timeout_to_use
                                    if notify_location is not None:
                                        notify["attributes"]["location"] = notify_location
                                    notify["client"] = notify_client
                                    
                                    # Send notify_devilry
                                    send_notify_devilry(notify)
                        
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

                    # Reload config and do checks on each message and save last time of checks
                    # But only if check_interval secs from previous checks
                    if (int(time.time()) - checks_last_time) >= CHECK_INTERVAL: 
                        logger.info("Loading YAML config {work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE))
                        try:
                            old_config = config
                            with open("{work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE), 'r') as yaml_file:
                                config = yaml.load(yaml_file, Loader=yaml.SafeLoader)
                        except:
                            config = old_config
                        logger.info("Doing heartbeat checks")
                        checks_last_time = do_checks()
                    else:
                        logger.info("Not doing heartbeat checks, waiting {n} seconds".format(n=(CHECK_INTERVAL - (int(time.time()) - checks_last_time))))
                    
                except zmq.error.Again as e:
                    
                    # Reload config and do checks on recv timeout and save last time of checks
                    logger.info("Loading YAML config {work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE))
                    try:
                        old_config = config
                        with open("{work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE), 'r') as yaml_file:
                            config = yaml.load(yaml_file, Loader=yaml.SafeLoader)
                    except:
                        config = old_config
                    logger.info("Timeout on receiving heartbeat, doing heartbeat checks")
                    checks_last_time = do_checks()
                    logger.info("Done with checks after timeout on receiving heartbeat, looping")
            
            # Reroute catched exception to log
            except Exception as e:
                logger.exception(e)
    
    # Reroute catched exception to log
    except Exception as e:
        logger.exception(e)
