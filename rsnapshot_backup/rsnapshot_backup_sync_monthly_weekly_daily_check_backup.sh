#!/bin/bash

GRAND_EXIT=0

/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh sync
[ $? -gt 0 ] && GRAND_EXIT=1

[ "$(date '+%d')" == "01" ] && /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh monthly
[ $? -gt 0 ] && GRAND_EXIT=1

[ "$(date '+%u')" == "1" ] && /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh weekly
[ $? -gt 0 ] && GRAND_EXIT=1

/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh daily
[ $? -gt 0 ] && GRAND_EXIT=1

/opt/sysadmws/rsnapshot_backup/check_backup.sh 2
[ $? -gt 0 ] && GRAND_EXIT=1

exit $GRAND_EXIT
