#!/opt/sysadmws/misc/shebang_python_switcher.sh
# -*- coding: utf-8 -*-

import os
import zmq
import sys
import time
import socket
import subprocess
import yaml
import logging
from logging.handlers import RotatingFileHandler
try:
    import argparse
    ARGPARSE = True
except ImportError:
    ARGPARSE = False

# Constants
WORK_DIR = "c:\\opt\\sysadmws\\heartbeat_mesh" if os.name == "nt" else "/opt/sysadmws/heartbeat_mesh"
CONFIG_FILE = "sender.yaml"
LOG_DIR = "c:\\opt\\sysadmws\\heartbeat_mesh\\log" if os.name == "nt" else "/opt/sysadmws/heartbeat_mesh/log"
LOG_FILE = "sender.log"
LOGO = "💔 ➔ ✉"
ZMQ_LINGER = 10000 # try to send heartbeat for ZMQ_LINGER ms
DEFAULT_PORT = 15987
TMP_DIR = "c:\\opt\\sysadmws\\heartbeat_mesh\\tmp" if os.name == "nt" else "/tmp"

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

        parser = argparse.ArgumentParser(description="Send heartbeats to tcp port.")
        parser.add_argument("--debug", dest="debug", help="enable debug", action="store_true")
        parser.add_argument("--config", dest="config", help="override config")
        parser.add_argument("--deregister", dest="deregister", help="send deregistration of RESOURCE heartbeat to RECEIVER:PORT using TOKEN, config is not used", nargs=4, metavar=("RESOURCE", "RECEIVER", "PORT", "TOKEN"))
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
        if ARGPARSE and args.config:
            # Override config
            logger.info("Loading YAML config {config_file}".format(config_file=args.config))
            with open("{config_file}".format(config_file=args.config), 'r') as yaml_file:
                config = yaml.load(yaml_file, Loader=yaml.SafeLoader)
        else:
            logger.info("Loading YAML config {work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE))
            with open("{work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE), 'r') as yaml_file:
                config = yaml.load(yaml_file, Loader=yaml.SafeLoader)

        # Deregister
        if ARGPARSE and args.deregister:
            
            logger.info("Starting heartbeat_mesh sender")
            logger.info("0MQ version {version}".format(version=zmq.pyzmq_version()))

            dr_resource, dr_receiver, dr_port, dr_token = args.deregister

            heartbeat = {}
            
            heartbeat["token"] = dr_token
            heartbeat["resource"] = dr_resource
            heartbeat["deregister"] = True

            logger.info("Heartbeat data for receiver {receiver}:{port}:".format(receiver=dr_receiver, port=dr_port))
            logger.info(heartbeat)

            logger.info("Connecting receiver {receiver}:{port} 0MQ".format(receiver=dr_receiver, port=dr_port))
            context = zmq.Context()
            zmqsocket = context.socket(zmq.PUSH)
            zmqsocket.setsockopt(zmq.LINGER, ZMQ_LINGER)
            zmqsocket.connect("tcp://{receiver}:{port}".format(receiver=dr_receiver, port=dr_port))

            logger.info("Sending 0MQ message")
            zmqsocket.send_json(heartbeat)

            logger.info("Closing receiver {receiver}:{port} 0MQ".format(receiver=dr_receiver, port=dr_port))
            zmqsocket.close()
            context.term()

            sys.exit(0)

        # Check if enabled in config
        if config["enabled"] != True:
            logger.error("heartbeat_mesh sender not enabled in config, exiting")
            sys.exit(1)

        logger.info("Starting heartbeat_mesh sender")

        # Start 0MQ
        logger.info("0MQ version {version}".format(version=zmq.pyzmq_version()))

        # Do write-read checks
        if not ("tmp_file_check" in config and config["tmp_file_check"] == False):
            # Get random (uuid)
            with open('/proc/sys/kernel/random/uuid', 'r') as f:
                uuid = f.readline().rstrip()
                logger.info("Random uuid: {uuid}".format(uuid=uuid))
            # File name
            file_name = TMP_DIR + "/" + uuid
            # Write
            with open(file_name, "w+") as tmp_file:
                tmp_file.write(uuid)
                tmp_file.flush()
                os.fsync(tmp_file)
                logger.info("Wrote tmp file: {file_name}".format(file_name=file_name))
            # Read
            with open(file_name, "r") as tmp_file:
                read_uuid = tmp_file.readline()
                logger.info("Read {data} from tmp file: {file_name}".format(data=read_uuid, file_name=file_name))
            # Compare values
            if uuid != read_uuid:
                logger.error("Write-read check failed, values do not match, exiting")
                sys.exit(1)
            else:
                logger.info("Write-read check successful, values do match")
            # Remove
            if os.path.exists(file_name):
                os.remove(file_name)
                logger.info("Tmp file {file_name} removed".format(file_name=file_name))

        # Loop for receivers
        for receiver in config["receivers"]:

            # Each receiver could fail
            try:

                # Prepare heartbeat data
                
                heartbeat = {}
                heartbeat["payload"] = {}
                
                heartbeat["token"] = config["receivers"][receiver]["token"]

                if "resource" in config["receivers"][receiver]:
                    heartbeat["resource"] = config["receivers"][receiver]["resource"]
                else:
                    heartbeat["resource"] = socket.gethostname()

                if "timeout" in config["receivers"][receiver]:
                    heartbeat["timeout"] = config["receivers"][receiver]["timeout"]

                if not ("uptime_payload" in config["receivers"][receiver] and config["receivers"][receiver]["uptime_payload"] == False):
                    with open('/proc/uptime', 'r') as f:
                        uptime_seconds = int(float(f.readline().split()[0]))
                    heartbeat["payload"]["uptime"] = uptime_seconds

                if "payload" in config["receivers"][receiver]:
                    for payload in config["receivers"][receiver]["payload"]:
                        heartbeat["payload"][payload["name"]] = subprocess.check_output(payload["cmd"]).decode().rstrip()

                logger.info("Heartbeat data for receiver {receiver}:".format(receiver=receiver))
                logger.info(heartbeat)

                # 0MQ send message
                logger.info("Connecting receiver {receiver} 0MQ".format(receiver=receiver))
                context = zmq.Context()
                zmqsocket = context.socket(zmq.PUSH)
                zmqsocket.setsockopt(zmq.LINGER, ZMQ_LINGER)
                zmqsocket.connect("tcp://{receiver}:{port}".format(receiver=receiver, port=config["receivers"][receiver]["port"] if "port" in config["receivers"][receiver] else DEFAULT_PORT))

                logger.info("Sending 0MQ message")
                zmqsocket.send_json(heartbeat)

                logger.info("Closing receiver {receiver} 0MQ".format(receiver=receiver))
                zmqsocket.close()
                context.term()
                time.sleep(1)

            # Reroute catched exception to log
            except Exception as e:
                logger.exception(e)

    # Reroute catched exception to log
    except Exception as e:
        logger.exception(e)

    logger.info("Finished heartbeat_mesh sender")
