#!/bin/bash

set -u
set -e

TOKEN_WRITE_ZONES=$1
PAGERULES_ZONE=$2
PAGERULES_ZONE_FILE=$3

# Parsing jq to line and preparations to temp file
cat ${PAGERULES_ZONE_FILE} | jq -c '.result[]' | sed -e 's/^.*\,\"targets\"/{"targets\"/' -e 's/\,\"created_on\".*$/}/' > ${PAGERULES_ZONE_FILE}.tmp

# Import pagerules by zones
while read LINE
do
  curl -X POST "https://api.cloudflare.com/client/v4/zones/${PAGERULES_ZONE}/pagerules" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer ${TOKEN_WRITE_ZONES}" \
     --data ${LINE}
  echo ""
  echo ""
done < ${PAGERULES_ZONE_FILE}.tmp

# Remove temp file
rm ${PAGERULES_ZONE_FILE}.tmp
