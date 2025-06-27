#!/bin/bash

OUTPUT=$(mysql -NBe "SHOW MASTER STATUS" 2>&1)
RET=$?

if [[ $RET -ne 0 ]]; then
  echo "Error while running SHOW MASTER STATUS"
  echo "$OUTPUT"
  exit 2
fi

if [[ -z "$OUTPUT" ]]; then
  echo "SHOW MASTER STATUS is empty"
  exit 2
fi

echo "SHOW MASTER STATUS is OK"
exit 0
