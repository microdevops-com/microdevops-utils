# notify_devilry

`notify_devilry` acts as a router between local server notification sources and remote service destinations.
There was a typo in the word `delivery`, but it remains as a part of the name now :) .

`notify_devilry` helps to:
- Route server notifications (monitring alerts, events etc) to humans via chats and to services via APIs.
- Decentralize server monitoring (all servers send to chats independently with no central hub to avoid central monitoring service failure or misconfiguration).
- Centralize server monitoring alerts and events in central monitoring service.
- Apply rule chains if notification keys match or not, see [notify_devilry.yaml.example](./notify_devilry.yaml.example).
- Rule chains can apply actions on notifications:
  - Set notification key values, e.g. to set severity for specific resources or clients.
  - Rate limit notifications (useful for human destinations to avoid noise in chats).
  - Suppress notifications.
  - Send notifications to several destinations including other rules.
- YAML config is rendered with Jinja2 each notification, for example to modify flow for non working hours.

All `sysadmws-utils` components use `notify_devilry` to send notifications.

`notify_devilry` mostly follows [alerta](https://docs.alerta.io/en/latest/server.html) [Design Principles](https://docs.alerta.io/en/latest/design.html)
and [Conventions](https://docs.alerta.io/en/latest/conventions.html) to be compatible with `alerta` as one of possible API endpoints.

Local server notifications sources should send notifications as JSON via stdin.

Remote destination services supported:
- [alerta](https://docs.alerta.io/en/latest/server.html) - to bump alerts with notifications
- [telegram](https://telegram.org) - to send notifications as messages to chats

# Notification keys scheme with examples

_*_ - mandatory keys

- `severity`\* - according to `alerta` severity map
  - `fatal`
  - `security`
  - `critical`
  - `major`
  - `minor`
  - `warning`
  - `ok`
  - `normal`
  - `cleared`
  - `indeterminate`
  - `informational`
  - `debug`
  - `trace`
  - `unknown`
- `client` - could be used to choose different `alerta` destinations with different per customer keys, different `chat_id`s in `telegram`, default from config will apply if ommited
- `environment` - default from config will apply if ommited
  - `prod`
  - `staging`
  - `dev`
  - `infra`
  - `legacy`
- `service` (list in `alerta`, string - here) and `resource`\*
  - `server`
    - `srv1.example.com`
  - `disk`
    - `srv1.example.com:/`
    - `srv1.example.com:/mnt/partition`
  - `database`
    - `srv1.example.com:mysql`
  - `heartbeat`
    - `srv1.example.com`
  - `website`
    - `https://example.com/`
  - `dns`
    - `example.com`
- `event`\*
  - `notify_devilry_test`
  - `notify_devilry_ok`
  - `notify_devilry_critical`
  - `cmd_check_alert_cmd_ok`
  - `cmd_check_alert_cmd_retcode_not_zero`
  - `cmd_check_alert_cmd_timeout`
  - `cmd_check_alert_time_limit_ok`
  - `cmd_check_alert_time_limit_warning`
- `value`
  - `30s`
  - `60s`
  - `99%`
  - `5d`
  - `10d`
- `group` - event group
  - `notify_devilry`
  - `cmd_check_alert`
- `origin`
  - `heartbeat_mesh`
  - `disk_alert`
  - `mysql_replica_checker`
  - `website_checker`
- `attributes` - any key value pair with additional data
  - `datetime`: `1970-01-01 00:00:00 +0000 UTC`
  - `location`: `Hetzner`
- `text`
  - `host heartbeat lost for 30 seconds`
  - `mysql slave is 60 seconds behind master`
  - `partition is 99% full, 100 Mb available`
  - `certificate will expire in 5 days`
  - `domain will expire in 10 days`
- `timeout` - override default alert timeout value
- `type` - for `alerta`
  - `sysadmws-utils`
- `correlate` - for `alerta` [Correlation](https://docs.alerta.io/en/latest/server.html#simple-correlation)
  - [`notify_devilry_test`, `notify_devilry_critical`, `notify_devilry_ok`]
- `force_send` - set to True if program run with `--force-send`, can be used in match filter

# Rate limit
`notify_devilry` can rate limit notifications with `rate_limit`.

It has no practical sense for routing to `alerta` as it has its own [De-Duplication](https://docs.alerta.io/en/latest/server.html#de-duplication) mechanisms,
but helps humans to receive less messages via chats.

It uses `environment`, `resource`, `event` and `severity` notification keys to detect similiar notifications.

# Rule format
```
chains:
  # All chains are processed on new notification, specific when targeted with `jump`
  chain1:
    # Chain of rules, rules are processed one by one in this list, modifications of the notifications on each rule persist
    - name: rule example 1 # required, just a name to reference the rule and describe it
      entrypoint: True # optional, catch new incoming notification if True and in first rule in chain
      match: # optional, apply this rule only if notification matches
        key1: # key name in notification to match
          in|not_in: # match type
            - value1 # values list to match
            - value2
        key2:
          ...
      set: # optional, set notification key to value
        key1: value1
        key2: value2
      jump: # optional, list of chains to process the notification, modifications of the notifications in one chain do not persist to next chain in this list
        - chain2
        - chain3
      send: # optional
        alerta: # send alert to `alerta` aliases
          - alerta_alias1
          - alerta_alias2
        telegram: # send message to `telegram` aliases
          - telegram_alias1
          - telegram_alias2
      suppress: True # optional, do nothing actually
      chain_break: True # optional, stop processing rules in this chain
```

Each rule must have *only one* item of `set`, `jump`, `send`, `suppress`.
