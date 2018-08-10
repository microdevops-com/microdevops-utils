#!/bin/bash

GRAND_EXIT=0

/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh sync || GRAND_EXIT=1

[ "$(date '+%d')" == "01" ] && ( /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh monthly || GRAND_EXIT=1 )

[ "$(date '+%u')" == "1" ] && ( /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh weekly || GRAND_EXIT=1 )

/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh daily || GRAND_EXIT=1

/opt/sysadmws/rsnapshot_backup/check_backup.sh 2 || GRAND_EXIT=1

exit $GRAND_EXIT
