# cve_probe

Read-only probe answering one narrow question per critical CVE: is this host exploitable
right now, and through what? It is not a scanner. It only knows the CVEs described in
`rules/*.json` and gathers exactly the evidence those rules need.

Why it exists: package-based CVE scanners report thousands of matches per host. The handful
of CVEs that actually got our clients hacked (kernel local privilege escalations, PHP RCE)
need a different question: running kernel vs installed, module blacklists, sysctl
mitigations, PHP inside containers, php.ini hardening, end-of-life branches with no fix,
compromised CA roots still present in a trust store.

Constraints: Python 3.5 syntax, standard library only, runs as root, changes nothing.
Kernel modules are never loaded (`modprobe` is used with `-n` only).

## What it detects

The complete current scope is the rule set in `rules/`. Nothing outside this table is checked.

| family | ids | what | kind |
|--------|-----|------|------|
| `copy-fail` | CVE-2026-31431, CVE-2025-39964 | Copy Fail: AF_ALG `algif_aead` (plus `algif_skcipher`/`algif_hash` for the 2025 bug) local privilege escalation | kernel |
| `dirty-frag` | CVE-2026-43284, CVE-2026-43500, CVE-2026-46300 | Dirty Frag / Fragnesia: XFRM ESP (`esp4`/`esp6`) and RxRPC page-cache write, local privilege escalation | kernel |
| `ipv6-frag-escape` | CVE-2026-53362 | IPv6 UDP send path heap overflow, local privilege escalation / container escape, in CISA KEV | kernel |
| `ebt-snat` | CVE-2026-53266 | ebtables SNAT ARP rewrite into spliced file pages, local privilege escalation | kernel |
| `tcp-ireq-opt-uaf` | CVE-2026-98432 | IPv4 TCP request socket IP-options use-after-free, remote and unauthenticated on any listening port; firewall drop of TCP with IP options counts as mitigated | kernel |
| `php2shell` | CVE-2026-109618, CVE-2026-109619 | PHP2Shell: unauthenticated remote code execution in PHP HTTP SAPIs, on the host and inside containers | php |
| `emudhra-ca` | EMUDHRA-CA-2026 (USN-8944-1/2, DSA-6572) | eMudhra CA key compromise: `emSign ECC Root CA - G3` or Sectigo `AAA Certificate Services` still in a trust store, host and containers | trust_store |
| `brotli-decoder` | CVE-2026-111497 | Node2Shell: Brotli decoder overflow, remote code execution; running Node.js/Bun binaries (vendored copy) on host and in containers, plus the system libbrotli in every root | runtime |
| `nginx2root` | CVE-2026-123007, CVE-2026-123633, CVE-2026-123634, CVE-2026-121810, CVE-2026-113425 | NGINX2Root: nginx HTTP/2, HTTP/3, resolver and mail proxy memory corruption, remote code execution as the worker user; running nginx on host and in containers, judged by package, configuration and who can reach the ports | runtime |
| `sshhole` | CVE-2026-123158 | OpenSSH sshd password authentication bypass on musl libc without PAM (Alpine), in CISA KEV; running sshd on host and in containers, judged by the libraries it has mapped, package, `PasswordAuthentication` and who can reach the port. glibc builds report `not_applicable` | runtime |
| `ruby2shell` | CVE-2026-132825 | Ruby2Shell: heap overflow in Ruby string case conversion, remote code execution reported for Rails and Sinatra; running Ruby interpreters on host and in containers (rbenv, RVM, images, distro packages, GitLab's bundled Ruby), critical when the process holds a listening TCP or Unix socket | runtime |

`--only <family>` or `--only <id>` restricts a run to one row. When a rule file is added, add its row here.
CVEs that were assessed and deliberately left out, with the reason, are listed in `NOT_COVERED.md` in
the source repository.

## Usage

```
/opt/microdevops/cve_probe/cve_probe.py            # text report, exit code per severity
/opt/microdevops/cve_probe/cve_probe.py --json     # machine-readable report
/opt/microdevops/cve_probe/cve_probe.py --all      # text report including ok findings
/opt/microdevops/cve_probe/cve_probe.py --only php2shell --only CVE-2026-31431
/opt/microdevops/cve_probe/cve_probe.py --kernel-only | --php-only
/opt/microdevops/cve_probe/cve_probe.py --json --facts   # add raw kernel/php facts
/opt/microdevops/cve_probe/cve_probe.py --severity exposure   # weigh findings by exposure, see below
```

Exit codes, meant for cmd_check_alert `severity_per_retcode`:

| exit | severity | statuses |
|------|----------|----------|
| 0 | ok | fixed, not_applicable |
| 1 | probe error | could not run (not root, bad rules) |
| 2 | minor | mitigated |
| 3 | major | reboot_pending, stale_workers, host_managed, unknown, restricted |
| 4 | critical | vulnerable |

Statuses:

- `vulnerable` - no fix installed, no mitigation in place.
- `mitigated` - unpatched, but the attack path is closed: module blocked via modprobe.d
  `install ... /bin/false`, module files absent for the running kernel, sysctl set, a
  netfilter rule from the rule file active on the right hooks, or the php.ini mitigation applied.
- `reboot_pending` - a fixed kernel is installed, the running one is not.
- `stale_workers` - fixed PHP binary on disk, running processes started before it.
- `host_managed` - running inside an LXC/Incus container: the kernel is vulnerable by version
  but belongs to the host, and host-side mitigations are not visible from here.
- `restricted` - vulnerable and configured for the bug, but the firewall accepts the listening
  ports only from particular sources or interfaces (a CDN, an office range), or the service
  listens on loopback or in a container that publishes no port. Not proven safe: the allowed
  sources can still attack, and the list has to stay correct.
- `unknown` - no evidence either way (no changelog, no table entry, built after disclosure).
- `fixed`, `not_applicable`.

## Severity modes

`--severity default` (also when the argument is absent) is the table above: every `vulnerable`
finding is critical. Monitoring uses it. `--severity exposure` keeps every finding and status
and changes only the severity of `vulnerable` findings: it can lower them from critical to
major, never below, and never touches another status. The JSON always carries both
(`severity_default`, `severity_exposure`, `vector`, `severity_reason` per finding; both overall
severities and exit codes, `severity_mode` and `host_exposure` at the top), so one run serves
both views. Text output in default mode is unchanged.

Each rule states how its bug is exploited (`vector`, per family or per CVE, and on the
`library` block): `remote` (the attacker sends something over the network), `local` (must
already run code on the host), `library` (vulnerable code installed, no exposed consumer
found), `trust` (needs a position in the network path). A rule that does not say is `remote`.

| vector | host | exposure severity |
|--------|------|-------------------|
| remote | a judged port is open to any source | critical |
| remote, `through_proxy` | a judged port is accepted from particular sources | critical: they may be a load balancer or CDN, which forwards an ordinary request |
| remote, not `through_proxy` | all judged ports limited to particular sources | major |
| remote | no accept rule, or no listener | major |
| local | an entry point for foreign code exists | critical |
| local | none found | major |
| library, trust | any | major |

`through_proxy` says whether the attack survives a reverse proxy: true for bugs carried in a
request (PHP, Ruby, Brotli), false for protocol-level ones (TCP options, HTTP/2 framing, ssh).
A remote rule that does not say is treated as true.

Ports judged for a remote finding: the process's own non-loopback TCP listeners; if it listens
only on loopback or a Unix socket (an application server behind nginx), or for a kernel bug,
every non-loopback TCP listener of the host. Each port goes through the same walk of the input
firewall rules as described under Reachability below.

Entry points for foreign code, any one of which keeps a local bug critical:

1. a service other than the host's sshd open to any source;
2. a service accepted from particular sources whose class is web or application, runs commands
   by design, or unknown (see the classes below);
3. a published Docker/podman container whose published ports carry such a service, judged by
   what listens inside the container; any container of a runtime that cannot be judged
   (Kubernetes pods); LXC/Incus guests running on this kernel;
4. a CI runner or build agent (`gitlab-runner`, GitHub Actions, Buildkite, Gitea, Drone,
   Woodpecker, Jenkins and TeamCity agents);
5. a login account that is not an administrator: normal uid, real shell, usable password or
   `authorized_keys`, not in `sudo`/`wheel`/`admin` and not named in sudoers.

Service classes, by executable name; where the name is ambiguous the command line or path
decides. `host_exposure.listeners` carries the class and the evidence per port.

| class | entry point | members |
|-------|-------------|---------|
| admin | no | `sshd` |
| data | no | databases, caches and their sentinels, storage and queue daemons: `mysqld`, `mariadbd`, `postgres`, `redis-*`, `valkey-*`, `keydb-server`, `memcached`, `mongod`, `mongos`, `clickhouse`, `etcd`, `consul`, `minio`, `proxysql`, `pgbouncer`, `slapd`, `gluster*`, `nsq*`; RabbitMQ (`beam.smp` with rabbit on its command line); Kafka, ZooKeeper, Elasticsearch, OpenSearch, Cassandra (`java` by main class) |
| system | no | mail, name, time and RPC daemons, proxies that only relay, virtual machine consoles, monitoring and log agents: Postfix `master`, `exim4`, `dovecot`, `rpcbind`, `systemd-resolved`, `named`, `unbound`, `chronyd`, `ntpd`, `danted`, `xinetd`, `qemu-system-*`, `epmd`, salt master and minion, `zabbix_*`, `netdata`, `vmagent`, `promtail`, `telegraf`, `vector`, `fluent-bit`, `filebeat`, `alloy`, `*_exporter` |
| web | yes | `nginx`, `apache2`, `httpd`, `caddy`, `traefik`, `envoy`, `varnishd`, `php-fpm`, `node`, `bun`, `deno`, `ruby`, `python`, `uwsgi`, `gunicorn`, `dotnet`, other `java` and `beam.smp`, `asterisk` (telephony), Kannel `bearerbox`/`smsbox` (messaging gateway) |
| exec | yes | services that run commands by design: `olivetin` |
| unknown | yes | everything else |

Forwarders count by what they carry. `haproxy` is judged per bound port from its configuration
(the `-f` files of the master process; the worker is chrooted): mode http with servers is web;
a section serving only haproxy's own stats or metrics is system; mode tcp is data only with
positive evidence, a database health check (`option mysql-check`, `pgsql-check`, `redis-check`,
`tcp-check` with Redis or SQL commands) or every backend server on a well-known data port,
because tcp mode also passes TLS through to web servers. An unreadable configuration or a port
not found in it counts as web. `docker-proxy` and DNAT-published container ports take the class
of the process listening inside the container.

What the probe sees is an upper bound: a provider firewall or NAT in front of the host may
close what looks open. Every doubt counts as exposed: no firewall, an accept under a
condition the probe does not evaluate (packet marks on Kubernetes nodes, for example), an
unknown process, an unreadable sudoers. A closed host is never ok because it is closed.

## What it looks at

Kernel (`kind: kernel` rules):

1. Upstream range: kernels before the regression (`affected_from`) are `not_applicable`, kernels
   from an upstream release that already contains the fix (`affected_before`) are `fixed`, e.g. a
   7.0 HWE kernel for a bug fixed upstream in 6.19. Everything in between goes through 2 to 4.
2. Running kernel package changelog containing the CVE id. On Ubuntu that changelog lives in
   `linux-modules-*`, on Debian in `linux-image-*`, on RHEL family in `rpm -q --changelog`.
3. Per-distro fixed-version table from the rule, compared with a dpkg-compatible comparator.
4. Kernel build date (`uname -v`) before the disclosure date means vulnerable.
5. Mitigations: `modprobe -n -v` per module, `/etc/modprobe.d`, `modules.builtin`,
   `/proc/modules`, sysctl values. Built-in or loaded modules cannot be mitigated.
6. Firewall mitigations (`firewall_mitigations` in the rule): `nft list ruleset` (ip/inet
   families) and `iptables-save` / `iptables-legacy-save`, parsed into rules reachable from the
   input, forward and prerouting hooks, including chains entered through unconditional jumps
   (ufw, DOCKER-USER). Each tool runs only when its kernel backend (`nf_tables`, `ip_tables`) is
   already loaded, so the listing never autoloads a module. A rule counts only if nothing before
   it in its chain can accept the packet (an accept rule, or a jump into a chain containing one;
   `ct state established accept` passes a retransmitted SYN, and a loopback accept passes local
   users) and if it is not limited by port, interface or address. It must cover `input`, plus
   `forward` when other network namespaces with interfaces exist (containers of any kind, whose
   traffic is routed past INPUT); a `prerouting` rule covers both. Inside an LXC/Incus container
   the container's own ruleset is checked and turns `host_managed` into `mitigated`.
7. Newest installed kernel, for `reboot_pending`.
8. Exposure hints (`exposure` in the rule, currently only `mptcp`): `net.mptcp.enabled` and the
   MPTCP listening sockets from `ss -Mln`, appended to every non-fixed finding as evidence.
   They never change the status; the public CVE-2026-98432 exploit needs an MPTCP listener and
   Go 1.24+ daemons open one by default, so this tells the operator how exposed the host is.

PHP (`kind: php` rules), discovered from running processes, not from installed packages:

1. Walk `/proc` for `php-fpm*`, `php-cgi*`, `frankenphp`, `lsphp*`, `apache2`/`httpd` with
   `libphp` mapped. CLI processes are ignored (PHP2Shell needs an HTTP SAPI).
2. Container id from `/proc/PID/cgroup`; works for Docker, podman, containerd/k8s, k0s.
   Names are decorated via `docker`/`podman`/`crictl` when present, never required.
   Processes of LXC/Incus guests (cgroup `/lxc.payload.<name>`, `/lxc/<name>`) are skipped on
   the host, together with anything nested inside them: the guest runs its own probe. The
   skipped guest names are printed in the header and in `--facts`.
3. Version and ini from `php-fpm -v` / `php-fpm -i`, executed inside the container with
   `nsenter -t PID -m -u -p`, so what is reported is what actually serves requests.
4. Package evidence read from `/proc/PID/root`: dpkg status and changelog (distro or
   deb.sury.org), apk database (Alpine). Official `php:*` images have no package, so the
   upstream version is compared.
5. Staleness: binary mtime newer than process start, or exe deleted.

Trust store (`kind: trust_store` rules), for CA compromises such as eMudhra 2026:

1. The host bundle (`/etc/ssl/certs/ca-certificates.crt`, RHEL
   `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`, `/etc/ssl/cert.pem`) and the bundle of
   every container found via `/proc/PID/cgroup`, read through `/proc/PID/root`. Containers
   without a bundle (pause, distroless) are skipped, as are LXC/Incus guests and containers
   nested in them.
2. Every certificate in the bundle is SHA-256 fingerprinted and compared with the rule's list,
   so a manual removal (`!` in `/etc/ca-certificates.conf`, RHEL blocklist) counts as fixed
   without any version table. Any listed root present means `vulnerable`.
3. Not covered: trust stores bundled by runtimes (Java cacerts, Node, Python certifi).

Runtime (`kind: runtime` rules), for libraries vendored into runtime binaries such as Brotli in
Node.js:

1. Walk `/proc` for the executables named by the rule (`node`, `nodejs`, `bun`), on the host and
   in containers (not in LXC/Incus guests), grouped per container and binary. The version comes from the binary's own
   `--version`, executed inside its namespaces with `nsenter`, and is compared per release line;
   end-of-life lines are `vulnerable` with no fix. A process that has the system library mapped
   (`/proc/PID/maps` contains the rule's `soname`, as distro builds do) takes the library's verdict
   instead of the vendored one. A fixed binary under processes started before it was installed is
   `stale_workers`.
2. A vulnerable runtime holding a listening TCP or Unix socket is `vulnerable`; one without is
   `unknown`, because exposure then depends on what the code decodes (fetch responses, zlib on
   untrusted data).
3. The system library package (`libbrotli1`, `brotli-libs`, `brotli`) is read in the host root and
   every container root via dpkg status, apk db or host `rpm -q`, compared with the per-distro
   table or, without one, with the upstream fix of its branch. One finding per status across host
   and containers, like the trust store. Roots where the library file exists but no package
   database can be read (rpm-based images on a dpkg host, images without a package manager) are
   reported in `--facts` and `--verbose` only.

4. Package changelog first: when the changelog of the installed package (deb
   `changelog.Debian.gz` in the instance's root, `rpm -q --changelog` on an rpm host) names the
   CVE id, the runtime or library is `fixed` for that CVE, whatever the tables say. No entry or
   no changelog (Alpine, images with stripped docs) proves nothing and the tables decide.
   Runtimes shipped as distro packages (nginx): rules with `fixed_packages` or `fixed_upstream`
   on the runtime judge the package of the running binary by the distro table (keyed by distro id, or `rpm`
   with the major release for the RHEL family; `null` means the vendor has released no fix), and third-party builds (`third_party_re`: sury, nginx.org) or
   unlisted releases by the upstream fix of their branch. A package whose upstream version differs
   from what the running binary reports is ignored: the binary was replaced by hand. A package
   from another upstream branch than the distro's fixed version (a PPA, a mainline image on an
   Alpine base) is not compared with the distro table either.
5. Configuration conditions (`requires_config` per CVE): the runtime's main configuration file
   (the path after `config_arg` on the process command line, else the first existing of
   `config_files`) is read from the instance's root with its `include` directives followed;
   nothing is executed. Every regex must match for the CVE to apply, otherwise the finding is
   `mitigated`, or the CVE's `config_absent_status` (`not_applicable` for features that were
   simply never configured, such as the mail proxy). This is the configuration on disk: an edited but not reloaded file is reported
   by its content, not by what the running master loaded.
   A directive that switches the feature off (`mitigated_if_config`, unless `unless_config` also
   matches, e.g. `PasswordAuthentication no` with no `yes` anywhere) gives `mitigated`. Include
   syntax other than nginx's is set per runtime with `config_include_re`.
   Build conditions (`requires_mapped`, `exempt_if`): regexes over `/proc/PID/maps` of the running
   process decide whether this build is the affected one at all, e.g. musl libc mapped and PAM
   not in use; otherwise the finding is `not_applicable` before anything else is checked.
6. Reachability: with the configuration present, each non-loopback TCP listener (only the ports
   whose `listen` carries `listen_param`, e.g. `http2`, when that can be told) is walked through
   the input hook of every table (iptables-save, ip6tables-save, nft) as a new connection from
   an outside interface. An accept with no source condition, an accept policy, or anything the
   probe cannot evaluate means open to any source: `vulnerable`. Only source-limited accepts
   (`-s`, ipset, `ip saddr`, or an interface without a default route) or none at all:
   `restricted`. IPv6 is checked when the host has a global IPv6 address. Containers: a DNAT or
   docker-proxy rule to the container address, or a runtime other than Docker/podman, counts as
   open; a Docker/podman container that publishes nothing is `restricted`.

## Rule files

One JSON file per CVE family in `rules/`. Entries under `cves` are keyed by CVE id, or by an
advisory-style id when no CVE exists (`EMUDHRA-CA-2026`). Keys:

```
family, title, kind (kernel|php|trust_store|runtime), references[], public (YYYY-MM-DD), remedy,
vector (remote|local|library|trust), through_proxy (true|false, remote rules)
cves: { "CVE-...": { public, affected_from, affected_before, modules[], sysctl_mitigations[],
                     firewall_mitigations[], exposure[], not_affected_distros{}, fixed{}, mitigations[] } }
```

Family-level `modules`, `sysctl_mitigations`, `firewall_mitigations`, `exposure`, `affected_from`,
`fixed` and `remedy` apply to every CVE unless the CVE overrides them. `remedy` is appended to
vulnerable findings.

`firewall_mitigations` entries are `{"tool": "nft"|"iptables", "match": regex, "unless": regex}`
applied to one rule line as `nft list ruleset` or `iptables-save` prints it (iptables saves
`--u32` in hex: `0x0>>0x18&0xf=0x6:0xf`). `match` must include the verdict; `unless` rejects
port-limited variants.

Kernel `fixed` tables, keyed by distro id (`ubuntu`, `debian`) or family (`rpm`):

```
"ubuntu": [ {"match": "^6\\.8\\.0-\\d+-(generic|lowlatency)", "fixed": "6.8.0-117"} ]
"debian": [ {"release": "12", "match": "^6\\.1\\.", "fixed": "6.1.170-1"} ]
"rpm":    [ {"match": "^6\\.12\\.0-124\\.", "fixed": "6.12.0-124.55.1.el10_1"},
            {"match": "^6\\.12\\.0-", "fixed": "6.12.0-124.55.1.el10_1"} ]
```

`match` is a regex over `uname -r`; entries are tried in order, so put specific streams
before catch-alls. `"fixed": null` means the vendor lists the series as vulnerable with no
fix released (the kernel is reported vulnerable regardless of version). The compared string is the Ubuntu ABI (`6.8.0-107`), the Debian package
version from `/proc/version`, or the RHEL version-release without arch.

Trust store rules: `certs` per entry (`name`, `sha256` fingerprint, optional `files` as named
in `/etc/ca-certificates.conf`) and a `remedy` sentence printed with the finding.

Runtime rules: `runtimes` keyed by name (`exe` regex over the basename, `version_arg`,
`version_re`, `fixed` per major line, `eol_lines`, `not_affected_before`, `packages` per family,
`config_arg`, `config_files`, `config_include_re`, `variants[]` (recognised by a `file` marker in the instance's root or a `banner` regex over the
version output; `label`, own `remedy`, optional `name` and `version_re` for the product's own version,
optional `fixed` per core branch for products that backport without changing the core version: the
runtime shipped inside a product with its own lifecycle, e.g. ingress-nginx, OpenResty), `fixed_packages` per distro release, `fixed_upstream` per branch, `third_party_re`;
`no_listener_text` for the `unknown` finding of a vulnerable runtime without a listening socket;
per CVE `affected_from`, `requires_config[]`, `config_absent_status`, `mitigated_if_config`, `unless_config`,
`requires_mapped[]`, `exempt_if{mapped, config}`, `listen_param`, `listen_all_if`, `exposure[]`)
and `library` (`packages`
per family, a name or list of names, `soname`, `fixed_upstream` per branch, `fixed_packages` per distro release, `rpm`
keyed by major release, its own `remedy`). Distroless images are read via `dpkg/status.d`.

PHP rules: `fixed_upstream` per branch, `eol_branches`, `fixed_packages` per origin
(`sury` per branch, distro id per release per source package), and per-CVE `mitigations`
as ini conditions (`equals` or `in`, optional `branch_min`).

Adding a CVE: copy the closest rule file, fill the tables from the vendor pages listed in
`references`, ship the package. No code change needed unless a new kind of evidence is required.

Sources for the tables: `https://ubuntu.com/security/CVE-...`,
`https://security-tracker.debian.org/tracker/CVE-...`,
`https://access.redhat.com/hydra/rest/securitydata/cve/CVE-....json`,
`https://launchpad.net/~ondrej/+archive/ubuntu/php/+packages`.
