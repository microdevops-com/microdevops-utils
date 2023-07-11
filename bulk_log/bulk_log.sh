#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
GW_IP_ADDRESS=$(/sbin/ip route | awk '/default/ { print $3 }')

echo "#########################################################################################################"
date
echo "###"
COLUMNS=250 top -b -n 1 -c 2>&1
echo "###"
ps aux 2>&1
echo "###"
iotop -b -k -t -n 1 2>&1
echo "###"
free -m 2>&1
echo "###"
uptime
echo "###"
ping -c 10 www.google.com 2>&1
echo "###"
netstat -an 2>&1
echo "###"
ping -c 4 ${GW_IP_ADDRESS} 2>&1
echo "###"
arp -an 2>&1
echo "###"
ifconfig -a 2>&1
echo "###"
ethtool eth0 2>&1
echo "###"
ethtool -S eth0 2>&1
echo "###"
netstat -ia 2>&1
echo "###"
netstat -nr 2>&1
echo "###"
w 2>&1
echo "###"
df -h 2>&1
echo "###"
