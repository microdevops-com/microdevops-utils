#!/usr/bin/env bats

setup() {
  TEST_TMP="$(mktemp -d)"
  STUB_BIN="$TEST_TMP/bin"
  mkdir -p "$STUB_BIN"
  BULK_LOG_SCRIPT="$BATS_TEST_DIRNAME/../bulk_log.sh"
}

teardown() {
  rm -rf "$TEST_TMP"
}

write_stub() {
  local name="$1"
  cat >"$STUB_BIN/$name"
  chmod +x "$STUB_BIN/$name"
}

install_basic_stubs() {
  write_stub top <<'EOS'
#!/bin/bash
echo "top ok"
EOS

  write_stub ps <<'EOS'
#!/bin/bash
echo "ps ok"
EOS

  write_stub free <<'EOS'
#!/bin/bash
echo "free ok"
EOS

  write_stub uptime <<'EOS'
#!/bin/bash
echo "uptime ok"
EOS

  write_stub ping <<'EOS'
#!/bin/bash
echo "ping args: $*"
EOS

  write_stub w <<'EOS'
#!/bin/bash
echo "w ok"
EOS

  write_stub df <<'EOS'
#!/bin/bash
echo "df ok"
EOS
}

run_bulk_log() {
  run env \
    BULK_LOG_PATH="$STUB_BIN:/usr/bin:/bin" \
    BULK_LOG_TIMEOUT_SECONDS="${BULK_LOG_TIMEOUT_SECONDS:-2}" \
    BULK_LOG_LEGACY_NET_TOOLS_ENABLED="${BULK_LOG_LEGACY_NET_TOOLS_ENABLED:-0}" \
    BULK_LOG_IOTOP_ENABLED="${BULK_LOG_IOTOP_ENABLED:-0}" \
    BULK_LOG_PING_TARGET="9.9.9.9" \
    bash "$BULK_LOG_SCRIPT"
}

line_for_heading() {
  local heading="$1"
  printf '%s\n' "$output" | nl -ba | awk -v h="$heading" '$0 ~ "\\t### " h "$" {print $1; exit}'
}

@test "skips gateway ping when default route is unavailable" {
  install_basic_stubs

  write_stub ip <<'EOS'
#!/bin/bash
if [ "$1" = "-o" ] && [ "$2" = "route" ] && [ "$3" = "show" ] && [ "$4" = "to" ] && [ "$5" = "default" ]; then
  exit 0
fi
if [ "$1" = "neigh" ]; then
  echo "10.0.0.1 dev lo lladdr 00:00:00:00:00:00 STALE"
  exit 0
fi
if [ "$1" = "addr" ]; then
  echo "1: lo: <LOOPBACK>"
  exit 0
fi
if [ "$1" = "-s" ] && [ "$2" = "link" ]; then
  echo "1: lo"
  exit 0
fi
if [ "$1" = "route" ] && [ "$2" = "show" ] && [ "$3" = "table" ] && [ "$4" = "main" ]; then
  echo "default via 10.0.0.1 dev lo"
  exit 0
fi
exit 0
EOS

  write_stub ss <<'EOS'
#!/bin/bash
echo "ss ok"
EOS

  write_stub ethtool <<'EOS'
#!/bin/bash
echo "ethtool ok"
EOS

  run_bulk_log

  [ "$status" -eq 0 ]
  [[ "$output" == *"### ping gw"* ]]
  [[ "$output" == *"SKIP: gateway address is empty"* ]]
  [[ "$output" != *"Destination address required"* ]]
}

@test "autodetects interface from default route for ethtool" {
  install_basic_stubs

  write_stub ip <<'EOS'
#!/bin/bash
if [ "$1" = "-o" ] && [ "$2" = "route" ] && [ "$3" = "show" ] && [ "$4" = "to" ] && [ "$5" = "default" ]; then
  echo "default via 10.10.10.1 dev ens192 proto dhcp src 10.10.10.2 metric 100"
  exit 0
fi
if [ "$1" = "neigh" ]; then
  echo "10.10.10.1 dev ens192 lladdr 00:11:22:33:44:55 REACHABLE"
  exit 0
fi
if [ "$1" = "addr" ]; then
  echo "2: ens192: <BROADCAST,MULTICAST,UP,LOWER_UP>"
  exit 0
fi
if [ "$1" = "-s" ] && [ "$2" = "link" ]; then
  echo "2: ens192"
  exit 0
fi
if [ "$1" = "route" ] && [ "$2" = "show" ] && [ "$3" = "table" ] && [ "$4" = "main" ]; then
  echo "default via 10.10.10.1 dev ens192"
  exit 0
fi
exit 0
EOS

  write_stub ss <<'EOS'
#!/bin/bash
echo "ss ok"
EOS

  write_stub ethtool <<'EOS'
#!/bin/bash
echo "ethtool iface=$1"
EOS

  run_bulk_log

  [ "$status" -eq 0 ]
  [[ "$output" == *"### ethtool ens192"* ]]
  [[ "$output" == *"ethtool iface=ens192"* ]]
}

@test "continues with explicit SKIP messages when commands are missing" {
  install_basic_stubs
  BULK_LOG_IOTOP_ENABLED=1

  run_bulk_log

  [ "$status" -eq 0 ]
  [[ "$output" == *"### iotop"* ]]
  [[ "$output" == *"SKIP: command 'iotop' not found"* ]]
  [[ "$output" == *"SKIP: neither 'ss' nor 'netstat' found"* ]]
  [[ "$output" == *"SKIP: neither 'ip' nor 'arp' found"* ]]
  [[ "$output" == *"SKIP: neither 'ip' nor 'ifconfig' found"* ]]
  [[ "$output" == *"SKIP: default interface is empty"* ]]
}

@test "enforces per-command timeout and keeps running" {
  if ! command -v timeout >/dev/null 2>&1; then
    skip "timeout command not available"
  fi

  install_basic_stubs
  BULK_LOG_TIMEOUT_SECONDS=1

  write_stub ps <<'EOS'
#!/bin/bash
sleep 3
echo "ps delayed"
EOS

  run_bulk_log

  [ "$status" -eq 0 ]
  [[ "$output" == *"### ps"* ]]
  [[ "$output" == *"WARN: command timed out after 1s (rc=124)"* ]]
  [[ "$output" == *"### free"* ]]
}

@test "keeps section ordering stable" {
  install_basic_stubs

  write_stub ip <<'EOS'
#!/bin/bash
if [ "$1" = "-o" ] && [ "$2" = "route" ] && [ "$3" = "show" ] && [ "$4" = "to" ] && [ "$5" = "default" ]; then
  echo "default via 10.20.30.1 dev ens160"
  exit 0
fi
if [ "$1" = "neigh" ]; then
  echo "10.20.30.1 dev ens160 lladdr 00:11:22:33:44:55 REACHABLE"
  exit 0
fi
if [ "$1" = "addr" ]; then
  echo "2: ens160"
  exit 0
fi
if [ "$1" = "-s" ] && [ "$2" = "link" ]; then
  echo "2: ens160"
  exit 0
fi
if [ "$1" = "route" ] && [ "$2" = "show" ] && [ "$3" = "table" ] && [ "$4" = "main" ]; then
  echo "default via 10.20.30.1 dev ens160"
  exit 0
fi
exit 0
EOS

  write_stub ss <<'EOS'
#!/bin/bash
echo "ss ok"
EOS

  write_stub ethtool <<'EOS'
#!/bin/bash
echo "ethtool ok"
EOS

  run_bulk_log

  [ "$status" -eq 0 ]

  top_line="$(line_for_heading "top")"
  ps_line="$(line_for_heading "ps")"
  ping_line="$(line_for_heading "ping")"
  ss_line="$(line_for_heading "ss -an")"
  gw_line="$(line_for_heading "ping gw")"
  neigh_line="$(line_for_heading "ip neigh")"
  addr_line="$(line_for_heading "ip addr")"
  eth_line="$(line_for_heading "ethtool ens160")"
  route_line="$(line_for_heading "ip route")"
  w_line="$(line_for_heading "w")"
  df_line="$(line_for_heading "df")"

  [ -n "$top_line" ]
  [ "$top_line" -lt "$ps_line" ]
  [ "$ps_line" -lt "$ping_line" ]
  [ "$ping_line" -lt "$ss_line" ]
  [ "$ss_line" -lt "$gw_line" ]
  [ "$gw_line" -lt "$neigh_line" ]
  [ "$neigh_line" -lt "$addr_line" ]
  [ "$addr_line" -lt "$eth_line" ]
  [ "$eth_line" -lt "$route_line" ]
  [ "$route_line" -lt "$w_line" ]
  [ "$w_line" -lt "$df_line" ]
}

@test "script-level lock prevents overlapping runs" {
  if ! command -v flock >/dev/null 2>&1; then
    skip "flock command not available"
  fi

  lock_file="$TEST_TMP/bulk_log.lock"
  exec 9>"$lock_file"
  flock -n 9

  run env \
    BULK_LOG_PATH="$STUB_BIN:/usr/bin:/bin" \
    BULK_LOG_LOCK_FILE="$lock_file" \
    bash "$BULK_LOG_SCRIPT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"SKIP: another bulk_log instance is running (lock: $lock_file)"* ]]

  flock -u 9
  exec 9>&-
}

@test "cron stays simple and does not include flock" {
  run grep -E '/opt/sysadmws/bulk_log/bulk_log.sh >> /opt/sysadmws/bulk_log/bulk_log.log' "$BATS_TEST_DIRNAME/../bulk_log.cron"
  [ "$status" -eq 0 ]

  run grep -E 'flock' "$BATS_TEST_DIRNAME/../bulk_log.cron"
  [ "$status" -ne 0 ]
}

@test "logrotate config is valid in debug mode" {
  if ! command -v logrotate >/dev/null 2>&1; then
    skip "logrotate command not available"
  fi

  run logrotate -d -s "$TEST_TMP/logrotate.status" "$BATS_TEST_DIRNAME/../bulk_log.logrotate"
  [ "$status" -eq 0 ]
}
