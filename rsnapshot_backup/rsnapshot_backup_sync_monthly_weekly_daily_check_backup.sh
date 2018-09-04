#!/bin/bash

GRAND_EXIT=0

date '+%F %T ' | tr -d '\n'
echo -e >&2 "NOTICE: Running /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh sync"
/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh sync || GRAND_EXIT=1

if [ "$(date '+%d')" == "01" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Running /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh monthly"
	/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh monthly || GRAND_EXIT=1
fi

if [ "$(date '+%u')" == "1" ]; then
	date '+%F %T ' | tr -d '\n'
	echo -e >&2 "NOTICE: Running /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh weekly"
	/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh weekly || GRAND_EXIT=1
fi

date '+%F %T ' | tr -d '\n'
echo -e >&2 "NOTICE: Running /opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh daily"
/opt/sysadmws/rsnapshot_backup/rsnapshot_backup.sh daily || GRAND_EXIT=1

date '+%F %T ' | tr -d '\n'
echo -e >&2 "NOTICE: Running /opt/sysadmws/rsnapshot_backup/check_backup.sh 2"
/opt/sysadmws/rsnapshot_backup/check_backup.sh 2 || GRAND_EXIT=1

exit $GRAND_EXIT
