#!/bin/bash

# Pass the arguments as is to /opt/sensu-plugins-ruby/embedded/bin/check-http.rb
# Catch stdout and stderr and write to a variable
OUTPUT=$(/opt/sensu-plugins-ruby/embedded/bin/check-http.rb "$@" 2>&1)
EXIT_CODE=$?

# If the exit code is 2 and output is "CheckHttp CRITICAL: Request error: incorrect header check" do a retry
if [[ $EXIT_CODE -eq 2 && $OUTPUT == *"CheckHttp CRITICAL: Request error: incorrect header check"* ]]; then
  sleep 2
  OUTPUT=$(/opt/sensu-plugins-ruby/embedded/bin/check-http.rb "$@" 2>&1)
  EXIT_CODE=$?
fi

echo $OUTPUT
exit $EXIT_CODE
