#!/bin/bash
if [[ -e /etc/os-release ]]; then
	. /etc/os-release
fi

if [[ "${ID_LIKE}" = "debian" ]]; then
	# Common utils
	apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install gawk rsnapshot jq
	# Python
	if [[ "${UBUNTU_CODENAME}" = "focal" ]]; then
		apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install python3 python3-yaml python3-jinja2 python3-zmq
	else
		apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install python python-yaml python-jinja2 python-zmq
	fi
fi
