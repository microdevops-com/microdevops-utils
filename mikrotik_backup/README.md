Connecting to Mikrotik over SSH:
- DSA only
- Add `PubkeyAcceptedKeyTypes +ssh-dss` to `.ssh/config`

Close user management window in WinBox, otherwise SSH hangs.
More info: https://wiki.mikrotik.com/wiki/Use_SSH_to_execute_commands_(DSA_key_login) .
