# notify_devilry

`notify_devilry` acts as a router between local server notification sources and remote service destinations.
There was a typo in the word `delivery`, but it remains as a part of the name now :) .

`notify_devilry` helps to:
- Route server notifications (monitring alerts, events etc) to humans via chats and to services via APIs.
- Decentralize server monitoring (all servers send to chats independently with no central hub to avoid central monitoring service failure or misconfiguration).
- Centralize server monitoring alerts and events in central monitoring service.
- Apply rule chains if notification keys match or not, see [notify_devilry.yaml.jinja.example](./notify_devilry.yaml.jinja.example).
- Rules can apply actions on notifications:
  - Transform notification key values, e.g. to increase or decrease severity for specific resources or clients.
  - Rate limit notifications (useful for human destinations to avoid noise in chats).
  - Suppress notifications.
  - Send notifications to several destinations.
- YAML config is rendered with Jinja2 each message, for example to modify flow for non working hours.

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
- `environment`\* - default from config will apply if ommited
  - `prod`
  - `staging`
  - `dev`
  - `infra`
  - `legacy`
- `service` (list in `alerta`, string - here) and `resource`\*
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
- `value`
  - `30s`
  - `60s`
  - `99%`
  - `5d`
  - `10d`
- `group` - event group
  - `availability`
  - `software`
  - `hardware`
  - `certificate`
  - `domain`
- `origin`
  - `heartbeat_mesh`
  - `disk_alert`
  - `mysql_replica_checker`
  - `website_checker`
- `attributes` - any key value pair with additional data
  - `date time`: `1970-01-01 00:00:00 +0000 UTC`
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

# Rate Limit
`notify_devilry` can rate limit notifications with `rate_limit`.

It has no practical sense for routing to `alerta` as it has its own [De-Duplication](https://docs.alerta.io/en/latest/server.html#de-duplication) mechanisms,
but helps humans to receive less messages via chats.

It uses `environment`, `resource`, `event` and `severity` notification keys to detect similiar notifications.
