#!/usr/bin/python

import os
import shutil
import sys
import datetime
import yaml
import urllib
import urllib2
import logging
from collections import OrderedDict
try:
    import json
except ImportError:
    import simplejson as json
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

# Constants
WORK_DIR = "/opt/sysadmws-utils/notify_devilry"
CONFIG_FILE = "notify_devilry.yaml.jinja"

# Set logging format and show up to debug
logging.basicConfig(format='{} %(levelname)s: %(message)s'.format(datetime.datetime.now().strftime("%F %T")),level=logging.DEBUG)

# Custom Exceptions
class LoadJsonError(Exception):
    pass
class CheckJsonKeyError(Exception):
    pass
#class LoadYamlConfigError(Exception):
#    pass

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
                raise LoadJsonError("Reading JSON message from file '{}' failed".format(f))
    return message

# Check needed key in dict
def check_json_key(key, msg):
    if not key in msg:
        raise CheckJsonKeyError("No '{}' key in JSON message '{}'".format(key, msg))

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
    logging.info("current_date = {}".format(current_date))
    logging.info("current_time = {}".format(current_time))
    config_dict = yaml.load(template.render(
        current_date = int(current_date),
        current_time = int(current_time)
    ))
    return config_dict

# Send methods
# Telegram
def send_telegram(token, chat_id, msg):
    # Format message as text
    message_as_text = ""
    for m_key, m_val in msg.items():
        message_as_text = "{}{}: <b>{}</b>\n".format(message_as_text, m_key, m_val)
    url_url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    url_data = urllib.urlencode({"parse_mode": "HTML", "chat_id": chat_id, "text": message_as_text })
    url_obj = urllib2.urlopen(url_url, url_data)
    url_result = url_obj.read()
    logging.info("Sending to TG API result: {}".format(url_result))

if __name__ == "__main__":

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
        logging.warning("notify_devilry not enabled in config, exiting")
        sys.exit(1)

    logging.info("Starting notify_devilry")

    # Iterate over notify dict and send message for each
    for notify_item in config_dict['notify_devilry']['notify']:
        # In case notify item has a match filter
        should_continue = False
        if 'match' in notify_item:
            # Check and skip item if not matched
            for match_item_key, match_item_val in notify_item['match'].items():
                if message[match_item_key] != match_item_val:
                    should_continue = True
        if should_continue:
            continue
        # Should send telegram, iterate over telegram aliases
        if 'telegram' in notify_item:
            for telegram_item in notify_item['telegram']:
                # Even if sending failed, catch and show exception and try send next methods
                try:
                    send_telegram(config_dict['notify_devilry']['telegram'][telegram_item]['token'], config_dict['notify_devilry']['telegram'][telegram_item]['chat_id'], message)
                except Exception as e:
                    logging.exception(e)

    logging.info("Finished notify_devilry")
