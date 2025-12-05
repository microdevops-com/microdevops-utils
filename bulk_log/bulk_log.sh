#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
GW_IP_ADDRESS=$(/sbin/ip route | awk '/default/ { print $3 }')

echo "#########################################################################################################"
date
echo "### top"
COLUMNS=250 top -b -n 1 -c 2>&1
echo "### ps"
ps aux 2>&1
echo "### iotop"
iotop -b -k -t -n 1 2>&1
echo "### free"
free -m 2>&1
echo "### uptime"
uptime
echo "### ping"
ping -c 10 www.google.com 2>&1
echo "### netstat"
netstat -an 2>&1
echo "### ping gw"
ping -c 4 ${GW_IP_ADDRESS} 2>&1
echo "### arp"
arp -an 2>&1
echo "### ifconfig"
ifconfig -a 2>&1
echo "### ethtool"
ethtool eth0 2>&1
echo "### ethtool"
ethtool -S eth0 2>&1
echo "### netstat"
netstat -ia 2>&1
echo "### netstat -nr"
netstat -nr 2>&1
echo "### w"
w 2>&1
echo "### df"
df -h 2>&1
echo " "
