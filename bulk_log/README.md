# bulk_log

`bulk_log.sh` collects periodic host diagnostics for post-mortem analysis.

## Runtime behavior

- Per-command timeout: `BULK_LOG_TIMEOUT_SECONDS` (default: `30`)
- External ping target: `BULK_LOG_PING_TARGET` (default: `1.1.1.1`)
- External ping count: `BULK_LOG_PING_COUNT` (default: `10`)
- DNS test enabled: `BULK_LOG_DNS_TEST_ENABLED` (`1` or `0`, default: `1`)
- DNS test hostname: `BULK_LOG_DNS_TEST_NAME` (default: `www.google.com`)
- Gateway ping enabled: `BULK_LOG_GW_PING_ENABLED` (`1` or `0`, default: `1`)
- Gateway ping count: `BULK_LOG_GW_PING_COUNT` (default: `4`)
- Force interface for `ethtool`: `BULK_LOG_IFACE` (default: auto-detected)
- Include legacy `net-tools` sections (`netstat/arp/ifconfig`): `BULK_LOG_LEGACY_NET_TOOLS_ENABLED` (`1` or `0`, default: `1`)
- Enable `iotop` section: `BULK_LOG_IOTOP_ENABLED` (`1` or `0`, default: `1`)
- Override execution `PATH` (mainly for tests): `BULK_LOG_PATH`
- Lock file path for process-level locking: `BULK_LOG_LOCK_FILE` (default: `<script_dir>/bulk_log.lock`)

## Scheduling

Cron can remain simple because locking is handled inside `bulk_log.sh`:

```cron
*/2 * * * * root /opt/sysadmws/bulk_log/bulk_log.sh >> /opt/sysadmws/bulk_log/bulk_log.log
```

## Tests

Automated tests are in `bulk_log/tests/bulk_log.bats`.

Run checks with:

```bash
bulk_log/tests/run.sh
```

This runs `bash -n`, then `shellcheck` and `bats` when available.

## Collected diagnostics

Alongside classic sections (`top`, `ps`, `ping`, network info), the utility now also attempts:

- `uname -a`, `/etc/os-release`
- `vmstat`, `mpstat`, `iostat`
- DNS lookup (`getent`/`host`/`nslookup` fallback)
- `ss -s`
- `dmesg` tail
- `systemctl --failed`, warning-level `journalctl` tail
- `lsof` head
- `who -b`, `last -x` head

All sections are best-effort and automatically skipped if command is missing.
