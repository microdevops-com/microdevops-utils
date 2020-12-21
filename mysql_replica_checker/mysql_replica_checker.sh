#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

function report {
	local data=${1}
	local master=${2}
	local relay_log=${3}	
	local relay_log_size=${4}
	local stat=${5}

	# Try getting the Master hostname, if the ip is given
	local pat="[0-9]{1,3}(\.[0-9]{1,3}){3}"
	if [[ ${master} ]] && [[ ${master} =~ ${pat} ]]; then
		local master_fdqn=$(host -W 5 "${master}" 2>&1) && host_ok=1
		if [[ ${host_ok} -eq 1 ]]; then master=${master_fdqn##*' '}; fi
	fi
	
	# Check for free space
	if [[ ${relay_log} ]]; then
		local free_space=$(df -Ph "$(dirname "${relay_log}")" | awk 'END{print $4}' )
	fi
	
	# Compose response
	local rsp
	rsp+='{'
	[[ ${stat} = "negative" ]] && rsp+="\"severity\":\"minor\"," 
	[[ ${stat} = "positive" ]] && rsp+="\"severity\":\"ok\"," 
	rsp+="\"service\":\"database\"," 
	rsp+="\"resource\":\"$(hostname -f):mysql\"," 
	[[ ${stat} = "negative" ]] && rsp+="\"event\":\"mysql_replica_checker_error\"," 
	[[ ${stat} = "positive" ]] && rsp+="\"event\":\"mysql_replica_checker_ok\"," 
	rsp+="\"group\":\"mysql_replica_checker\"," 
	rsp+="\"origin\":\"mysql_replica_checker.sh\"," 
	[[ ${stat} = "negative" ]] && rsp+="\"text\":\"Mysql replication error detected\"," 
	[[ ${stat} = "positive" ]] && rsp+="\"text\":\"Mysql replication ok detected\"," 
	[[ ${stat} = "negative" ]] && rsp+="\"correlate\":[\"mysql_replica_checker_ok\"]," 
	[[ ${stat} = "positive" ]] && rsp+="\"correlate\":[\"mysql_replica_checker_error\"]," 
	rsp+="\"attributes\":{" 
	rsp+=${master:+"\"master\":\"${master}\","}
	if [[ -n ${data} ]]; then
		rsp+="${data}"
	fi
	rsp+=${free_space:+"\"relay log free space\":\"${free_space}\","}
	rsp+=${relay_log_size:+"\"log size\":\"$(bc <<<"scale=2; ${relay_log_size:=0} / 1024 / 1024" )Mb\""}
	rsp+='}'
	rsp+='}'

	# Send response
	echo "${rsp}" | sed -e "s/,}/}/g" | /opt/sysadmws/notify_devilry/notify_devilry.py
	exit 0
}

# Check if mysqld and mysql available in path or exit silently
# We exit silently to suppress error messages from cron on servers without mysql
if ! type mysqld &> /dev/null || ! type mysql &> /dev/null; then 
	exit 0
fi 

# Try to load config file 
CONFIG="$(dirname "$0")/mysql_replica_checker.conf"
if [[ -f "$CONFIG" ]]; then
	. "$CONFIG"
fi

# Set MYSQL working variables
BEHIND_MASTER_THR=${BEHIND_MASTER_THR:="300"}
MY_CLIENT=${MY_CLIENT:=$(which mysql)}
MY_CRED=${MY_CRED:="--defaults-file=/etc/mysql/debian.cnf"}
MY_QUERY=${MY_QUERY:="show variables like 'relay_log'; show slave status\G"}
MY_ADMIN=${MY_ADMIN:=$(which mysqladmin)}

# Detect if MYSQL service is alive or exit
my_check=$("$MY_ADMIN" "$MY_CRED" ping 2>/dev/null | grep alive)
if [ "z$my_check" = "z" ] ; then
        exit 0
fi

# Query MYSQL
sql_resp=$("$MY_CLIENT" "$MY_CRED" -Be "$MY_QUERY" 2>&1)

# Exit if not slave
if [[ ! ${sql_resp} =~ "Slave" ]]; then
	exit 0
fi

# Parse MYSQL response
master=$(grep -oP "Master_Host:\s+\K(.+)" <<<"${sql_resp}")			# str or num with dot 

# Basic
last_errno=$(grep -oP "Last_Errno:\s+\K(\S+)" <<<"${sql_resp}")			# ? num 
seconds_behind=$(grep -oP "Seconds_Behind_Master:\s+\K(\S+)" <<<"${sql_resp}")	# NULL or num
sql_delay=$(grep -oP "SQL_Delay:\s+\K(\d+)" <<<"${sql_resp}")			# num or not
io_is_running=$(grep -oP "Slave_IO_Running:\s+\K(\w+)" <<<"${sql_resp}")	# str 
sql_is_running=$(grep -oP "Slave_SQL_Running:\s+\K(\w+)" <<<"${sql_resp}")	# str

# For free space check
relay_log=$(grep -oP "relay_log\s+\K(\S+)" <<<"${sql_resp}")			# str (path)
relay_log_size=$(grep -oP "Relay_Log_Space:\s+\K(\d+)" <<<"${sql_resp}")	# num (bits)

# Extend err msg
last_io_err=$(grep -oP "Last_IO_Error:\s+\K(.+)" <<<"${sql_resp}")		# srt with spaces
last_sql_err=$(grep -oP "Last_SQL_Error:\s+\K(.+)" <<<"${sql_resp}")		# str with spaces

# Run some checks

# Check For Last Error 
if [[ "${last_errno}" != 0 ]]; then
	err_msg+="\"last errno\":\"${last_errno}\","
fi

# Check if IO thread is running
if [[ "${io_is_running}" != "Yes" ]]; then
	err_msg+="\"slave io running\":\"${io_is_running}\","
fi

# Check for SQL thread
if [[ "${sql_is_running}" != "Yes" ]]; then
	err_msg+="\"slave sql running\":\"$sql_is_running\","
fi

# Check how slow the slave is (preset delay + sql_delay)
if [[ -z "${sql_delay}" ]]; then
	# Set 0 if var is ''
	sql_delay=0 
fi

# Handle NULL
if [[ "${seconds_behind}" == "NULL" ]]; then
	err_msg+="\"seconds behind master\":\"${seconds_behind}\","
# Handle threshold+delay 
elif [[ "${seconds_behind}" -ge "$(( ${BEHIND_MASTER_THR} + ${sql_delay} ))" ]]; then
	if [[ "${sql_delay}" -gt 0 ]]; then
		err_msg="\"sql delay\":\"${sql_delay}\","
	fi
	err_msg+="\"threshold\":\"${BEHIND_MASTER_THR}\","
	err_msg+="\"seconds behind master\":\"${seconds_behind}\"," 
fi

# Add last_err_msg to msg
if [[ "${last_io_err}" ]]; then
	err_msg+="\"last io error\":\"${last_io_err}\","
fi
if [[ "${last_sql_err}" ]]; then
	err_msg+="\"last sql error\":\"${last_sql_err}\","
fi

# Send notify only if err_msg
if [[ "${err_msg}" ]]; then
	report "${err_msg}" "${master}" "${relay_log}" "${relay_log_size}" "negative"
else
	report "${err_msg}" "${master}" "${relay_log}" "${relay_log_size}" "positive"
fi
