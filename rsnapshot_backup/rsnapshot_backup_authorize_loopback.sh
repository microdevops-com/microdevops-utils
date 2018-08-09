#!/bin/bash
set -e
exec > /opt/sysadmws/rsnapshot_backup/rsnapshot_backup_authorize_loopback_out.tmp
exec 2>&1

if [ ! -e /root/.ssh/id_rsa.pub ]; then
	ssh-keygen -b 4096 -f /root/.ssh/id_rsa -q -N ''
fi

if [ ! -e /root/.ssh/authorized_keys ]; then
	cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys
	chmod 600 /root/.ssh/authorized_keys
fi

if ! grep -q "$(cat /root/.ssh/id_rsa.pub)" /root/.ssh/authorized_keys; then
	cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys
	chmod 600 /root/.ssh/authorized_keys
fi
