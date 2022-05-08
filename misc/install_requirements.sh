#!/bin/bash
if [[ -e /etc/os-release ]]; then
	. /etc/os-release
fi

if [[ "${ID_LIKE}" = "debian" || "${ID}" = "debian" ]]; then
	# Common utils
	apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install gawk rsnapshot jq
	# Python
	if [[ "${UBUNTU_CODENAME}" = "focal" || "${UBUNTU_CODENAME}" = "jammy" || "${VERSION_CODENAME}" = "bullseye" ]]; then
		apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install python3 python3-yaml python3-jinja2 python3-zmq
		# Install python-is-python3 if python2 is not installed
		if ! which python; then
			apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install python-is-python3
		fi
	else
		apt-get -qy -o 'DPkg::Options::=--force-confold' -o 'DPkg::Options::=--force-confdef' install python python-yaml python-jinja2 python-zmq
	fi
fi

if [[ "${ID_LIKE}" = "rhel fedora" ]]; then
	# Common utils
	yum install -y gawk rsnapshot jq
	# Python
	if [[ "${VERSION_ID}" = "7" ]]; then
		yum install -y python2-pyyaml python2-zmq python2-jinja2
	elif [[ "${VERSION_ID}" = "8" ]]; then
		yum install -y python3-pyyaml python3-zmq python3-jinja2
		if alternatives --display python | grep -q "python - status is auto"; then
			alternatives --set python /usr/bin/python3
			echo python set to /usr/bin/python3
		else
			echo python already set
		fi
	else
		echo "Unknown CentOS version detected"
	fi
fi
