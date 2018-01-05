#!/usr/bin/python

from __future__ import (absolute_import, division, print_function)
import os
import shutil
import sys
import datetime
import yaml
import urllib
import urllib2
import json
import ordereddict
from jinja2 import Environment, FileSystemLoader, Template

# Constants
CONFIG_FILE = "notify_devilry.yaml.jinja"
THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Log methods
def log_notice(msg):
    now = datetime.datetime.now()
    print(now.strftime("%F %T ") + "NOTICE: " + msg, file = sys.stdout)
def log_error(msg):
    now = datetime.datetime.now()
    print(now.strftime("%F %T ") + "ERROR: " + msg, file = sys.stderr)

# Send methods
def send_telegram(token, chat_id, msg):
    log_notice("Sending to TG API result: " + urllib2.urlopen("https://api.telegram.org/bot" + token + "/sendMessage", urllib.urlencode({"parse_mode": "HTML", "chat_id": chat_id, "text": msg })).read())

if __name__ == "__main__":

    try:
        log_notice("Starting notify_devilry")

        # Set default exit code
        exit_code = 0

        # Read json message from stdin
        try:
            message = json.load(sys.stdin, object_pairs_hook=OrderedDict)
            if not 'host' in message:
                raise Exception("No 'host' key in message dict")
            if not 'from' in message:
                raise Exception("No 'from' key in message dict")
            # Format message as text
            message_as_text = ""
            for m_key, m_val in message.items():
                message_as_text = message_as_text + m_key + ": " + "<b>" + m_val + "</b>" + "\n"
        except Exception as e:
            log_error(e.message)
            exit_code = 1
            raise Exception("Reading JSON message from stdin failed, exiting")

        try:
            j2_env = Environment(loader = FileSystemLoader(THIS_DIR),trim_blocks = True)
        except Exception as e:
            log_error(e.message)

        # Get config file
        try:
            template = j2_env.get_template(CONFIG_FILE)
        except Exception as e:
            log_error(e.message)

        # Set vars inside config file and render
        try:
            current_date = datetime.datetime.now().strftime("%Y%m%d")
            current_time = datetime.datetime.now().strftime("%H%M%S")
            log_notice("current_date = " + current_date)
            log_notice("current_time = " + current_time)
            config_dict = yaml.load(template.render(
                current_date = int(current_date),
                current_time = int(current_time)
            ))
        except Exception as e:
            log_error(e.message)

        # Check if enabled in config
        try:
            if not config_dict['notify_devilry']['enabled']:
                raise Exception("notify_devilry not enabled in config, exiting")
        except:
            raise Exception("notify_devilry not enabled in config, exiting")

        # Iterate over notify dict and send message for each
        for notify_item in config_dict['notify_devilry']['notify']:
            try:
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
                        try:
                            send_telegram(config_dict['notify_devilry']['telegram'][telegram_item]['token'], config_dict['notify_devilry']['telegram'][telegram_item]['chat_id'], message_as_text)
                        except Exception as e:
                            log_error(e.message)
            except Exception as e:
                log_error(e.message)

    except Exception as e:
        log_error(e.message)

    finally:
	# Clean tmps here, if any
        log_notice("Finished notify_devilry")
        sys.exit(exit_code)
