#!/bin/bash
if [[ -e /etc/os-release ]]; then
	. /etc/os-release
fi

if [[ "${UBUNTU_CODENAME}" = "focal" ]]; then
	exec /usr/bin/env python3 "$@"
else
	exec /usr/bin/env python "$@"
fi
