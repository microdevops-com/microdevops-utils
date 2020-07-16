#!/bin/bash

set -u
set -e

TOKEN_LIST_ZONES=$1
TOKEN_EXPORT=$2
DST_DIR=$3
ZONES=""

# Get total pages in zone list
TOTAL_PAGES=$(curl -sS -X GET "https://api.cloudflare.com/client/v4/zones?per_page=5&direction=asc" \
	-H "Content-Type:application/json" -H "Authorization: Bearer ${TOKEN_LIST_ZONES}" | jq -c ".result_info.total_pages")

# List zones with pagination
for PAGE in $(seq 1 ${TOTAL_PAGES})
do
	ZONES_TO_ADD=$(curl -sS -X GET "https://api.cloudflare.com/client/v4/zones?per_page=5&direction=asc&page=${PAGE}" \
		-H "Content-Type:application/json" -H "Authorization: Bearer ${TOKEN_LIST_ZONES}" | jq -c ".result" | jq -r ".[].id")
	ZONES="${ZONES} ${ZONES_TO_ADD}"
done

# Export DNS records by zones
for ZONE_ID in ${ZONES}
do
        curl -sS -X GET "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/export" \
                -H "Content-Type:application/json" \
                -H "Authorization: Bearer ${TOKEN_EXPORT}" \
                > ${DST_DIR}/dns_records_${ZONE_ID}.txt;
done
