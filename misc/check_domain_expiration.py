#!/usr/bin/python3

# Sometimes whois server should be specified manually, to check current authoritative server for a domain use:
# $ whois com | grep whois 
# whois:        whois.verisign-grs.com
# $ whois ws | grep whois
# whois:        whois.website.ws

import click
import whoisdomain # pip3 install whoisdomain
import datetime
from pprint import pprint

@click.command()
@click.option("--domain", required=True, help="Domain to check")
@click.option("--warning", type=click.INT, default=(28 * 24 * 60), help="Minutes to warning, default 28 * 24 * 60 (4 weeks)")
@click.option("--critical", type=click.INT, default=(7 * 24 * 60), help="Minutes to critical, default 7 * 24 * 60 (1 week)")
@click.option("--no-cache", is_flag=True, default=False, help="Do not use cache file, optional")
@click.option("--server", type=click.STRING, default=None, help="Whois server to use, optional")
def main(domain, warning, critical, no_cache):

    exit_code = 0
    try:
        query_success = False
        # We ignore return code because the whoisdomain command itself does retries to different servers and return 1 if retries made
        # Try query 3 times
        for i in range(3):
            try:
                query = whoisdomain.query(domain=domain, cache_file="/opt/microdevops/misc/check_domain_expiration.cache", ignore_returncode=True, force=no_cache, server=server)
            except Exception as e:
                print("WARNING: {exception}".format(exception=e))
                continue
            else:
                query_success = True
                break
        if not query_success:
            print("CRITICAL: Unable to query domain {domain}".format(domain=domain))
            exit(2)
        if query.expiration_date is None:
            print("CRITICAL: Domain {domain} has no expiration date".format(domain=domain))
            exit_code = 2
        else:
            expiration_date = query.expiration_date
            minutes = int((expiration_date - datetime.datetime.now()).total_seconds() / 60)
            if minutes < critical:
                print("CRITICAL: Domain {domain} expires in {minutes} minutes ({days} days)".format(domain=domain, minutes=minutes, days=int(minutes / 60 / 24)))
                exit_code = 2
            elif minutes < warning:
                print("WARNING: Domain {domain} expires in {minutes} minutes ({days} days)".format(domain=domain, minutes=minutes, days=int(minutes / 60 / 24)))
                exit_code = 1
            else:
                print("OK: Domain {domain} expires in {minutes} minutes ({days} days)".format(domain=domain, minutes=minutes, days=int(minutes / 60 / 24)))
    except Exception as e:
        print("CRITICAL: {exception}".format(exception=e))
        exit(2)
    else:
        pprint(vars(query))
        exit(exit_code)

if __name__ == "__main__":
    main()
