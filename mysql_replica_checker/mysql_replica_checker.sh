#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

function report {
  local message=${1}
  local master=${2}
  local relay_log=${3}	
  local relay_log_size=${4}
  relay_log_size=$(bc <<<"scale=2; ${relay_log_size:=0} / 1024 / 1024 / 1024" )'G'


  ###try to get Master hostname, if ip given  
  local pat="[0-9]{1,3}(\.[0-9]{1,3}){3}"
  if [[ ${master} ]] && [[ ${master} =~ ${pat} ]]; then
    local master_fdqn=$(host -W 5 "${master}" 2>&1) && host_ok=1
    if [[ ${host_ok} -eq 1 ]]; then master=${master_fdqn##*' '}; fi
  fi
  
  ###check for free space
  if [[ ${relay_log} ]]; then
    local free_space=$(df -Ph "$(dirname "${relay_log}")" | awk 'END{print $4}' )
  fi
  
  ### Compose response
  local rsp
  rsp+='{'
  rsp+="\"host\":\"$(hostname -f)\"," 
  rsp+="\"date\":\"$(date +'%F %T')\","
  rsp+="\"type\":\"replica alert\"," 
  rsp+="\"master\":\"${master}\","
  if [[ -n ${message} ]]; then
    rsp+="\"message\":\"${message}\","
  fi
  rsp+="\"relay log free space\":\"${free_space}\","
  rsp+="\"log size\":\"${relay_log_size}\""
  rsp+='}'

  ### Send response
  echo "${rsp}"
  exit 0
}

###   Check if mysqld and mysql available in path OR DIE
if ! type mysqld &> /dev/null || ! type mysql &> /dev/null; then 
  echo "Mysql is not found"
  exit 0
fi 

	
###   Try to load config file 
CONFIG="$(dirname "$0")/mysql_replica_checker.conf"
if [[ -f "$CONFIG" ]]; then
  . "$CONFIG"
fi


###   Set MYSQL working variables
BEHIND_MASTER_THR=${BEHIND_MASTER_THR:="300"}
MY_CLIENT=${MY_CLIENT:=$(which mysql)}
MY_CRED=${MY_CRED:="--defaults-file=/etc/mysql/debian.cnf"}
MY_QUERY=${MY_QUERY:="show variables like 'relay_log'; show slave status\G"}


###   Query MYSQL OR DIE with message
sql_resp=$("$MY_CLIENT" "$MY_CRED" -Be "$MY_QUERY" 2>&1) && query_ok=1
if [[ ${query_ok} -ne 1 ]]; then
  report "It seems all OK but I can't query MYSQL"
fi


###   if MYSQL is not SLAVE then DIE 
if [[ ! ${sql_resp} =~ "Slave" ]]; then
  echo "Mysql is not slave"
  exit 0
fi


###   Parse MYSQL response
master=$(grep -oP "Master_Host:\s+\K(.+)" <<<"${sql_resp}")                    #  str or num with dot 

  #basic
last_errno=$(grep -oP "Last_Errno:\s+\K(\S+)" <<<"${sql_resp}")                #? num 
seconds_behind=$(grep -oP "Seconds_Behind_Master:\s+\K(\S+)" <<<"${sql_resp}") #  NULL or num
sql_delay=$(grep -oP "SQL_Delay:\s+\K(\d+)" <<<"${sql_resp}")                  #  num or not
io_is_running=$(grep -oP "Slave_IO_Running:\s+\K(\w+)" <<<"${sql_resp}")       #  str 
sql_is_running=$(grep -oP "Slave_SQL_Running:\s+\K(\w+)" <<<"${sql_resp}")     #  str

  #For free space check
relay_log=$(grep -oP "relay_log\s+\K(\S+)"  <<<"${sql_resp}")                  #  str (path)
relay_log_size=$(grep -oP "Relay_Log_Space:\s+\K(\d+)"  <<<"${sql_resp}")      #  num (bits)

  #Extend err msg
last_io_err=$(grep -oP "Last_IO_Error:\s+\K(.+)" <<<"${sql_resp}")             #  srt with spaces
last_sql_err=$(grep -oP "Last_SQL_Error:\s+\K(.+)" <<<"${sql_resp}")           #  str with spaces


###  Run Some Check
err_msg+="\n"
  ##  Check For Last Error 
if [[ "${last_errno}" != 0 ]]; then
  err_msg+="Last_Errno: ${last_errno}\n"
fi

  ##  Check if IO thread is running ##
if [[ "${io_is_running}" != "Yes" ]]; then
  err_msg+="Slave_IO_Running: ${io_is_running}\n"
fi

  ##  Check for SQL thread ##
if [[ "${sql_is_running}" != "Yes" ]]; then
  err_msg+="Slave_SQL_Running: $sql_is_running\n"
fi

  ##  Check how slow the slave is (preset delay + sql_delay) ##
if [[ -z "${sql_delay}" ]]; then sql_delay=0; fi
if [[ "${seconds_behind}" == "NULL" ]]; then
  err_msg+="Seconds_Behind_Master: ${seconds_behind}\n"
elif [[ "${seconds_behind}" -ge "$(( ${BEHIND_MASTER_THR} + ${sql_delay} ))" ]]; then
  [[ "${sql_delay}" -gt 0 ]] && delay=" sql_delay: ${sql_delay}" || delay=''
  err_msg+="Seconds_Behind_Master: ${seconds_behind} (thr: ${BEHIND_MASTER_THR}${delay})\n"
fi

  ##  Add last_err_msg to msg
if [[ "${last_io_err}" ]]; then
  err_msg+="Last_IO_Error: ${last_io_err}\n"
fi
if [[ "${last_sql_err}" ]]; then
  err_msg+="Last_SQL_Error: ${last_sql_err}\n"
fi

report "${err_msg%%'\n'}" "${master}" "${relay_log}" "${relay_log_size}"
