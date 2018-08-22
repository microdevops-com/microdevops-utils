# sysadmws-utils-v1
Sysadmin Workshop Utilities:
- bulk_log - collect and logrotate raw output from debug commands, useful for post-mortem diagnosis.
- disk_alert - simple autonomouos script to check free space and space prediction using linear regression, sends alerts to Telegram usign notify_devilry.
- logrotate_db_backup - script to rotate db dumps using logrotate.
- mikrotik_backup - script to dump Mikrotik RouterOS config and binary backup via ssh for multiple boxes.
- misc - various cmd tools.
- mysql_queries_log - script helps to catch some kind of mysql queries, useful for post-mortem diagnosis.
- mysql_replica_checker - simple autonomouos script to check mysql replica status, sends alerts to Telegram usign notify_devilry.
- notify_devilry - configured with YAML+Jinja2, sends input JSON to Telegram.
- put_check_files - autonomous script to put check files for rsnapshot_backup, if Salt formula sysadmws-formula is unavailable.
- rsnapshot_backup - rsnapshot wrapper, makes usage of rsnapshot for ssh, native, mysql, postgresql etc on hundreds of servers manageable.

rsnapshot_backup could be configured by hands with JSON config, but shouldn't. Use [sysadmws-formula/rsnapshot_backup](https://github.com/sysadmws/sysadmws-formula/blob/master/rsnapshot_backup/pillar.example).

Example Salt state to install for Ubuntu/Debian:
```
pkgrepo_sysadmws:
  pkgrepo.managed:
    - file: /etc/apt/sources.list.d/sysadmws.list
    - name: 'deb https://repo.sysadm.ws/sysadmws-apt/ any main'
    - keyid: 2E7DCF8C
    - keyserver: keyserver.ubuntu.com

pkg_latest_utils:
  pkg.latest:
    - refresh: True
    - pkgs:
        - sysadmws-utils-v1
```

Example Salt state to install for CentOS and other unsupported OS via tgz package:
```
install_utils_tgz_v1_1:
  cmd.run:
    - name: 'rm -f /root/sysadmws-utils-v1.tar.gz'
    - runas: 'root'

install_utils_tgz_v1_2:
  cmd.run:
    - name: 'cd /root && wget --no-check-certificate https://repo.sysadm.ws/tgz/sysadmws-utils-v1.tar.gz'
    - runas: 'root'

install_utils_tgz_v1_3:
  cmd.run:
    - name: 'tar zxf /root/sysadmws-utils-v1.tar.gz -C /'
    - runas: 'root'
```

See more at [sysadmws-formula](https://github.com/sysadmws/sysadmws-formula/blob/master/sysadmws-utils/sysadmws-utils.sls).
