#!/bin/bash
# originally taken from https://dba.stackexchange.com/questions/188305/list-all-mongodb-databases-from-linux-bash-terminal

# $dbs will contain db names and sizes mixed together
# Use --quiet to skip connection information

dbs=$(mongo $1 $2 $3 $4 $5 $6 $7 $8 $9 --quiet <<EOF
show dbs
quit()
EOF
)
i=0

# Check for some errors first
for db in ${dbs[*]}
do
	if ( echo "$db" | grep -q "NotMasterNoSlaveOk" ); then
		exit
	fi
done

# List dbs
for db in ${dbs[*]}
do
	# Odd values are db names
	# Even values are sizes
	i=$(($i+1))
	# Show db name, ignore size
	if (($i % 2)); then
		echo "$db"
	fi
done
