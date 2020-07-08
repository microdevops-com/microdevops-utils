#!/bin/bash

set -u
set -e

TOKEN_LIST_ZONES=$1
TOKEN_DNS_EXPORT=$2
DST_DIR=$3

# List zones
ZONES=$(curl -X GET "https://api.cloudflare.com/client/v4/zones" -H "Content-Type:application/json" -H "Authorization: Bearer ${TOKEN_LI
ST_ZONES}" | jq -c ".result" | jq -r ".[].id")

# Export DNS records by zones
for ZONE_ID in ${ZONES}
do
        curl -X GET "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/export" \
                -H "Content-Type:application/json" \
                -H "Authorization: Bearer ${TOKEN_DNS_EXPORT}" \
                > ${DST_DIR}/dns_zone_${ZONE_ID}.txt;
done
