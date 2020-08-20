# receiver.py
receiver.py is a service to receive haertbeats sent by sender.py and send notifications via notify_devilry.

It writes heartbeat data with sender payload to history and current files. These files are just for logging purposes and could be used by external components.
They are not needed for receiver and could be disabled.

Heartbeats are sent using zmq.PUSH socket and received using zmq.PULL socket.

Receiver gives grace period after start for senders to send their heartbeats.

Sender should send heartbeat with token to authorize and identify client, otherwise heartbeat is ignored.

Receiver performs checks and sends these event notifications:
- heartbeat_mesh_receiver_activity_ok - Heartbeats are being received
- heartbeat_mesh_receiver_activity_lost - No heartbeats registered on receiver host for two check intervals
- heartbeat_mesh_heartbeat_timeout - Resource heartbeat timed out
- heartbeat_mesh_heartbeat_ok - Resource heartbeat ok
- heartbeat_mesh_heartbeat_config_missing - Heartbeat registered more than 24h without resource listing in config
- heartbeat_mesh_heartbeat_config_exist - Heartbeat registered more than 24h withresource listing in config
- heartbeat_mesh_heartbeat_not_registered - No heartbeats registered for resource from config
- heartbeat_mesh_heartbeat_registered - Heartbeats registered for resource from config
- heartbeat_mesh_heartbeat_deregistered - Resource heartbeat deregistered
- heartbeat_mesh_heartbeat_new - New resource heartbeat registered
- heartbeat_mesh_heartbeat_comeback - Heartbeat comeback registered after timeout

# sender.py
sender.py is a small script run by cron to send heartbeats to receivers.

Many receivers could be used. If receiver is not available - it is skipped and no error reported.

Sender should send heartbeats more often than timeout value to be considered alive.

Sender could add payload, such as host uptime, with heartbeats.

Most common usage is to monitor server (host) availability, but you can use any arbitrary name as resource definition in separate config and automate heartbeats for some service:
```
systemctl is-active --quiet service && sender.py --config service.yaml
```

In this case `service.yaml` should contain:
```
enabled: True
receivers:
  receiver1.example.com:
    token: aaaaaaaaaaaaaaaaaaaaa
    resource: host1.example.com:service
```

# Service Install
```
sudo cp receiver.service /etc/systemd/system/heartbeat_mesh_receiver.service
sudo systemctl daemon-reload
sudo chown root:root /etc/systemd/system/heartbeat_mesh_receiver.service
sudo chmod 644 /etc/systemd/system/heartbeat_mesh_receiver.service
sudo sudo systemctl enable heartbeat_mesh_receiver
sudo systemctl start heartbeat_mesh_receiver
sudo systemctl status heartbeat_mesh_receiver
```

# Read Logs
```
sudo journalctl --unit heartbeat_mesh_receiver
```
