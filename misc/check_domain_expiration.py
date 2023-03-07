#!/usr/bin/python3

import click
import whois # pip3 install whois
import datetime
from pprint import pprint

@click.command()
@click.option("--domain", required=True, help="Domain to check")
@click.option("--days-warning", type=click.INT, default=28, help="Days to warning, default 28")
@click.option("--days-critical", type=click.INT, default=7, help="Days to critical, default 7")
def main(domain, days_warning, days_critical):

    exit_code = 0
    try:
        query = whois.query(domain)
        if query.expiration_date is None:
            exit_code = 2
        else:
            expiration_date = query.expiration_date
            days = (expiration_date - datetime.datetime.now()).days
            if days < days_critical:
                print("CRITICAL: Domain %s expires in %d days" % (domain, days))
                exit_code = 2
            elif days < days_warning:
                print("WARNING: Domain %s expires in %d days" % (domain, days))
                exit_code = 1
            else:
                print("OK: Domain %s expires in %d days" % (domain, days))
    except Exception as e:
        print("CRITICAL: %s" % e)
        exit(2)
    else:
        pprint(vars(query))
        exit(exit_code)

if __name__ == "__main__":
    main()
