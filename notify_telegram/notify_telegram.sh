#!/usr/bin/env bash

# Get constants from file
# TG_ALERT_CHAT_ID, TG_URL, TG_PARSE_MODE
# we might start script from different locations
# +so use absolute path to config
cyan='\e[36m';green='\e[32m';red='\e[91m';reset='\e[0m'

CRED="$(dirname "$0")/notify_telegram.conf"
if [[ -s $CRED ]]; then
  . "$CRED"
else 
  echo "No credentials found at $CRED"
  exit 2
fi

# show help
show_help () {
doc_help=$(cat <<-EOF
${cyan}Usage: STDOUT | $0 [-sdlcv] ${reset}
	  -s 	Silent mode, no notification on message in telegram
	  -d	Markdown parse mode, for using *bold* or _italic_
	  -l    HTML parse mode, <b>bold</b> or <i>italic</i>
	  -c	Send input as preformatted code block
	  -v	Print curl output, e.g. telegram server response
	Default parse mode: $TG_PARSE_MODE
	${green}
	Example: 
	  ls -1 | $0 -sc
	  df -h | grep sda | $0
	${red}
	WARNING: avoid competitive params ${reset}
	  case echo -e  '<b>bold</b>' | notify_telegram -dc
	                    ${red} use -c option only with -d  ^ ${reset}
	  can't send  echo -e '<b>bold</b>' | ./notify_telegram -lc
EOF
)
echo -e "$doc_help"
}

# main
OPTIND=1
while getopts "hsdlcv" opt; do
    case "$opt" in
      h) show_help; exit 0		;; 
      s)   silent="true"		;;
      d)   mode=${mode:="markdown"}	;;
      l)   mode=${mode:="HTML"}		;;
      c)   coded="true"			;;
      v)   output="/dev/stdout"		;;
      *)   exit 0			;;
    esac
done
shift "$((OPTIND-1))" 

# just sent text to TG
tg_send () {
  mode="${mode:=$TG_PARSE_MODE}"  
  if [[ $coded == "true" ]]; then
    if [[ $mode == "HTML" ]]; then
      msg="<pre>$1</pre>"
    elif [[ $mode == "markdown" ]]; then
      msg="\`\`\`$1\`\`\`"
    fi
  else msg="$1"
  fi

  curl -s -X POST				\
    "$TG_URL"					\
    -d parse_mode="$mode"			\
    -d chat_id="$TG_ALERT_CHAT_ID"		\
    -d text="$msg"				\
    -d disable_notification=${silent:="false"}	\
    --silent --output "${output:="/dev/null"}"
}

# if piped, send nonempty message with text from stdin, else print usage note
if [[  -t 0  ]]; then 
  show_help
else
  msg="$(cat)"
  if [[ ! -z ${msg//' '} ]]; then
    tg_send "$msg"
  else 
    exit 0
  fi
fi
