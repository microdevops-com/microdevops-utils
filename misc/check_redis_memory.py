#!/usr/bin/python3

import redis
import click
import sys

@click.command()
@click.option('--redis-host', default='localhost', help='Redis host')
@click.option('--redis-port', default=6379, help='Redis port')
@click.option('--redis-password', prompt=True, hide_input=True, help='Redis password')
@click.option('--total-memory', default=49152, help='total memory (in MB)')
@click.option('--critical-threshold', default=2048, help='Critical threshold (in MB)')
@click.option('--warning-threshold', default=5120, help='Warning threshold (in MB)')
def check_redis_memory(redis_host, redis_port, redis_password, total_memory, critical_threshold, warning_threshold):

    r = redis.Redis(host=redis_host, port=redis_port, password=redis_password)
    info = r.info('memory')
    used_memory_rss = int(info['used_memory_rss'])

    # Convert used_memory_rss to MB
    used_memory_rss_mb = used_memory_rss / (1024 * 1024)

    # Print used_memory_rss in MB
    print('Used memory RSS: {:.2f} MB'.format(used_memory_rss_mb))

    available_memory = total_memory - used_memory_rss_mb

    if available_memory < critical_threshold:
        print('CRITICAL: Redis free memory is {:.2f} MB'.format(available_memory))
        sys.exit(2)
    elif available_memory < warning_threshold:
        print('WARNING: Redis free memory is {:.2f} MB'.format(available_memory))
        sys.exit(1)
    else:
        print('OK: Redis memory usage is under the thresholds')
        sys.exit(0)

if __name__ == '__main__':
    check_redis_memory()
