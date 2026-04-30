#!/usr/bin/python3

# Sometimes whois server should be specified manually, to check current authoritative server for a domain use:
# $ whois com | grep whois
# whois:        whois.verisign-grs.com
# $ whois ws | grep whois
# whois:        whois.website.ws

import click
import whoisdomain # pip3 install whoisdomain
import datetime
import requests
from pprint import pprint

RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"

def rdap_get_expiration(domain):
    tld = domain.split(".")[-1].lower()

    bootstrap_resp = requests.get(RDAP_BOOTSTRAP_URL, timeout=10)
    bootstrap_resp.raise_for_status()
    bootstrap = bootstrap_resp.json()

    rdap_server = None
    for tlds, servers in bootstrap["services"]:
        if tld in [t.lower() for t in tlds]:
            rdap_server = servers[0]
            break

    if rdap_server is None:
        raise Exception("No RDAP server found for TLD: .{}".format(tld))

    rdap_url = rdap_server.rstrip("/") + "/domain/" + domain
    resp = requests.get(rdap_url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    for event in data.get("events", []):
        if event.get("eventAction") == "expiration":
            dt = datetime.datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt

    return None

@click.command()
@click.option("--domain", required=True, help="Domain to check")
@click.option("--warning", type=click.INT, default=(28 * 24 * 60), help="Minutes to warning, default 28 * 24 * 60 (4 weeks)")
@click.option("--critical", type=click.INT, default=(7 * 24 * 60), help="Minutes to critical, default 7 * 24 * 60 (1 week)")
@click.option("--no-cache", is_flag=True, default=False, help="Do not use cache file, optional")
@click.option("--server", type=click.STRING, default=None, help="Whois server to use, optional")
@click.option("--rdap", is_flag=True, default=False, help="Use RDAP protocol instead of WHOIS")
def main(domain, warning, critical, no_cache, server, rdap):

    exit_code = 0
    try:
        if rdap:
            expiration_date = rdap_get_expiration(domain)
            if expiration_date is None:
                print("CRITICAL: Domain {domain} has no expiration date".format(domain=domain))
                exit(2)
            minutes = int((expiration_date - datetime.datetime.now()).total_seconds() / 60)
            if minutes < critical:
                print("CRITICAL: Domain {domain} expires in {minutes} minutes ({days} days)".format(domain=domain, minutes=minutes, days=int(minutes / 60 / 24)))
                exit_code = 2
            elif minutes < warning:
                print("WARNING: Domain {domain} expires in {minutes} minutes ({days} days)".format(domain=domain, minutes=minutes, days=int(minutes / 60 / 24)))
                exit_code = 1
            else:
                print("OK: Domain {domain} expires in {minutes} minutes ({days} days)".format(domain=domain, minutes=minutes, days=int(minutes / 60 / 24)))
            exit(exit_code)
        else:
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
