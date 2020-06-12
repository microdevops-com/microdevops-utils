#!/usr/bin/env bash
__workdir="$(dirname "$0")" 
__scriptname="cmd_check_alert.py" 
__python_binary="$(which python3.9 python3.8 python3.7 python3.6 python3.5 python3 python 2> /dev/null | grep -m1 '^/' )"
( $__python_binary $__workdir/$__scriptname ) & 
