# cve_probe: assessed and not covered

The probe lists vulnerabilities that let someone take a host over, and only where it can
gather evidence on the host. This file records what was looked at and deliberately left
out, so the same assessment is not repeated and "why is CVE-X not in the probe" has an
answer. The rules actually checked are in `rules/` and in the README table.

Add a row when a CVE or a batch is assessed and rejected. Move a row out when its
"revisit if" condition comes true and a rule is written.

## Assessed, not covered

| id | what | decision | reason | assessed | revisit if |
|----|------|----------|--------|----------|------------|
| CVE-2026-118899 | nginx: endless loop reading a request body over TLS 1.3, worker hangs | not covered | denial of service only; fixed by the same upstream releases (1.30.7, 1.31.9) and distro updates as the covered nginx CVEs, except Ubuntu 22.04 and older where Ubuntu's own pages disagree | 2026-11-19 | it turns out to allow more than a hang |
| CVE-2026-125283 | nginx: worker crash with `alias` fed by a regex-capturing `map` variable plus `try_files` | not covered | denial of service only, one worker, restarted by the master; the required config pattern cannot be decided from regexes over the config; no Ubuntu release has a fix, upstream 1.30.7 / 1.31.9 do | 2026-11-19 | it turns out to allow code execution |
| CVE-2026-120993, CVE-2026-120967, CVE-2026-123640 | nginx: PROXY protocol v2 NULL dereference (1.31.4 to 1.31.8 only), stream SNI bypass with client certificates, stream `ssl_preread` validation | not covered | denial of service or a narrow stream-module setup; same nginx batch as above | 2026-11-19 | the stream module becomes common in the fleet |
| PHP releases of 2026-11-19: CVE-2026-129289, -129496, -115560, -126714, -129481, -129474, -129182, -129291, -128090, -128064, -127960, -129538, -129506, -129501, -129292, -15353, -129438 | PHP 8.2.36 / 8.3.37 / 8.4.28 / 8.5.13: FPM request smuggling, timezone cache and session use-after-free, session serializer mismatch, Phar signature downgrade and others | not covered | every one rated critical needs non-default configuration or application behaviour the probe cannot see: a front end that reuses FastCGI connections (`fastcgi_keep_conn on`) with an unread request body, mixed session serializers plus an object chain in the application, PHP 8.5 with non-production ini settings. PHP's announcement says so itself; Ubuntu rates all of them medium; none is in CISA KEV | 2026-11-19 | one enters CISA KEV, or an exploit for a default nginx + PHP-FPM setup is published. CVE-2026-129289 could get a narrow rule: FPM version plus `fastcgi_keep_conn on` |
| kernel SCTP flaw (no CVE id) | second half of the NGINX2Root chain: nginx worker to root, container escape | evidence only | no CVE id, no affected range, no fixed kernel version to compare with; details withheld by the reporter. The `sctp` module state (loadable, loaded, blocked) is printed on vulnerable and restricted nginx findings | 2026-11-19 | it gets a CVE id and vendor kernel versions: then a kernel rule with `sctp` as the module mitigation |
| Angie, freenginx, Tengine | nginx forks, for the NGINX2Root CVEs | not covered | not in use here; each has its own version numbers and fix releases and would need its own table. OpenResty is covered (binary `nginx`, nginx version in the banner). An unknown fork named `nginx` shows as `unknown`; Angie is not discovered at all | 2026-11-19 | a fork is deployed |
| CVE-2025-39682 | kernel TLS zero-copy bug | not covered | only the 6.8 series was affected and the fix shipped before the Copy Fail fix, so any host fixed for Copy Fail has it | 2026-10-27 | never |

## Covered, with a known limit

| rule | limit | why it was left |
|------|-------|-----------------|
| `nginx2root`, `sshhole` | a container with a published port is always reported open to any source; source restrictions on the forwarding path are not evaluated | errs toward alarm, never away from it; evaluating Docker's and podman's forward chains is sizeable work for a rare case |
| `nginx2root` | `restricted` means the firewall limits the sources, not that the sources are a proxying CDN | the probe carries no CDN address lists and cannot see the CDN's mode from the host |
| `sshhole` | "password authentication possible" is the test; the advisory says the bypass needs "some configurations of accounts" without naming them | not published |

## Limits of `--severity exposure`

| limit | consequence |
|-------|-------------|
| the probe sees only the host: a provider firewall, security group or NAT in front is invisible | exposure is an upper bound; a host can look open and be closed, never the reverse |
| source addresses do not say whether they are a proxy or an office | request-level bugs stay critical behind any source-limited port; a non-infrastructure service behind limited sources counts as an entry point |
| accept rules under conditions the probe does not evaluate (packet marks set by Cilium or kube-proxy, rate limits) count as open | Kubernetes nodes show every port as open |
| accounts from LDAP, SSSD or other directories are not in `/etc/passwd` | such non-admin users are not counted as an entry point |
| service classes go by executable name, with the command line only for `java`, `beam.smp`, salt and haproxy | a renamed fork or a new daemon is unknown and counts as an entry point until it is added; `nc` listeners stay unknown on purpose |
| a proxy in front is recognised by a CDN name in a ufw comment or by the web server trusting forwarded addresses | a load balancer the web server was never told about is missed when every admitted source has a name: the finding is major |
| source names exist only in ufw rule comments | on a host without ufw, or with rules that carry no comment, a source-limited web service keeps the assumption that the sources may be a proxy |
| a forward proxy and a reverse proxy are the same process | `squid` is classed as a relay (system); one that reverse-proxies an application behind limited sources is classed too low |
| an unauthenticated Docker API on TCP (2375) is reported only as an entry point | it is a configuration fault, not a CVE, and gets no finding of its own |
| reachability of Kubernetes pods (containerd, CRI-O) is not evaluated: service rules, NodePorts, ingress and CNI packet marks are not read | a remote finding in a pod stays critical with the reason that its reachability cannot be proven |
| nginx is always web, also when its `stream` block only forwards a database | such a host keeps local bugs critical |
| a database, cache or queue reachable from limited sources is not an entry point | someone who can log in to it is not considered to run code on the host |
| which listener proxies to which process is not visible | an application on loopback is judged by all listeners of the host |

## Seen, not assessed

Leads nobody has looked at. Not decisions.

| id | where it came from | seen |
|----|--------------------|------|
| CVE-2026-119977 | WordPress core, added to CISA KEV on 2026-11-03 | 2026-11-19 |
| Red Hat bulletins RHSB-2026-004 to -014: CVE-2026-46333, CVE-2026-46243, CVE-2026-46331, CVE-2026-43499, CVE-2026-53166, CVE-2026-80844, CVE-2026-81000, CVE-2026-68121, CVE-2026-74469 | candidate list for further kernel rules | 2026-10-27 |
