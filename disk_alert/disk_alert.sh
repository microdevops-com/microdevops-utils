#!/bin/bash

HOSTNAME=`hostname -f`

if [ "${LANG}" != 'en_US.UTF-8' ] ; then export LANG=C ; fi
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
df -PH | grep -vE '^Filesystem|tmpfs|cdrom' | awk '{ print $5 " " $1 }' | while read output;
do
  #echo $output
  usep=$(echo $output | awk '{ print $1}' | cut -d'%' -f1  )
  partition=$(echo $output | awk '{ print $2 }' )
  if [ $usep -ge 75 ]; then
    echo "Running out of space \"$partition ($usep%)\" on $(hostname -f) as on $(date)" |
      mail -s "${HOSTNAME} - Alert: Almost out of disk space $usep%" mon@sysadm.ws
  fi
done
