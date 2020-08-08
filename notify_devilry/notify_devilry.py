#!/opt/sysadmws/misc/shebang_python_switcher.sh
# -*- coding: utf-8 -*-

import os
import shutil
import sys
import time
from datetime import datetime
import yaml
import urllib
import socket
import subprocess
import textwrap
import copy
try:
    from urllib.parse import urlencode
    from urllib.request import urlopen, Request
except ImportError:
    from urllib import urlencode
    from urllib2 import urlopen, Request
import logging
from logging.handlers import RotatingFileHandler
try:
    import json
except ImportError:
    import simplejson as json
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
# No way to use that on 2.6
try:
    import argparse
    ARGPARSE = True
except ImportError:
    ARGPARSE = False

# Constants
WORK_DIR = "/opt/sysadmws/notify_devilry"
HISTORY_DIR = "/opt/sysadmws/notify_devilry/history"
CONFIG_FILE = "notify_devilry.yaml"
LOG_DIR = "/opt/sysadmws/notify_devilry/log"
LOG_FILE = "notify_devilry.log"
HISTORY_MESSAGE_IN_PREFIX = "in"
HISTORY_MESSAGE_OUT_PREFIX = "out"
HISTORY_MESSAGE_SUFFIX = "json"
SENDING_METHODS = ['alerta', 'telegram']
LOGO="✉ ➔ ✂ ➔ ❓ ➔ ✌"
NAME="notify_devilry"
UT_NOW = int(time.time())
MAX_INDENT = 100
SELF_GROUP = "notify_devilry"
SELF_ORIGIN = "notify_devilry.py"
SELF_SERVICE = "notify_devilry"
ALERTA_RETRIES = 3
ALERTA_RETRY_SLEEP = 2
ALERTA_URLOPEN_TIMEOUT = 5
SEVERITY_MINOR = "minor"

# Custom Exceptions
class LoadJsonError(Exception):
    pass

# Load JSON from file
def load_json(f):
    try:
        message = json.load(f)
    except:
        try:
            file_data = f.read()
            message = json.loads(file_data)
        except:
            raise LoadJsonError("Reading JSON message from file {0} failed".format(f))
    return message

# Check needed key in dict
def check_json_key(key, msg):
    if not key in msg:
        raise LoadJsonError("No {0} key in JSON message {1}".format(key, msg))

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

# Send methods

# Alerta
def send_alerta(url, api_key, msg):
    # Keys ignored:
    # client - alerta maps customer by api key
    data = {
        "severity": msg["severity"],
        "environment": msg["environment"],
        "service": [msg["service"]],
        "resource": msg["resource"],
        "event": msg["event"],
        "value": msg["value"],
        "group": msg["group"],
        "origin": msg["origin"],
        "attributes": msg["attributes"],
        "text": msg["text"],
        "type": msg["type"]
    }
    if "timeout" in msg:
        data["timeout"] = msg["timeout"]
    if "correlate" in msg:
        data["correlate"] = msg["correlate"]

    url_data = json.dumps(data).encode()
    url_req = Request(url)
    url_req.add_header("Content-Type", "application/json")
    url_req.add_header("Authorization", "Key {api_key}".format(api_key=api_key))
    url_obj = urlopen(url_req, url_data, ALERTA_URLOPEN_TIMEOUT)
    url_result = url_obj.read()
    logger.info("Sending to Alerta API result: {0}".format(url_result))

# Telegram
def send_telegram(token, chat_id, sound, msg):
    # Format message as text
    message = textwrap.dedent(
        """
        source: [sysadmws-utils](https://github.com/sysadmws/sysadmws-utils)
        severity: *{severity}*
        client: *{client}*
        environment: *{environment}*
        service: *{service}*
        resource: *{resource}*
        event: *{event}*
        value: *{value}*
        group: *{group}*
        origin: *{origin}*
        {attributes}

        ```
        {text}
        ```
        """
        ).lstrip().rstrip().format(
            severity=msg["severity"],
            client=msg["client"],
            environment=msg["environment"],
            service=msg["service"],
            resource=msg["resource"],
            event=msg["event"],
            value=msg["value"],
            group=msg["group"],
            origin=msg["origin"],
            attributes="\n".join(str(a) + ": *" + str(msg["attributes"][a]) + "*" for a in sorted(msg["attributes"])),
            text=msg["text"]
        )
    # Decide sound
    if sound is not None:
        if msg["severity"] in sound:
            disable_notification = "false"
        else:
            disable_notification = "true"
    else:
        disable_notification = "false"
    url_url = "https://api.telegram.org/bot{0}/sendMessage".format(token)
    url_data = urlencode({"parse_mode": "Markdown", "chat_id": chat_id, "disable_web_page_preview": "true", "disable_notification": disable_notification, "text": message}).encode()
    url_req = Request(url_url)
    url_obj = urlopen(url_req, url_data)
    url_result = url_obj.read()
    logger.info("Sending to TG API result: {0}".format(url_result))

# Universal send method
# Alerta bug found:
# If you send several consecutive immediate alerts with the same severity, env, resource, event - it will 500 and 200 after some time.
# So retry - is a good workaround.
# Retrying module is not generally available, so done without it.
def send_message(sending_method, sending_method_item_settings, message):
    if sending_method == "alerta":
        url = sending_method_item_settings["url"]
        api_key = sending_method_item_settings["api_key"]
        for retry in range(ALERTA_RETRIES):
            try:
                send_alerta(url, api_key, message)
            except Exception as e:
                # Retry if not last retry
                if retry < (ALERTA_RETRIES - 1):
                    logger.error("send_alerta exception catch, retry {retry}".format(retry=retry + 1))
                    time.sleep(ALERTA_RETRY_SLEEP)
                else:
                    # Send exception
                    logger.error("send_alerta exception catch, all retries failed")
                    if "exception" in sending_method_item_settings:
                        logger.info("Sending exception")
                        exception_message = {
                            "severity": SEVERITY_MINOR,
                            "service": SELF_SERVICE,
                            "resource": socket.gethostname(),
                            "event": "notify_devilry_alerta_send_error",
                            "value": str(type(e).__name__),
                            "group": SELF_GROUP,
                            "origin": SELF_ORIGIN,
                            "text": str(e),
                            "attributes": {
                                "alerta url": sending_method_item_settings["url"]
                            }
                        }
                        exception_message = apply_defaults(exception_message)
                        for s_method in SENDING_METHODS:
                            if s_method in sending_method_item_settings["exception"]:
                                for al in sending_method_item_settings["exception"][s_method]:
                                    al_settings = config[s_method][al] 
                                    send_message(s_method, al_settings, exception_message)
                    # And raise
                    raise
            else:
                break
    if sending_method == "telegram":
        token = sending_method_item_settings["token"]
        chat_id = sending_method_item_settings["chat_id"]
        sound = sending_method_item_settings["sound"] if "sound" in sending_method_item_settings else None
        send_telegram(token, chat_id, sound, message)

# History funcs
def history_load_message_in(f, key):
    # Read JSON from file
    try:
        f.seek(0)
        history_dict = json.load(f)
        return history_dict[key]
    # On any kind of error just return None
    except:
        return None

def history_save_message_in(f, last_2, last_1):
    # Reset file pos
    f.seek(0)
    # Compose dict
    history_dict = {"last_2": last_2, "last_1": last_1}
    # Save dict as JSON
    json.dump(history_dict, f)
    f.truncate()

def history_load_message_out(f, key):
    # Read JSON from file
    try:
        f.seek(0)
        history_dict = json.load(f)
        return history_dict[key]
    except:
        if key == "count":
            return 0
        else:
            return None

def history_save_message_out(f, last, count):
    # Reset file pos
    f.seek(0)
    # Compose dict
    history_dict = {"last": last, "count": count}
    # Save dict as JSON
    json.dump(history_dict, f)
    f.truncate()

# History file funcs
def open_history_message_file(d, f):
    # Check dir
    if not os.path.isdir(d):
        os.mkdir(d, 0o755)
    # Try to open existing file
    try:
        history_file = open("{0}/{1}".format(d, f), 'r+')
    # Open existing file failed - make new one
    except IOError:
        history_file = open("{0}/{1}".format(d, f), 'w')
    return history_file

# Misc funcs

def safe_file_name(name):
    return name.replace(" ", "_").replace(".", "_").replace("/", "_")

def apply_defaults(msg):
    # Those keys are referenced to render templates, so add empty values instead of None
    if "value" not in msg:
        msg["value"] = ""
    if "service" not in msg:
        msg["service"] = ""
    if "group" not in msg:
        msg["group"] = ""
    if "origin" not in msg:
        msg["origin"] = ""
    if "text" not in msg:
        msg["text"] = ""
    # Defaults
    if "type" not in msg:
        msg["type"] = "sysadmws-utils"
    if "environment" not in msg and "environment" in config["defaults"]:
        msg["environment"] = config["defaults"]["environment"]
    if "client" not in msg:
        if "client" in config["defaults"]:
            msg["client"] = config["defaults"]["client"]
        else:
            msg["client"] = ""
    if "attributes" not in msg:
        msg["attributes"] = {}
    if "location" not in msg["attributes"] and "location" in config["defaults"]:
        msg["attributes"]["location"] = config["defaults"]["location"]
    if "datetime" not in msg["attributes"]:
        msg["attributes"]["datetime"] = subprocess.check_output(["date", "+%F %T %z %Z"]).decode().rstrip()
    msg["force_send"] = force_send
    return msg

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
        
        parser = argparse.ArgumentParser(description="Deliver JSON notifications from stdin by rules defined in YAML config.")
        parser.add_argument("--debug", dest="debug", help="enable debug", action="store_true")
        parser.add_argument("--force-send", dest="force_send", help="force sending message", action="store_true")
        args = parser.parse_args()
        
        # Enable debug
        if args.debug:
            console_handler.setLevel(logging.DEBUG)
        
        # Set force_send
        force_send = args.force_send
    
    else:
        
        # Always debug mode if no argparse
        console_handler.setLevel(logging.DEBUG)
        
        # No force_send without argparse available
        force_send = False

    # Catch exception to logger
    try:
        logger.info(LOGO)

        # Load YAML config
        logger.info("Loading YAML config {work_dir}/{config_file}".format(work_dir=WORK_DIR, config_file=CONFIG_FILE))
        config = load_yaml_config(WORK_DIR, CONFIG_FILE)

        # Check if enabled in config
        if "enabled" not in config or config["enabled"] != True:
            logger.error("{name} not enabled in config, exiting".format(name=NAME))
            sys.exit(1)

        logger.info("Starting {name}".format(name=NAME))

        # Read json message from stdin
        try:
            message = load_json(sys.stdin)
        except Exception as e:
            logger.error("load_json failed, sending error")
            message = {
                "severity": SEVERITY_MINOR,
                "service": SELF_SERVICE,
                "resource": socket.gethostname(),
                "event": "notify_devilry_msg_read_failure",
                "value": str(type(e).__name__),
                "group": SELF_GROUP,
                "origin": SELF_ORIGIN,
                "text": str(e)
            }
        
        # Log before any changes
        logger.info("Message before any changes:")
        logger.info(message)
        
        # Check needed keys
        check_json_key("severity", message)
        check_json_key("resource", message)
        check_json_key("event", message)

        # Add fixed keys and defaults
        message = apply_defaults(message)
        
        # Log after changes
        logger.info("Message after changes:")
        logger.info(message)
        logger.info("Message combo keys: {0}, {1}, {2}, {3}".format(message["environment"], message["resource"], message["event"], message["severity"]))

        # Use some key combination to detect similiar messages and rate limit them
        key_combo = "{0}_{1}_{2}_{3}".format(
            safe_file_name(message["environment"]),
            safe_file_name(message["resource"]),
            safe_file_name(message["event"]),
            safe_file_name(message["severity"])
        )

        # Open history message in file
        with open_history_message_file(HISTORY_DIR, "{0}_{1}.{2}".format(HISTORY_MESSAGE_IN_PREFIX, key_combo, HISTORY_MESSAGE_SUFFIX)) as history_in_file:
            
            # Load last 2 messages in time, used to understrand that similiar messages stopped and we need to reset rate limit
            last_1_message_in_time = history_load_message_in(history_in_file, key="last_1")
            last_2_message_in_time = history_load_message_in(history_in_file, key="last_2")
            logger.info("Loaded last message times: {0}, {1}".format(last_2_message_in_time, last_1_message_in_time))
            logger.info("Current message time: {0}".format(UT_NOW))
            
            # Shift and save history for the next iteration
            history_save_message_in(history_in_file, last_2=last_1_message_in_time, last_1=UT_NOW)

        # Check times of similiar messages, allow drift in times up to 2 minutes
        if last_1_message_in_time is not None and last_2_message_in_time is not None:
            
            # Minutes between current and last  = A
            # Minutes between last and before-last = B
            # Minutes between current and before-last  = C
            # Diff between A and B = X
            int_A = int((UT_NOW - last_1_message_in_time) / 60)
            int_B = int((last_1_message_in_time - last_2_message_in_time) / 60)
            int_C = int((UT_NOW - last_2_message_in_time) / 60)
            int_X = int_A - int_B

            if int_C <= 7:

                # Sim messages are not supposed to be sent more often than each 5 min
                # So if we have 5 minutes plus 2 minutes on deviation = 7 minutes between current and before last message it could be sender bug and duplicatate
                # So detect sim messages
                sim_messages_detected = True
                logger.info("Similiar messages detected because diff between current and before last message is less than 7 minutes")

            else:

                if int_X <= 2:
                    
                    # X <= 2 means that A is not 2 minutes bigger than B, so similiar messages come regularly (with up to 2 minutes deviation)
                    # Similiar messages detected
                    sim_messages_detected = True
                    logger.info("Similiar messages detected")
                
                else:
                    
                    # X > 2 means that messages are likely similiar, but came not regularly, so we think it is a new message and force sim messages not detected
                    # Similiar messages not detected
                    sim_messages_detected = False
                    logger.info("Similiar messages not detected")
        
        else:
            
            # Similiar messages not detected
            sim_messages_detected = False
            logger.info("Similiar messages not detected")
        
        # But do not allow more than 24h between last_1 and now
        if last_1_message_in_time is not None:
            
            if int((UT_NOW - last_1_message_in_time)/60) > 1440:
                
                # Similiar messages not detected
                sim_messages_detected = False
                logger.info("There is more than 24 hours between last message and now, forcing similiar messages not detected")

        # But if force_send == True - send anyway
        if force_send:
                
            sim_messages_detected = False
            logger.info("--force-send forcing similiar messages as not detected")

        # Chain func
        def chain(message, indent, specific_chain=None):

            # Check indent level
            if indent > MAX_INDENT:
                logger.warning("Max indent level {n} detected, probably it is a chain loop".format(n=indent))
                return

            # Warn if specific chain not exists
            if specific_chain is not None and specific_chain not in config["chains"]:
                logger.warning("Specific chain {chain} not found".format(chain=specific_chain))

            # Iterate over all chains on start
            for chain_name, chain_rules in config["chains"].items():

                # Check specific chain
                if specific_chain is not None and chain_name != specific_chain:
                    continue

                logger.info("Chain {indent}> {chain_name}".format(indent="=" * indent, chain_name=chain_name))

                # Check entrypoint key in the first rule of this chain and skip chain if not found
                if specific_chain is None and "entrypoint" not in chain_rules[0] or ("entrypoint" in chain_rules[0] and chain_rules[0]["entrypoint"] != True):
                    logger.info("Entrypoint in rule 0 not found, skipping this chain")
                    continue

                # Iterate over chain rules
                for rule in chain_rules:

                    logger.info("Chain {chain} rule {rule}".format(chain=chain_name, rule=rule["name"]))

                    # Check needed actions in rule
                    actions_found = 0
                    if "suppress" in rule:
                        actions_found+=1
                    if "set" in rule:
                        actions_found+=1
                    if "jump" in rule:
                        actions_found+=1
                    if "send" in rule:
                        actions_found+=1
                    if actions_found == 0 or actions_found > 1:
                        logger.warning("Chain {chain} rule {rule} containes no actions or more than one action from [suppress, set, jump, send] list".format(chain=chain_name, rule=rule["name"]))

                    # Match filter
                    if "match" in rule:

                        logger.info("Match filter found in {chain}/{rule}".format(chain=chain_name, rule=rule["name"]))
                        should_continue = False

                        # Loop match items
                        for match_item_key, match_item_val in rule["match"].items():

                            # Match type logic
                            if "in" in match_item_val:
                                if match_item_key not in message or message[match_item_key] not in match_item_val["in"]:
                                    should_continue = True
                            if "not_in" in match_item_val:
                                if match_item_key not in message or message[match_item_key] in match_item_val["not_in"]:
                                    should_continue = True

                        if should_continue:
                            logger.info("Match filter didn't match in {chain}/{rule}, skipping rule".format(chain=chain_name, rule=rule["name"]))
                            continue
                        else:
                            logger.info("Match filter match in {chain}/{rule}, not skipping rule".format(chain=chain_name, rule=rule["name"]))

                    else:
                        logger.info("Match filter not found in {chain}/{rule}".format(chain=chain_name, rule=rule["name"]))

                    # Suppress
                    if "suppress" in rule and rule["suppress"] == True:
                        logger.info("Suppress found in {chain}/{rule}, doing nothing".format(chain=chain_name, rule=rule["name"]))

                    # Set
                    if "set" in rule:
                        for set_key, set_val in rule["set"].items():
                            message[set_key] = set_val
                        logger.info("Set found in {chain}/{rule}, modified message:".format(chain=chain_name, rule=rule["name"]))
                        logger.info(message)

                    # Jump
                    if "jump" in rule:
                        for jump_chain in rule["jump"]:
                            # Call specific chain with immutable message
                            logger.info("Jump found in {chain}/{rule}, calling chain {jump_chain}".format(chain=chain_name, rule=rule["name"], jump_chain=jump_chain))
                            chain(copy.deepcopy(message), indent + 1, jump_chain)
                    
                    # Send
                    if "send" in rule:

                        # Iterate over available sending methods and check if every is enabled
                        for sending_method in SENDING_METHODS:

                            # Check sending method is configured in config for rule
                            if sending_method in rule["send"]:

                                logger.info("Sending method {0} enabled for rule {1}".format(sending_method, rule["name"]))
                                # We can have many contact aliases listed in each sending method, iterate over them
                                for alias in rule["send"][sending_method]:

                                    logger.info("Contact alias {0} listed for current sending method".format(alias))
                                    # Open history message in file
                                    with open_history_message_file(HISTORY_DIR, "{prefix}_{key_combo}_{chain_name}_{rule_name}_{sending_method}_{alias}.{suffix}".format(
                                        prefix=HISTORY_MESSAGE_OUT_PREFIX,
                                        key_combo=key_combo,
                                        chain_name=safe_file_name(chain_name),
                                        rule_name=safe_file_name(rule["name"]),
                                        sending_method=safe_file_name(sending_method),
                                        alias=safe_file_name(alias),
                                        suffix=HISTORY_MESSAGE_SUFFIX
                                    )) as history_out_file:

                                        # If we are not under similiar messages condition we should clear out message out counter and time, because we have a new series of messages
                                        if not sim_messages_detected:
                                            
                                            # Set out to initial values
                                            history_save_message_out(history_out_file, last=None, count=1)
                                            logger.info("Message out counter cleared out")

                                        # Load history message out (disregard the rate_limit enabled or not, we may enable it in future)
                                        last_message_out_time = history_load_message_out(history_out_file, key="last")
                                        message_out_count = history_load_message_out(history_out_file, key="count")
                                        logger.info("Last message time and message count for chain {chain} rule {rule}, sending method {sending_method}, contact alias {alias}: {last_message_out_time}, {message_out_count}".format(
                                            chain=chain_name,
                                            rule=rule["name"],
                                            sending_method=sending_method,
                                            alias=alias,
                                            last_message_out_time=last_message_out_time,
                                            message_out_count=message_out_count
                                        ))

                                        # Check loaded values and set should_send value
                                        if last_message_out_time is None or message_out_count == 0:
                                            
                                            logger.info("Last message time is None or messages count is 0, sending anyway")
                                            should_send = True
                                        
                                        else:

                                            # Init value before checks
                                            should_send = False

                                            # Check if rate limit is set for this rule (rate limits are set per rule in yaml config, but saved/loaded/checked also per sending method and contact alias)
                                            # And check if we are under similiar messages condition
                                            if "rate_limit" in rule and sim_messages_detected:

                                                logger.info("Rate limit configured for rule {0} and similiar messages detected".format(rule["name"]))
                                                
                                                # Decide which rate limit level to choose
                                                # If we have already sent more messages than items on rate limit, use the last one
                                                if message_out_count - 2 >= len(rule["rate_limit"]):
                                                    rate_limit_level = rule["rate_limit"][len(rule["rate_limit"]) - 1]
                                                # Else take the rate limit level according to the number of messages sent
                                                else:
                                                    rate_limit_level = rule["rate_limit"][message_out_count - 2]
                                                
                                                # Decide if we have to send this message or pass to the next sending method
                                                # If time passed since last message in minutes more or equal our level
                                                time_from_last_message = (UT_NOW - last_message_out_time) / 60
                                                logger.info("Took rate limit: {0}, time from last message: {1}".format(rate_limit_level, time_from_last_message))
                                                if time_from_last_message >= rate_limit_level:
                                                    
                                                    # Send the message with this sending method and alias
                                                    should_send = True
                                                    logger.info("Time from last message is bigger than rate limit, should send")
                                            
                                            # Else no rate limitng, always send
                                            else:
                                                
                                                should_send = True
                                                logger.info("Rate limit not enabled for rule {0} or similiar messages not detected".format(rule["name"]))
                                        
                                        # Check shoud_send and send
                                        if should_send:
                                            
                                            # Get sending method settings per contact alias in yaml config
                                            alias_settings = config[sending_method][alias]

                                            # Set env vars if needed
                                            if "env" in config:
                                                for env in config["env"]:
                                                    os.environ[env] = config["env"][env]
                                            
                                            # Even if sending failed, catch and show exception and try sending next items (contact aliases) and methods
                                            try:
                                                
                                                logger.info("Sending message for chain {0} rule {1} via {2} for contact alias {3}".format(chain_name, rule["name"], sending_method, alias))
                                                send_message(sending_method, alias_settings, message)
                                                
                                                # Save successful message out per this rule and sending method and contact alias in history
                                                history_save_message_out(history_out_file, last=UT_NOW, count=message_out_count + 1)
                                            
                                            except Exception as e:
                                                logger.warning("Caught exception on sending:")
                                                logger.exception(e)
                                        
                                        # Else just log
                                        else:
                                            logger.info("Rate limit applied, message not sent for chain {chain} rule {rule}, sending method {sending_method}, contact alias {alias}".format(
                                                chain=chain_name,
                                                rule=rule["name"],
                                                sending_method=sending_method,
                                                alias=alias
                                            ))
                    # Chain break
                    if "chain_break" in rule:
                        logger.info("Chain break found in {chain}/{rule}, breaking chain".format(chain=chain_name, rule=rule["name"]))
                        break

        # Call chain with incoming message and zero indent, make message immutable by deepcopy
        chain(copy.deepcopy(message), 0)
    
    # Reroute catched exception to log
    except Exception as e:
        logger.exception(e)

    logger.info("Finished {name}".format(name=NAME))
