# sysadmws-utils-v1
Sysadmin Workshop Utilities

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
