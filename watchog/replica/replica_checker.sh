#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin


###   Check if mysqld and mysql available in path OR DIE
if ! type mysqld || ! type mysql ; then exit 0; fi &> /dev/null

	
###   Try to load config file OR DIE
CONFIG="replica_checker.conf"
if [[ -f "$CONFIG" ]]; then
  . "$CONFIG"
else
  echo "ERROR: no config file found: $CONFIG"
  exit 2
fi


###   Set MYSQL working variables
HOST=${HOST:=$(hostname)}
BEHIND_MASTER_THR=${BEHIND_MASTER_THR:="300"}
MY_CLIENT=${MY_CLIENT:=$(which mysql)}
MY_CRED=${MY_CRED:="--defaults-file=/etc/mysql/debian.cnf"}
MY_QUERY=${MY_QUERY:="show variables like 'relay_log'; show slave status\G"}
CUR_DATE_TIME=$(date +"%F %T")


###   Query MYSQL OR DIE with message
sql_resp=$("$MY_CLIENT" "$MY_CRED" -Be "$MY_QUERY" 2>&1) && query_ok=1
if [[ $query_ok -ne 1 ]]; then
  msg="I am ${HOST} <b>replica checker</b>, and I can't query <i>MYSQL</i>"
  curl -s -X POST "$URL" -d parse_mode="$PARSE_MODE" -d chat_id="$ALERT_CHAT_ID" -d text="$msg"
  exit 0
fi


###   if MYSQL is not SLAVE then DIE 
if [[ ! $sql_resp =~ "Slave" ]]; then
  exit 0
fi


###   Get data for checks
master=$(grep -oP "Master_Host:\s+\K(.+)" <<<"$sql_resp")                    #  str or num with dot 

  #basic
last_errno=$(grep -oP "Last_Errno:\s+\K(\S+)" <<<"$sql_resp")                #? num 
seconds_behind=$(grep -oP "Seconds_Behind_Master:\s+\K(\S+)" <<<"$sql_resp") #  NULL or num
sql_delay=$(grep -oP "SQL_Delay:\s+\K(\d+)" <<<"$sql_resp")                  #  num or not
io_is_running=$(grep -oP "Slave_IO_Running:\s+\K(\w+)" <<<"$sql_resp")       #  str 
sql_is_running=$(grep -oP "Slave_SQL_Running:\s+\K(\w+)" <<<"$sql_resp")     #  str

  #For free space check
relay_log=$(grep -oP "relay_log\s+\K(\S+)"  <<<"$sql_resp")                  #  str (path)
relay_log_size=$(grep -oP "Relay_Log_Space:\s+\K(\d+)"  <<<"$sql_resp")      #  num (bits)

  #Extend err msg
last_io_err=$(grep -oP "Last_IO_Error:\s+\K(.+)" <<<"$sql_resp")             #  srt with spaces
last_sql_err=$(grep -oP "Last_SQL_Error:\s+\K(.+)" <<<"$sql_resp")           #  str with spaces
err_msg=()


###  Run Some Check

  ##  Check For Last Error 
if [[ "$last_errno" != 0 ]]; then
  err_msg=("${err_msg[@]}" "Last_Errno: $last_errno")
fi

  ##  Check if IO thread is running ##
if [[ "$io_is_running" != "Yes" ]]; then
  err_msg=("${err_msg[@]}" "Slave_IO_Running: $io_is_running")
fi

  ##  Check for SQL thread ##
if [[ "$sql_is_running" != "Yes" ]]; then
  err_msg=("${err_msg[@]}" "Slave_SQL_Running: $sql_is_running")
fi

  ##  Check how slow the slave is (preset delay + sql_delay) ##
if [[ -z "$sql_delay" ]]; then sql_delay=0; fi
if [[ "$seconds_behind" == "NULL" ]]; then
  err_msg=("${err_msg[@]}" "Seconds_Behind_Master: $seconds_behind")
elif [[ "$seconds_behind" -ge "$(( $BEHIND_MASTER_THR + $sql_delay ))" ]]; then
  [[ "$sql_delay" -gt 0 ]] && delay=" sql_delay: $sql_delay" || delay=''
  err_msg=("${err_msg[@]}" "Seconds_Behind_Master: $seconds_behind (thr: $BEHIND_MASTER_THR$delay)")
fi

  ##  Add last_err_msg to msg
if [[ "$last_io_err" ]]; then
  err_msg=("${err_msg[@]}" "Last_IO_Error: $last_io_err")
fi
if [[ "$last_sql_err" ]]; then
  err_msg=("${err_msg[@]}" "Last_SQL_Error: $last_sql_err")
fi


###   Send TG message if there was an error 
if [[ "${#err_msg[@]}" -gt 0 ]]; then
  # we wanna do following only if any error occurs  
  #+not just every time check is run

  ###try to get Master hostname, if ip given  
   pat="[0-9]{1,3}(\.[0-9]{1,3}){3}"
   if [[ $master =~ $pat ]]; then
     master_host=$(host -W 10 "$master" 2>&1) && host_ok=1
     if [[ $host_ok -eq 1 ]]; then master=${master_host##*' '}; fi
   fi

  ###check for free space
   if [[ ! -z $relay_log ]]; then
     free_space=$(df -Ph "$(dirname "$relay_log")" | awk 'END{print $4}' )
     relay_log_size=$(( $relay_log_size / 1024 / 1024 ))'M'
   fi

  ### Compose message
    msg+="MYSQL: ${HOST} <b>replica error</b>\n"
    msg+="Master: ${master}\n"
    msg+="$(for i in $(seq 0 ${#err_msg[@]}) ; do echo "${err_msg[$i]}" ; done)\n"
    msg+="<code>Avail: $free_space Log: $relay_log_size</code>\n"
    msg+="<code>$CUR_DATE_TIME</code>\n"
  msg=${msg//\\n/$'\n'}

  ### Send message
  curl -s -X POST "$URL" -d parse_mode="$PARSE_MODE" -d chat_id="$ALERT_CHAT_ID" -d text="$msg"
fi

