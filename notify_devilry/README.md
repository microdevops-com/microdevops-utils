# notify_devilry

`notify_devilry` acts as a router between local server notification sources and remote service destinations.
There was a typo in the word `delivery`, but it remains as a part of the name now :) .

`notify_devilry` helps to:
- Route server notifications (monitring alerts, events etc) to humans via chats and to services via APIs.
- Decentralize server monitoring (all servers send to chats independently with no central hub to avoid central monitoring service failure or misconfiguration).
- Centralize server monitoring alerts and events in central monitoring service.
- Mirror notifications to several destinations based on notification key values.
- Rate limit notifications for humans to avoid noise in chats.
- Suppress notifications for humans at non working hours.
- Map notification keys for different destinations.

All `sysadmws-utils` components use `notify_devilry` to send notifications.

`notify_devilry` mostly follows [alerta](https://docs.alerta.io/en/latest/server.html) [Design Principles](https://docs.alerta.io/en/latest/design.html)
and [Conventions](https://docs.alerta.io/en/latest/conventions.html) to be compatible with `alerta` as one of possible API endpoints.

Local server notifications sources should send notifications as JSON via stdin.

Remote services supported:
- [alerta](https://docs.alerta.io/en/latest/server.html) - to bump alerts with notifications
- [telegram](https://telegram.org) - to send notifications as messages to chats

# Notification keys scheme with examples

_*_ - mandatory keys

- `source` - notification source name
  - `sysadmws-utils`
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
- `client` - could be used to choose different `alerta` destinations with different per customer keys, different `chat_id`s in `telegram`
- `environment`\*
  - `prod`
  - `staging`
  - `dev`
  - `infra`
  - `legacy`
- `service` and `resource`\*
  - `server`
    - `srv1.example.com`
    - `srv1.example.com:mysql`
    - `srv1.example.com:/`
    - `srv1.example.com:/mnt/partition`
  - `website`
    - `https://example.com/`
  - `dns`
    - `example.com`
- `event`\*
  - `host heartbeat lost`
  - `replication lag`
  - `partition full`
  - `certificate expiry`
  - `domain expiry`
- `group` - event group
  - `host heartbeat`
  - `replication`
  - `disk`
  - `certificate`
  - `domain`
- `value`
  - `30s`
  - `60s`
  - `99%`
  - `5d`
  - `10d`
- `text`
  - `host heartbeat lost for 30 seconds`
  - `mysql slave is 60 seconds behind master`
  - `partition is 99% full, 100 Mb available`
  - `certificate will expire in 5 days`
  - `domain will expire in 10 days`
- `origin`
  - `heartbeat_mesh`
  - `disk_alert`
  - `mysql_replica_checker`
  - `website_checker`
- `attributes` - any key value pair with additional data
  - `date time`: `1970-01-01 00:00:00 EEST`
- `type`
  - `sysadmws-utils`
- `timeout` - override default alert timeout value

# Rate Limit
`notify_devilry` can rate limit notifications with `rate_limit` YAML config key per `notify` destination.
It has no practical sense for routing to `alerta` as it has its own [De-Duplication](https://docs.alerta.io/en/latest/server.html#de-duplication) mechanisms,
but helps humans to receive less messages via chats.

It uses `environment`, `resource`, `event` and `severity` notification keys to detect similiar notifications.
