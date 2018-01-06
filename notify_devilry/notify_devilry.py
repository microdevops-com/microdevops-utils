#!/usr/bin/python

import os
import shutil
import sys
import time
import datetime
import yaml
import urllib
try:
    from urllib.parse import urlencode
    from urllib.request import urlopen, Request
except ImportError:
    from urllib import urlencode
    from urllib2 import urlopen, Request
import logging
from logging.handlers import RotatingFileHandler
try:
    from collections import OrderedDict
except:
    pass
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
WORK_DIR = "/opt/sysadmws-utils/notify_devilry"
HISTORY_DIR = "/opt/sysadmws-utils/notify_devilry/history"
CONFIG_FILE = "notify_devilry.yaml.jinja"
LOG_DIR = "/opt/sysadmws-utils/notify_devilry/log"
LOG_FILE = "notify_devilry.log"
HISTORY_MESSAGE_IN_PREFIX = "in"
HISTORY_MESSAGE_OUT_PREFIX = "out"
HISTORY_MESSAGE_SUFFIX = "json"
SENDING_METHODS = ['telegram']

# Custom Exceptions
class LoadJsonError(Exception):
    pass

# Load JSON from stdin
def load_json(f):
    try:
        message = json.load(f, object_pairs_hook=OrderedDict)
    except:
        try:
            message = json.load(f)
        except:
            try:
                stdin_data = f.read()
                message = json.loads(stdin_data)
            except:
                raise LoadJsonError("Reading JSON message from file '{0}' failed".format(f))
    return message

# Check needed key in dict
def check_json_key(key, msg):
    if not key in msg:
        raise LoadJsonError("No '{0}' key in JSON message '{1}'".format(key, msg))

# Load YAML config
def load_yaml_config(d, f):
    # Get in the env
    j2_env = Environment(loader=FileSystemLoader(d), trim_blocks=True)
    # our config is a template
    try:
        template = j2_env.get_template(f)
    except TemplateNotFound:
        # It is ok if no config file, display no error, return None
        return None
    # Set vars inside config file and render
    current_date = datetime.datetime.now().strftime("%Y%m%d")
    current_time = datetime.datetime.now().strftime("%H%M%S")
    logger.info("Loading JSON config {0}/{1}".format(d, f))
    logger.info("current_date = {0}".format(current_date))
    logger.info("current_time = {0}".format(current_time))
    config_dict = yaml.load(template.render(
        current_date = int(current_date),
        current_time = int(current_time)
    ))
    return config_dict

# Alias for now unix timestamp
def ut_now():
    return int(time.time())

# Send methods
# Telegram
def send_telegram(token, chat_id, msg):
    # Format message as text
    message_as_text = ""
    for m_key, m_val in msg.items():
        message_as_text = "{0}{1}: <b>{2}</b>\n".format(message_as_text, m_key, m_val)
    url_url = "https://api.telegram.org/bot{0}/sendMessage".format(token)
    url_data = urlencode({"parse_mode": "HTML", "chat_id": chat_id, "text": message_as_text }).encode("utf-8")
    url_req = Request(url_url)
    url_obj = urlopen(url_req, url_data)
    url_result = url_obj.read()
    logger.info("Sending to TG API result: {0}".format(url_result))

# Universal send method
def send_message(sending_method, sending_method_item_settings, message):
    if sending_method == "telegram":
        token = sending_method_item_settings['token']
        chat_id = sending_method_item_settings['chat_id']
        send_telegram(token, chat_id, message)

# History methods
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

# History file methods
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

if __name__ == "__main__":

    # Set logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    if not os.path.isdir(LOG_DIR):
        os.mkdir(LOG_DIR, 0o755)
    log_handler = RotatingFileHandler("{0}/{1}".format(LOG_DIR, LOG_FILE), maxBytes=10485760, backupCount=10)
    log_handler.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    formatter = logging.Formatter('{0} %(name)s %(levelname)s: %(message)s'.format(datetime.datetime.now().strftime("%F %T")))
    log_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    logger.addHandler(console_handler)

    # Set parser
    if ARGPARSE:
        parser = argparse.ArgumentParser(description='Deliver JSON message from stdin by rules defined in YAML config.')
        parser.add_argument("--debug", dest="debug", help="enable debug", action="store_true")
        args = parser.parse_args()
        if args.debug:
            console_handler.setLevel(logging.DEBUG)
    else:
        # Always debug mode if no argparse
        console_handler.setLevel(logging.DEBUG)

    # Catch exception to logger
    try:
        # Load YAML config
        config_dict = load_yaml_config(WORK_DIR, CONFIG_FILE)
        # If config is None just exit silently
        if config_dict is None:
            sys.exit(1)

        # Read json message from stdin
        message = load_json(sys.stdin)
        # Check needed keys
        check_json_key("host", message)
        check_json_key("from", message)

        # Check if enabled in config
        if not config_dict['notify_devilry']['enabled']:
            logger.warning("notify_devilry not enabled in config, exiting")
            sys.exit(1)

        logger.info("Starting notify_devilry")

        # Use some key combination to detect similiar messages and rate limit them
        key_combo = "{0}_{1}_{2}_{3}".format(message['host'].replace(" ", "_").replace(".", "_"), message['from'].replace(" ", "_"), message['type'].replace(" ", "_"), message['status'].replace(" ", "_"))

        # Open history message in file
        with open_history_message_file(HISTORY_DIR, "{0}_{1}.{2}".format(HISTORY_MESSAGE_IN_PREFIX, key_combo, HISTORY_MESSAGE_SUFFIX)) as history_in_file:
            # Load last 2 messages in time, used to understrand that similiar messages stopped and we need to reset rate limit
            last_1_message_in_time = history_load_message_in(history_in_file, key="last_1")
            last_2_message_in_time = history_load_message_in(history_in_file, key="last_2")
            logger.info("Loaded last message times: {0}, {1}".format(last_2_message_in_time, last_1_message_in_time))
            # Shift and save history for the next iteration
            history_save_message_in(history_in_file, last_2=last_1_message_in_time, last_1=ut_now())

        # Check times of similiar messages, allow drift in times up to 2 minutes
        if last_1_message_in_time is not None and last_2_message_in_time is not None:
            if (int((ut_now() - last_1_message_in_time)/60) - int((last_1_message_in_time - last_2_message_in_time)/60)) <= 2:
                # Similiar messages detected
                sim_messages_detected = True
                logger.info("Similiar messages detected")
            else:
                # Similiar messages not detected
                sim_messages_detected = False
                logger.info("Similiar messages not detected")
        else:
            # Similiar messages not detected
            sim_messages_detected = False
            logger.info("Similiar messages not detected")
        # But do not allow more than 24h between last_1 and now
        if last_1_message_in_time is not None:
            if int((ut_now() - last_1_message_in_time)/60) > 1440:
                # Similiar messages not detected
                sim_messages_detected = False
                logger.info("There is more than 24 hours between last message and now, forcing similiar messages not detected")

        # Iterate over notify dict and send message for each
        for notify_item_name, notify_item in config_dict['notify_devilry']['notify'].items():
            # In case notify item has a match filter
            if 'match' in notify_item:
                logger.info("Match filter enabled")
                should_continue = False
                # Check match filter and skip item if not matched
                for match_item_key, match_item_val in notify_item['match'].items():
                    if message[match_item_key] != match_item_val:
                        should_continue = True
                        logger.info("Match filter matched all keys for notify item '{0}'".format(notify_item_name))
                if should_continue:
                    logger.info("Match filter didn't match all keys, skipping notify item '{0}'".format(notify_item_name))
                    continue
            else:
                logger.info("Match filter not enabled")
            # Iterate over available sending methods and check if every is enabled
            for sending_method in SENDING_METHODS:
                # Check sending method is configured in config for notify item
                if sending_method in notify_item:
                    logger.info("Sending method '{0}' enabled for notify item {1}".format(sending_method, notify_item_name))
                    # We can have many contact aliases listed in each sending method, iterate over them
                    for sending_method_item in notify_item[sending_method]:
                        logger.info("Contact alias '{0}' listed for current sending method".format(sending_method_item))
                        # Open history message in file
                        with open_history_message_file(HISTORY_DIR, "{0}_{1}_{2}_{3}_{4}.{5}".format(HISTORY_MESSAGE_OUT_PREFIX, key_combo, notify_item_name.replace(" ", "_"), sending_method.replace(" ", "_"), sending_method_item.replace(" ", "_"), HISTORY_MESSAGE_SUFFIX)) as history_out_file:
                            # If we are not under similiar messages condition we should clear out message out counter and time, because we have a new series of messages
                            if not sim_messages_detected:
                                # Set out to initial values
                                history_save_message_out(history_out_file, last=None, count=1)
                                logger.info("Message out counter cleared out")
                            # Load history message out (disregard the rate_limit enabled or not, we may enable it in future)
                            last_message_out_time = history_load_message_out(history_out_file, key="last")
                            message_out_count = history_load_message_out(history_out_file, key="count")
                            logger.info("Last message time and message count for notify intem '{0}', sending method '{1}', contact alias '{2}': {3}, {4}".format(notify_item_name, sending_method, sending_method_item, last_message_out_time, message_out_count))
                            if last_message_out_time is None or message_out_count == 0:
                                logger.info("Last message time is None or messages count is 0, sending anyway")
                                should_send = True
                            else:
                                # Init value before checks
                                should_send = False
                                # Check if rate limit is set for this notify item (rate limits are set per notify item in yaml config, but saved/loaded/checked per sending method and contact alias)
                                # And check if we are under similiar messages condition
                                if "rate_limit" in notify_item and sim_messages_detected:
                                    logger.info("Rate limit enabled for notify item '{0}' and similiar messages detected".format(notify_item_name))
                                    # Decide which rate limit level to choose
                                    # If we have already sent more messages than items on rate limit, use the last one
                                    if message_out_count-2 >= len(notify_item['rate_limit']):
                                        rate_limit_level = notify_item['rate_limit'][len(notify_item['rate_limit'])-1]
                                    # Else take the rate limit level according to the number of messages sent
                                    else:
                                        rate_limit_level = notify_item['rate_limit'][message_out_count-2]
                                    # Decide if we have to send this message or pass to the next sending method
                                    # If time passed since last message in minutes more or equal our level
                                    time_from_last_message = (ut_now() - last_message_out_time)/60
                                    logger.info("Took rate limit: {0}, time from last message: {1}".format(rate_limit_level, time_from_last_message))
                                    if time_from_last_message >= rate_limit_level:
                                        # Send the message with this sending method and alias
                                        should_send = True
                                        logger.info("Time from last message is bigger than rate limit, should send")
                                # Else no rate limitng, always send
                                else:
                                    should_send = True
                                    logger.info("Rate limit not enabled for notify item '{0}' or similiar messages not detected".format(notify_item_name))
                            if should_send:
                                # Get sending method settings per contact alias in yaml config
                                sending_method_item_settings = config_dict['notify_devilry'][sending_method][sending_method_item]
                                # Even if sending failed, catch and show exception and try send next items (contact aliases) and methods
                                try:
                                    logger.info("Sending message for notify item '{0}' via '{1}' for contact alias '{2}'".format(notify_item_name, sending_method, sending_method_item))
                                    send_message(sending_method, sending_method_item_settings, message)
                                    # Save successful message out per this notify item and sending method and contact alias in history
                                    history_save_message_out(history_out_file, last=ut_now(), count=message_out_count+1)
                                except Exception as e:
                                    logger.warning("Caught exception on sending:")
                                    logger.exception(e)
                            else:
                                logger.info("Rate limit applied, message not sent for notify intem '{0}', sending method '{1}', contact alias '{2}'".format(notify_item_name, sending_method, sending_method_item))
    except Exception as e:
        logger.exception(e)

    logger.info("Finished notify_devilry")
