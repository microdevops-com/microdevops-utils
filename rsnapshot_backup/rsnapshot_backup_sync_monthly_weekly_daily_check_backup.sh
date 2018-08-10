#!/bin/bash

/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh sync
[ "$(date '+%d')" == "01" ] && /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh monthly
[ "$(date '+%u')" == "1" ] && /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh weekly
/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh daily
/opt/sysadmws/rsnapshot_backup/check_backup.sh 2
