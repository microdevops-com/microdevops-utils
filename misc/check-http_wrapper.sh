#!/bin/bash

# Pass the arguments as is to /opt/sensu-plugins-ruby/embedded/bin/check-http.rb
# Catch stdout and stderr and write to a variable
if [[ $(uname -m) == "aarch64" ]]; then
  OUTPUT=$(source /usr/local/rvm/scripts/rvm && /usr/local/rvm/gems/ruby-2.4.10/bin/check-http.rb "$@" 2>&1)
else
  OUTPUT=$(/opt/sensu-plugins-ruby/embedded/bin/check-http.rb "$@" 2>&1)
fi
EXIT_CODE=$?

# If the exit code is 2 and output is "CheckHttp CRITICAL: Request error: incorrect header check" do a retry
if [[ $EXIT_CODE -eq 2 && $OUTPUT == *"CheckHttp CRITICAL: Request error: incorrect header check"* ]]; then
  sleep 2
  if [[ $(uname -m) == "aarch64" ]]; then
    OUTPUT=$(source /usr/local/rvm/scripts/rvm && /usr/local/rvm/gems/ruby-2.4.10/bin/check-http.rb "$@" 2>&1)
  else
    OUTPUT=$(/opt/sensu-plugins-ruby/embedded/bin/check-http.rb "$@" 2>&1)
  fi
  EXIT_CODE=$?
fi

echo $OUTPUT
exit $EXIT_CODE
