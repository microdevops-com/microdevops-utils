#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
GW_IP_ADDRESS=$(/sbin/ip route | awk '/default/ { print $3 }')

echo "#########################################################################################################"
date
echo " "
echo "### top"
COLUMNS=250 top -b -n 1 -c 2>&1
echo " "
echo "### ps"
ps aux 2>&1
echo " "
echo "### iotop"
iotop -b -k -t -n 1 2>&1
echo " "
echo "### free"
free -m 2>&1
echo " "
echo "### uptime"
uptime
echo " "
echo "### ping"
ping -c 10 www.google.com 2>&1
echo " "
echo "### netstat"
netstat -an 2>&1
echo " "
echo "### ping gw"
ping -c 4 ${GW_IP_ADDRESS} 2>&1
echo " "
echo "### arp"
arp -an 2>&1
echo " "
echo "### ifconfig"
ifconfig -a 2>&1
echo " "
echo "### ethtool"
ethtool eth0 2>&1
echo " "
echo "### ethtool -S"
ethtool -S eth0 2>&1
echo " "
echo "### netstat -ia"
netstat -ia 2>&1
echo " "
echo "### netstat -nr"
netstat -nr 2>&1
echo " "
echo "### w"
w 2>&1
echo " "
echo "### df"
df -h 2>&1
echo " "
