#!/usr/bin/env bash

set -u

DEFAULT_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH="${BULK_LOG_PATH:-$DEFAULT_PATH}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BULK_LOG_LOCK_FILE="${BULK_LOG_LOCK_FILE:-${SCRIPT_DIR}/bulk_log.lock}"

BULK_LOG_TIMEOUT_SECONDS="${BULK_LOG_TIMEOUT_SECONDS:-30}"
BULK_LOG_PING_TARGET="${BULK_LOG_PING_TARGET:-1.1.1.1}"
BULK_LOG_PING_COUNT="${BULK_LOG_PING_COUNT:-10}"
BULK_LOG_DNS_TEST_ENABLED="${BULK_LOG_DNS_TEST_ENABLED:-1}"
BULK_LOG_DNS_TEST_NAME="${BULK_LOG_DNS_TEST_NAME:-www.google.com}"
BULK_LOG_GW_PING_ENABLED="${BULK_LOG_GW_PING_ENABLED:-1}"
BULK_LOG_GW_PING_COUNT="${BULK_LOG_GW_PING_COUNT:-4}"
BULK_LOG_IFACE="${BULK_LOG_IFACE:-}"
BULK_LOG_LEGACY_NET_TOOLS_ENABLED="${BULK_LOG_LEGACY_NET_TOOLS_ENABLED:-1}"
BULK_LOG_IOTOP_ENABLED="${BULK_LOG_IOTOP_ENABLED:-1}"

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

acquire_lock() {
    if ! has_cmd flock; then
        echo "WARN: command 'flock' not found, continuing without process lock"
        return 0
    fi

    if ! exec 200>"$BULK_LOG_LOCK_FILE"; then
        echo "WARN: unable to open lock file '${BULK_LOG_LOCK_FILE}', continuing without process lock"
        return 0
    fi

    if ! flock -n 200; then
        echo "SKIP: another bulk_log instance is running (lock: ${BULK_LOG_LOCK_FILE})"
        exit 0
    fi
}

is_positive_int() {
    case "$1" in
        ''|*[!0-9]*)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

if ! is_positive_int "$BULK_LOG_TIMEOUT_SECONDS"; then
    BULK_LOG_TIMEOUT_SECONDS=30
fi

if ! is_positive_int "$BULK_LOG_PING_COUNT"; then
    BULK_LOG_PING_COUNT=10
fi

if ! is_positive_int "$BULK_LOG_GW_PING_COUNT"; then
    BULK_LOG_GW_PING_COUNT=4
fi

run_with_timeout() {
    if has_cmd timeout; then
        timeout --foreground --kill-after=5 "${BULK_LOG_TIMEOUT_SECONDS}" "$@"
    else
        "$@"
    fi
}

run_section() {
    local title="$1"
    local required_cmd="$2"
    shift 2

    local start_epoch end_epoch duration rc started_at ended_at

    echo " "
    echo "### ${title}"

    if ! has_cmd "$required_cmd"; then
        echo "SKIP: command '${required_cmd}' not found"
        return 0
    fi

    started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "### start ${started_at}"
    start_epoch=$(date +%s)
    run_with_timeout "$@" 2>&1
    rc=$?
    end_epoch=$(date +%s)
    duration=$((end_epoch - start_epoch))
    ended_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    if [[ "$rc" -eq 124 || "$rc" -eq 137 ]]; then
        echo "WARN: command timed out after ${BULK_LOG_TIMEOUT_SECONDS}s (rc=${rc})"
    elif [[ "$rc" -ne 0 ]]; then
        echo "WARN: command exited with rc=${rc}"
    fi

    echo "### end ${ended_at} rc=${rc} duration=${duration}s"
    return 0
}

get_default_gateway() {
    local gw=""

    if has_cmd ip; then
        gw=$(ip -o route show to default 2>/dev/null | awk 'NR==1 {print $3}')
    fi

    if [[ -z "$gw" ]] && has_cmd route; then
        gw=$(route -n 2>/dev/null | awk '$1=="0.0.0.0" {print $2; exit}')
    fi

    echo "$gw"
}

get_default_iface() {
    local iface=""

    if [[ -n "$BULK_LOG_IFACE" ]]; then
        echo "$BULK_LOG_IFACE"
        return 0
    fi

    if has_cmd ip; then
        iface=$(ip -o route show to default 2>/dev/null | awk 'NR==1 {print $5}')
    fi

    if [[ -z "$iface" ]] && has_cmd route; then
        iface=$(route -n 2>/dev/null | awk '$1=="0.0.0.0" {print $8; exit}')
    fi

    echo "$iface"
}

run_ping_gateway_section() {
    local gateway_ip="$1"

    if [[ "$BULK_LOG_GW_PING_ENABLED" != "1" ]]; then
        echo " "
        echo "### ping gw"
        echo "SKIP: gateway ping disabled (BULK_LOG_GW_PING_ENABLED=${BULK_LOG_GW_PING_ENABLED})"
        return 0
    fi

    if ! has_cmd ping; then
        echo " "
        echo "### ping gw"
        echo "SKIP: command 'ping' not found"
        return 0
    fi

    if [[ -z "$gateway_ip" ]]; then
        echo " "
        echo "### ping gw"
        echo "SKIP: gateway address is empty"
        return 0
    fi

    run_section "ping gw" ping ping -n -c "$BULK_LOG_GW_PING_COUNT" "$gateway_ip"
}

run_iotop_section() {
    if [[ "$BULK_LOG_IOTOP_ENABLED" != "1" ]]; then
        echo " "
        echo "### iotop"
        echo "SKIP: iotop disabled (BULK_LOG_IOTOP_ENABLED=${BULK_LOG_IOTOP_ENABLED})"
        return 0
    fi

    if ! has_cmd iotop; then
        echo " "
        echo "### iotop"
        echo "SKIP: command 'iotop' not found"
        return 0
    fi

    if [[ "$(id -u)" -ne 0 ]]; then
        echo " "
        echo "### iotop"
        echo "SKIP: iotop usually requires root privileges"
        return 0
    fi

    # Disable apport traceback spam on failure to keep logs concise.
    run_section "iotop" iotop env APPORT_DISABLE=1 iotop -b -k -t -n 1
}

run_connection_section() {
    if has_cmd ss; then
        run_section "ss -an" ss ss -an
    elif has_cmd netstat; then
        run_section "netstat -an" netstat netstat -an
    else
        echo " "
        echo "### connections"
        echo "SKIP: neither 'ss' nor 'netstat' found"
    fi
}

run_neighbors_section() {
    if has_cmd ip; then
        run_section "ip neigh" ip ip neigh show
    elif has_cmd arp; then
        run_section "arp -an" arp arp -an
    else
        echo " "
        echo "### neighbors"
        echo "SKIP: neither 'ip' nor 'arp' found"
    fi
}

run_addresses_section() {
    if has_cmd ip; then
        run_section "ip addr" ip ip addr show
    elif has_cmd ifconfig; then
        run_section "ifconfig -a" ifconfig ifconfig -a
    else
        echo " "
        echo "### addresses"
        echo "SKIP: neither 'ip' nor 'ifconfig' found"
    fi
}

run_interface_stats_section() {
    if has_cmd ip; then
        run_section "ip -s link" ip ip -s link
    elif has_cmd netstat; then
        run_section "netstat -ia" netstat netstat -ia
    else
        echo " "
        echo "### interface stats"
        echo "SKIP: neither 'ip' nor 'netstat' found"
    fi
}

run_routes_section() {
    if has_cmd ip; then
        run_section "ip route" ip ip route show table main
    elif has_cmd netstat; then
        run_section "netstat -nr" netstat netstat -nr
    else
        echo " "
        echo "### routes"
        echo "SKIP: neither 'ip' nor 'netstat' found"
    fi
}

run_shell_section() {
    local title="$1"
    local required_cmd="$2"
    local shell_expr="$3"

    if ! has_cmd "$required_cmd"; then
        echo " "
        echo "### ${title}"
        echo "SKIP: command '${required_cmd}' not found"
        return 0
    fi

    run_section "$title" bash bash -c "$shell_expr"
}

run_os_release_section() {
    if [[ -r /etc/os-release ]]; then
        run_section "/etc/os-release" cat cat /etc/os-release
    else
        echo " "
        echo "### /etc/os-release"
        echo "SKIP: /etc/os-release is not readable"
    fi
}

run_dns_section() {
    if [[ "$BULK_LOG_DNS_TEST_ENABLED" != "1" ]]; then
        echo " "
        echo "### dns lookup"
        echo "SKIP: DNS lookup disabled (BULK_LOG_DNS_TEST_ENABLED=${BULK_LOG_DNS_TEST_ENABLED})"
        return 0
    fi

    if [[ -z "$BULK_LOG_DNS_TEST_NAME" ]]; then
        echo " "
        echo "### dns lookup"
        echo "SKIP: BULK_LOG_DNS_TEST_NAME is empty"
        return 0
    fi

    if has_cmd getent; then
        run_section "dns getent ${BULK_LOG_DNS_TEST_NAME}" getent getent ahosts "$BULK_LOG_DNS_TEST_NAME"
    elif has_cmd host; then
        run_section "dns host ${BULK_LOG_DNS_TEST_NAME}" host host "$BULK_LOG_DNS_TEST_NAME"
    elif has_cmd nslookup; then
        run_section "dns nslookup ${BULK_LOG_DNS_TEST_NAME}" nslookup nslookup "$BULK_LOG_DNS_TEST_NAME"
    else
        echo " "
        echo "### dns lookup"
        echo "SKIP: no DNS lookup command found (getent/host/nslookup)"
    fi
}

acquire_lock

GW_IP_ADDRESS="$(get_default_gateway)"
DEFAULT_IFACE="$(get_default_iface)"

echo "===== bulk_log snapshot ====="
echo "ts: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "host: $(hostname -f 2>/dev/null || hostname)"
echo "iface: ${DEFAULT_IFACE:-unknown}"
echo "gateway: ${GW_IP_ADDRESS:-unknown}"
echo "============================="

run_section "uname -a" uname uname -a
run_os_release_section
COLUMNS=250 run_section "top" top top -b -n 1 -c
run_section "ps" ps ps aux
run_iotop_section
run_section "free" free free -m
run_section "uptime" uptime uptime
run_section "vmstat" vmstat vmstat 1 5
run_section "mpstat" mpstat mpstat -P ALL 1 1
run_section "iostat" iostat iostat -xz 1 3
run_section "ping" ping ping -n -c "$BULK_LOG_PING_COUNT" "$BULK_LOG_PING_TARGET"
run_dns_section
run_connection_section
run_section "ss -s" ss ss -s
run_ping_gateway_section "$GW_IP_ADDRESS"
run_neighbors_section
run_addresses_section

if [[ -n "$DEFAULT_IFACE" ]]; then
    run_section "ethtool ${DEFAULT_IFACE}" ethtool ethtool "$DEFAULT_IFACE"
    run_section "ethtool -S ${DEFAULT_IFACE}" ethtool ethtool -S "$DEFAULT_IFACE"
else
    echo " "
    echo "### ethtool"
    echo "SKIP: default interface is empty"
fi

run_interface_stats_section
run_routes_section
run_shell_section "dmesg -T | tail -n 200" dmesg 'dmesg -T | tail -n 200'
run_section "systemctl --failed" systemctl systemctl --failed --no-pager
run_section "journalctl warning tail" journalctl journalctl -p warning -n 200 --no-pager

if [[ "$BULK_LOG_LEGACY_NET_TOOLS_ENABLED" = "1" ]]; then
    run_section "netstat -ia (legacy)" netstat netstat -ia
    run_section "netstat -nr (legacy)" netstat netstat -nr
    run_section "arp -an (legacy)" arp arp -an
    run_section "ifconfig -a (legacy)" ifconfig ifconfig -a
fi

run_shell_section "lsof -nPlw | head -n 300" lsof 'lsof -nPlw | head -n 300'
run_section "who -b" who who -b
run_shell_section "last -x | head -n 20" last 'last -x | head -n 20'
run_section "w" w w
run_section "df" df df -h
