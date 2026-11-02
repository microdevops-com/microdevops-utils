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

`--only <family>` or `--only <id>` restricts a run to one row. When a rule file is added, add its row here.

## Usage

```
/opt/microdevops/cve_probe/cve_probe.py            # text report, exit code per severity
/opt/microdevops/cve_probe/cve_probe.py --json     # machine-readable report
/opt/microdevops/cve_probe/cve_probe.py --all      # text report including ok findings
/opt/microdevops/cve_probe/cve_probe.py --only php2shell --only CVE-2026-31431
/opt/microdevops/cve_probe/cve_probe.py --kernel-only | --php-only
/opt/microdevops/cve_probe/cve_probe.py --json --facts   # add raw kernel/php facts
```

Exit codes, meant for cmd_check_alert `severity_per_retcode`:

| exit | severity | statuses |
|------|----------|----------|
| 0 | ok | fixed, not_applicable |
| 1 | probe error | could not run (not root, bad rules) |
| 2 | minor | mitigated |
| 3 | major | reboot_pending, stale_workers, host_managed, unknown |
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
- `unknown` - no evidence either way (no changelog, no table entry, built after disclosure).
- `fixed`, `not_applicable`.

## What it looks at

Kernel (`kind: kernel` rules):

1. Upstream range: kernels before the regression are `not_applicable`.
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

PHP (`kind: php` rules), discovered from running processes, not from installed packages:

1. Walk `/proc` for `php-fpm*`, `php-cgi*`, `frankenphp`, `lsphp*`, `apache2`/`httpd` with
   `libphp` mapped. CLI processes are ignored (PHP2Shell needs an HTTP SAPI).
2. Container id from `/proc/PID/cgroup`; works for Docker, podman, containerd/k8s, k0s.
   Names are decorated via `docker`/`podman`/`crictl` when present, never required.
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
   without a bundle (pause, distroless) are skipped.
2. Every certificate in the bundle is SHA-256 fingerprinted and compared with the rule's list,
   so a manual removal (`!` in `/etc/ca-certificates.conf`, RHEL blocklist) counts as fixed
   without any version table. Any listed root present means `vulnerable`.
3. Not covered: trust stores bundled by runtimes (Java cacerts, Node, Python certifi).

## Rule files

One JSON file per CVE family in `rules/`. Entries under `cves` are keyed by CVE id, or by an
advisory-style id when no CVE exists (`EMUDHRA-CA-2026`). Keys:

```
family, title, kind (kernel|php|trust_store), references[], public (YYYY-MM-DD), remedy
cves: { "CVE-...": { public, affected_from, affected_before, modules[], sysctl_mitigations[],
                     firewall_mitigations[], not_affected_distros{}, fixed{}, mitigations[] } }
```

Family-level `modules`, `sysctl_mitigations`, `firewall_mitigations`, `affected_from`, `fixed`
and `remedy` apply to every CVE unless the CVE overrides them. `remedy` is appended to
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

PHP rules: `fixed_upstream` per branch, `eol_branches`, `fixed_packages` per origin
(`sury` per branch, distro id per release per source package), and per-CVE `mitigations`
as ini conditions (`equals` or `in`, optional `branch_min`).

Adding a CVE: copy the closest rule file, fill the tables from the vendor pages listed in
`references`, ship the package. No code change needed unless a new kind of evidence is required.

Sources for the tables: `https://ubuntu.com/security/CVE-...`,
`https://security-tracker.debian.org/tracker/CVE-...`,
`https://access.redhat.com/hydra/rest/securitydata/cve/CVE-....json`,
`https://launchpad.net/~ondrej/+archive/ubuntu/php/+packages`.
