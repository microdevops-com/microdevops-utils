#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# cve_probe - read-only probe answering one narrow question per critical CVE:
# is THIS host exploitable right now, and through what (kernel, package, container)?
#
# It is not a vulnerability scanner. It knows only the CVEs described by the rule
# files in rules/ and gathers the specific evidence those rules need.
#
# Constraints: Python 3.5 syntax, standard library only, no state changes on the host.
# In particular it never loads kernel modules (modprobe is only used with -n, dry run).

import argparse
import base64
import binascii
import glob
import hashlib
import gzip
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from datetime import date, datetime

VERSION = "1.15"
RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
CMD_TIMEOUT = 20

# Status -> severity (agreed with the fleet alert policy), severity -> exit code.
STATUS_SEVERITY = {
    "vulnerable": "critical",
    "reboot_pending": "major",
    "stale_workers": "major",
    "host_managed": "major",
    "unknown": "major",
    "restricted": "major",
    "mitigated": "minor",
    "fixed": "ok",
    "not_applicable": "ok",
}
SEVERITY_EXIT = {"ok": 0, "minor": 2, "major": 3, "critical": 4}
SEVERITY_RANK = {"ok": 0, "minor": 1, "major": 2, "critical": 3}
EXIT_PROBE_ERROR = 1

VERBOSE = False


def log(msg):
    if VERBOSE:
        sys.stderr.write("[cve_probe] %s\n" % msg)


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def run(cmd, timeout=CMD_TIMEOUT, cwd=None):
    """Run a command, return (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                             universal_newlines=True)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            return (-9, out or "", "timeout")
        return (p.returncode, out or "", err or "")
    except OSError as e:
        return (-1, "", str(e))


def read_file(path, default=None):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except (IOError, OSError):
        return default


def read_gz(path):
    try:
        with gzip.open(path, "rt", errors="replace") as f:
            return f.read()
    except (IOError, OSError, EOFError):
        return None


def which(name):
    for d in os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin").split(":") + \
            ["/usr/sbin", "/usr/bin", "/sbin", "/bin", "/usr/local/sbin", "/usr/local/bin"]:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def parse_os_release(text):
    d = {}
    for line in (text or "").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def in_root(root, path):
    """Resolve path inside another root (e.g. /proc/PID/root), following symlinks without
    escaping the root: every hop is normalised as an absolute path *inside* the root, so
    leading ".." collapse at the root's top. Bounded, so a loop cannot hang the probe."""
    cur = os.path.normpath("/" + path.lstrip("/"))
    for _ in range(8):
        full = os.path.join(root, cur.lstrip("/"))
        try:
            if not os.path.islink(full):
                break
            target = os.readlink(full)
        except OSError:
            break
        if target.startswith("/"):
            cur = os.path.normpath(target)
        else:
            cur = os.path.normpath(os.path.join(os.path.dirname(cur), target))
    return os.path.join(root, cur.lstrip("/"))


def apk_version(db, names):
    """(package, version) of the first of `names` installed per an Alpine /lib/apk/db/installed."""
    found = {}
    for block in (db or "").split("\n\n"):
        rec = dict((l[0], l[2:]) for l in block.splitlines() if len(l) > 2 and l[1] == ":")
        if rec.get("P") in names:
            found[rec["P"]] = rec.get("V")
    for n in names:
        if n in found:
            return (n, found[n])
    return None


# dpkg-compatible version comparison (also fine for rpm-style EVRs we meet here).

def _order(c):
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    return ord(c) + 256


def _verrevcmp(a, b):
    i, j = 0, 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _order(a[i]) if i < len(a) else 0
            bc = _order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def _split_version(v):
    epoch = 0
    if ":" in v:
        e, v = v.split(":", 1)
        if e.isdigit():
            epoch = int(e)
    if "-" in v:
        up, rev = v.rsplit("-", 1)
    else:
        up, rev = v, ""
    return epoch, up, rev


def vercmp(a, b):
    """Return <0, 0, >0 like dpkg --compare-versions."""
    ea, ua, ra = _split_version(a.strip())
    eb, ub, rb = _split_version(b.strip())
    if ea != eb:
        return ea - eb
    r = _verrevcmp(ua, ub)
    if r:
        return r
    return _verrevcmp(ra, rb)


def version_tuple(s):
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", s or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def parse_build_date(text):
    """Pull a build date out of `uname -v` / /proc/version / `php -v` text."""
    if not text:
        return None
    m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", text)  # Debian: (2025-05-10)
    if m:
        return parse_date(m.group(1))
    m = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +(\d{1,2}) +(?:\d\d:\d\d:\d\d +\S+ +)?(\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        except ValueError:
            return None
    return None


# ----------------------------------------------------------------------------
# Host facts
# ----------------------------------------------------------------------------

class Host(object):
    def __init__(self):
        self.hostname = socket.gethostname()
        self.os = parse_os_release(read_file("/etc/os-release", ""))
        self.distro = self.os.get("ID", "unknown").lower()
        self.release = self.os.get("VERSION_ID", "")
        self.codename = self.os.get("VERSION_CODENAME", "") or self.os.get("UBUNTU_CODENAME", "")
        self.family = self._family(self.distro, self.os.get("ID_LIKE", ""))
        self.virt = self._virt()
        self.is_container = self.virt in ("lxc", "lxc-libvirt", "docker", "podman", "containerd",
                                          "systemd-nspawn", "openvz", "rkt", "wsl", "container")
        self.arch = os.uname()[4]

    @staticmethod
    def _family(distro, id_like):
        s = " ".join([distro, id_like]).lower()
        if distro in ("debian", "ubuntu") or "debian" in s:
            return "deb"
        if "rhel" in s or "fedora" in s or "centos" in s:
            return "rpm"
        if distro == "alpine":
            return "apk"
        return "unknown"

    @staticmethod
    def _virt():
        if which("systemd-detect-virt"):
            rc, out, _ = run(["systemd-detect-virt"], timeout=5)
            v = out.strip()
            if v and v != "none":
                return v
            if rc == 0 and v:
                return v
        env = read_file("/proc/1/environ", "") or ""
        m = re.search(r"container=([a-z0-9-]+)", env)
        if m:
            return m.group(1)
        if os.path.exists("/.dockerenv"):
            return "docker"
        c = read_file("/run/systemd/container", "")
        if c and c.strip():
            return c.strip()
        return "none"

    def as_dict(self):
        return {"hostname": self.hostname, "distro": self.distro, "release": self.release,
                "codename": self.codename, "family": self.family, "virt": self.virt,
                "is_container": self.is_container, "arch": self.arch}


# ----------------------------------------------------------------------------
# Kernel facts
# ----------------------------------------------------------------------------

class KernelImage(object):
    """One kernel: the running one, or an installed one that is not running."""

    def __init__(self, release, host, running=False):
        self.release = release            # uname -r style, e.g. 6.8.0-107-generic
        self.running = running
        self.host = host
        self.version = None               # package version string if owned by a package
        self.package = None
        self.changelog = None             # text or None
        self.changelog_from = None        # package the changelog was read from
        self.build_date = None
        self.upstream = version_tuple(release)
        self._collect()

    def _collect(self):
        h = self.host
        if h.family == "deb":
            for name in ("linux-image-%s" % self.release, "linux-modules-%s" % self.release,
                         "linux-image-extra-%s" % self.release):
                rc, out, _ = run(["dpkg-query", "-W", "-f", "${Version}\t${Status}", name], timeout=10)
                if rc == 0 and out.split()[-1:] == ["installed"]:
                    ver = out.split("\t")[0].strip()
                    if self.package is None:
                        self.package, self.version = name, ver
                    # Ubuntu ships the CVE-listing changelog in linux-modules (changelog.Debian.gz),
                    # Debian in linux-image (changelog.gz).
                    cl = (read_gz("/usr/share/doc/%s/changelog.Debian.gz" % name)
                          or read_gz("/usr/share/doc/%s/changelog.gz" % name))
                    if cl and (self.changelog is None or cl.count("CVE-") > self.changelog.count("CVE-")):
                        self.changelog, self.changelog_from = cl, name
        elif h.family == "rpm":
            for name in ("kernel-core-%s" % self.release, "kernel-%s" % self.release,
                         "kernel-uek-core-%s" % self.release):
                rc, out, _ = run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", name], timeout=10)
                if rc == 0 and out.strip() and "not installed" not in out:
                    self.package, self.version = name, out.strip()
                    rc2, cl, _ = run(["rpm", "-q", "--changelog", name], timeout=30)
                    if rc2 == 0:
                        self.changelog, self.changelog_from = cl, name
                    break
        if self.running:
            self.build_date = parse_build_date(os.uname()[3]) or parse_build_date(read_file("/proc/version", ""))
        elif self.changelog:
            # Newest changelog entry date is good enough for an installed kernel.
            m = re.search(r"^ -- .*?  (\w{3}, \d{1,2} \w{3} \d{4})", self.changelog, re.M)
            if m:
                try:
                    self.build_date = datetime.strptime(m.group(1), "%a, %d %b %Y").date()
                except ValueError:
                    pass
            m = re.search(r"^\* (\w{3} \w{3} +\d{1,2} \d{4})", self.changelog, re.M)
            if m and not self.build_date:
                try:
                    self.build_date = datetime.strptime(re.sub(r" +", " ", m.group(1)), "%a %b %d %Y").date()
                except ValueError:
                    pass

    def distro_version_string(self):
        """The string compared against rule fixed versions, per distro convention."""
        h = self.host
        if h.distro == "ubuntu":
            m = re.match(r"(\d+\.\d+\.\d+-\d+)", self.release)
            return m.group(1) if m else self.release
        if h.distro == "debian":
            if self.version:
                return self.version
            if self.running:
                m = re.search(r"Debian (\S+)", read_file("/proc/version", "") or "")
                if m:
                    return m.group(1)
            return None
        if h.family == "rpm":
            return re.sub(r"\.(x86_64|aarch64|ppc64le|s390x|i686|noarch)$", "", self.version or self.release)
        return self.version or self.release

    def as_dict(self):
        return {"release": self.release, "running": self.running, "package": self.package,
                "version": self.version, "build_date": str(self.build_date) if self.build_date else None,
                "has_changelog": bool(self.changelog)}


class KernelFacts(object):
    def __init__(self, host):
        self.host = host
        self.release = os.uname()[2]
        self.running = KernelImage(self.release, host, running=True)
        self.installed = self._installed()
        self.newest = self._newest()
        self.modules_dir = "/lib/modules/%s" % self.release
        self.modules_dir_present = os.path.isdir(self.modules_dir)
        self.builtin = self._builtin()
        self.loaded = self._loaded()
        self.kconfig = self._kconfig()
        self.modprobe_conf = self._modprobe_conf()
        self.sysctl = {}
        self._exposure = {}
        self._module_cache = {}
        self._fw_rules = None       # collected on first use, only rules with firewall_mitigations need it
        self._fw_chains = None
        self._reach = {}
        self._publish_texts = None
        self._foreign_netns = None

    def _installed(self):
        rels = set()
        h = self.host
        if h.family == "deb":
            rc, out, _ = run(["dpkg-query", "-W", "-f", "${Package}\t${Status}\n", "linux-image-*"], timeout=10)
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) == 2 and parts[1].split()[-1:] == ["installed"]:
                    m = re.match(r"linux-image-(\d\S+)", parts[0])
                    if m:
                        rels.add(m.group(1))
        elif h.family == "rpm":
            rc, out, _ = run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}.%{ARCH}\n", "kernel-core", "kernel"], timeout=10)
            for line in out.splitlines():
                if line and "not installed" not in line:
                    rels.add(line.strip())
        return sorted(rels)

    def _newest(self):
        best = None
        for r in self.installed:
            if best is None or vercmp(r, best) > 0:
                best = r
        if best and best != self.release:
            return KernelImage(best, self.host)
        return None

    def _builtin(self):
        text = read_file(os.path.join(self.modules_dir, "modules.builtin"), "") or ""
        return set(os.path.basename(l).replace(".ko", "").replace("-", "_") for l in text.split())

    @staticmethod
    def _loaded():
        text = read_file("/proc/modules", "") or ""
        return set(l.split()[0] for l in text.splitlines() if l.split())

    def _kconfig(self):
        for p in ("/boot/config-%s" % self.release, "/lib/modules/%s/config" % self.release):
            t = read_file(p)
            if t:
                d = {}
                for line in t.splitlines():
                    if line.startswith("CONFIG_") and "=" in line:
                        k, v = line.split("=", 1)
                        d[k] = v
                    elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
                        d[line[2:].split(" ")[0]] = "n"
                return d
        t = read_gz("/proc/config.gz")
        if t:
            return self._kconfig_from_text(t)
        return {}

    @staticmethod
    def _kconfig_from_text(t):
        d = {}
        for line in t.splitlines():
            if line.startswith("CONFIG_") and "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
        return d

    @staticmethod
    def _modprobe_conf():
        rules = []
        for p in sorted(glob.glob("/etc/modprobe.d/*.conf")) + sorted(glob.glob("/lib/modprobe.d/*.conf")) + \
                sorted(glob.glob("/usr/lib/modprobe.d/*.conf")) + sorted(glob.glob("/run/modprobe.d/*.conf")):
            for line in (read_file(p, "") or "").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rules.append((p, line))
        return rules

    def sysctl_value(self, key):
        if key not in self.sysctl:
            self.sysctl[key] = (read_file("/proc/sys/" + key.replace(".", "/"), "") or "").strip() or None
        return self.sysctl[key]

    def exposure(self, name):
        """Evidence that sharpens a non-fixed verdict without changing it. "mptcp": the sysctl
        and the MPTCP listening sockets (`ss -Mln`), since the public exploit chain for
        CVE-2026-98432 needs an MPTCP listener and Go >= 1.24 opens one by default."""
        if name in self._exposure:
            return self._exposure[name]
        info = None
        if name == "mptcp":
            enabled = self.sysctl_value("net.mptcp.enabled")
            if enabled is not None:
                info = {"sysctl": enabled, "listeners": None}
                if which("ss"):
                    rc, out, _ = run(["ss", "-Mlnp"], timeout=CMD_TIMEOUT)
                    if rc == 0:
                        seen = []
                        for line in out.splitlines():
                            parts = line.split()
                            if len(parts) < 4 or parts[0] != "LISTEN":
                                continue
                            m = re.search(r'\(\("([^"]+)"', line)
                            item = (m.group(1) if m else "?", parts[3])
                            if item not in seen:
                                seen.append(item)
                        info["listeners"] = seen
                text = "net.mptcp.enabled=%s" % enabled
                if info["listeners"] is None:
                    text += ", MPTCP listeners unknown (ss lacks -M)"
                elif info["listeners"]:
                    names = ["%s %s" % it for it in info["listeners"][:6]]
                    if len(info["listeners"]) > 6:
                        names.append("...")
                    text += ", %d MPTCP listener(s): %s" % (len(info["listeners"]), ", ".join(names))
                else:
                    text += ", no MPTCP listener"
                info["text"] = text
        elif name == "sctp":
            # the published nginx chain reaches root through a kernel SCTP flaw (no CVE id yet)
            st = self.module_state("sctp")
            if self.host.is_container and st["state"] not in ("loaded", "builtin"):
                st = {"state": "state not visible from this container, the kernel belongs to the host"}
            info = {"module": st["state"],
                    "text": "sctp module %s%s" % (st["state"], {
                        "loadable": " (autoloads on demand: worker-to-root chain possible; block with modprobe.d install sctp /bin/false)",
                        "loaded": " (worker-to-root chain possible)",
                        "builtin": " (worker-to-root chain possible)"}.get(st["state"], ""))}
        self._exposure[name] = info
        return info

    def module_state(self, mod):
        """How a module could reach the kernel: loaded / builtin / blocked / absent / loadable."""
        if mod in self._module_cache:
            return self._module_cache[mod]
        norm = mod.replace("-", "_")
        st = {"module": mod, "loaded": norm in self.loaded or mod in self.loaded,
              "builtin": norm in self.builtin, "state": None, "evidence": ""}
        if st["builtin"]:
            st["state"] = "builtin"
            st["evidence"] = "listed in modules.builtin"
        elif st["loaded"]:
            st["state"] = "loaded"
            st["evidence"] = "present in /proc/modules"
        else:
            rc, out, err = run(["modprobe", "-n", "-v", mod], timeout=10) if which("modprobe") else (-1, "", "no modprobe")
            text = (out + err).strip()
            install_block = [l for (_, l) in self.modprobe_conf
                             if re.match(r"install\s+%s\s+(/bin/false|/bin/true|/usr/bin/false|/usr/bin/true)\b" % re.escape(norm), l)
                             or re.match(r"install\s+%s\s+(/bin/false|/bin/true|/usr/bin/false|/usr/bin/true)\b" % re.escape(mod), l)]
            blacklist = [l for (_, l) in self.modprobe_conf if re.match(r"blacklist\s+(%s|%s)\s*$" % (re.escape(norm), re.escape(mod)), l)]
            if re.search(r"^install .*(/bin/false|/bin/true)", text, re.M) or install_block:
                st["state"] = "blocked"
                st["evidence"] = "modprobe.d install rule: %s" % (install_block[0] if install_block else text.splitlines()[-1])
            elif rc != 0 and ("not found" in text or "Module %s not found" % mod in text):
                st["state"] = "absent"
                st["evidence"] = "module file missing for running kernel (%s)" % self.release
            elif re.search(r"^insmod ", text, re.M):
                st["state"] = "loadable"
                st["evidence"] = "modprobe -n would insmod it"
                if blacklist:
                    st["state"] = "blacklisted"
                    st["evidence"] = "blacklist line only (%s); alias autoload blocked, explicit load still possible" % blacklist[0]
            elif rc == 0 and not text:
                # modprobe prints nothing for a builtin module, but builtins are normally caught above
                # via modules.builtin; module names do not map to kconfig symbols generically, so
                # without that file the honest answer is unknown (major: somebody has to look).
                st["state"] = "unknown"
                st["evidence"] = "modprobe -n printed nothing"
            else:
                st["state"] = "unknown"
                st["evidence"] = text[-200:] if text else "no modprobe output"
        self._module_cache[mod] = st
        return st

    def firewall_rules(self):
        """netfilter rules reachable from the input/forward/prerouting hooks (nft + iptables).
        A listing tool is only run when its kernel backend is already present: nft and
        iptables-nft need nf_tables, legacy iptables needs ip_tables; running them otherwise
        would autoload the module, which this probe promises not to do."""
        if self._fw_rules is None:
            ch = self.fw_chains()
            self._fw_rules = _nft_ruleset(dict((k, v) for k, v in ch["nft"].items() if k[0] in ("ip", "inet"))) + \
                _iptables_ruleset(ch["ip"])
            log("firewall: %d rules on input/forward/prerouting hooks" % len(self._fw_rules))
        return self._fw_rules

    def fw_chains(self):
        """Parsed chains with their policies: nft (all families), iptables-save, ip6tables-save.
        Same backend rule as firewall_rules(): a tool only runs when its module is present."""
        if self._fw_chains is None:
            has = lambda m: m in self.loaded or m in self.builtin
            nft_ok = has("nf_tables")
            self._fw_chains = {"nft": _nft_chains(nft_ok),
                               "ip": _iptables_chains(nft_ok, has("ip_tables"), ""),
                               "ip6": _iptables_chains(nft_ok, has("ip6_tables"), "6")}
        return self._fw_chains

    def port_reachability(self, fam, port):
        """Who can open a new TCP connection to a local port, judged from the input hook of
        every table: ("open", rule) when some accept needs no particular source, ("restricted",
        n) when only n source- or interface-limited accepts exist, ("closed", 0) when nothing
        accepts it. fam is "ip" or "ip6". Every base chain must accept a packet, so the most
        restrictive chain wins; anything not understood counts as open."""
        key = (fam, port)
        if key in self._reach:
            return self._reach[key]
        ch = self.fw_chains()
        pub = _default_ifaces(fam)
        results = []
        ipt = ch[fam]
        for k, c in ipt.items():
            if c.get("hook") == "input" and k[1] in ("filter", "mangle", "security"):
                results.append(_walk_base(ipt, k, lambda t: _ipt_cond(t, port, pub), "iptables"))
        nft = ch["nft"]
        xt_seen = bool(ipt)
        for k, c in nft.items():
            if c.get("hook") != "input" or c.get("type") != "filter":
                continue
            if k[0] not in (fam, "inet"):
                continue
            if xt_seen and k[0] in ("ip", "ip6") and k[2] in ("INPUT",):
                continue          # iptables-nft table, already judged from iptables-save
            results.append(_walk_base(nft, k, lambda t: _nft_cond(t, port, fam, pub), "nft"))
        if not results:
            out = ("open", "no firewall rules on the input hook")
        elif any(r[0] == "closed" for r in results):
            out = ("closed", 0)
        elif any(r[0] == "restricted" for r in results):
            out = ("restricted", min(r[1] for r in results if r[0] == "restricted"))
        else:
            details = [r[1] for r in results]
            out = ("open", ([d for d in details if not d.endswith("policy accept")] or details)[0])
        log("reachability %s port %s: %s" % (fam, port, out))
        self._reach[key] = out
        return out

    def foreign_netns(self):
        """Number of other network namespaces with processes and a non-loopback interface:
        containers of any kind (OCI, LXC, Incus) whose sockets live on this kernel and receive
        routed traffic through our forward hook. Host-network containers share our namespace."""
        if self._foreign_netns is None:
            try:
                own = os.readlink("/proc/self/ns/net")
            except OSError:
                own = None
            seen = {}
            for d in os.listdir("/proc"):
                if not d.isdigit():
                    continue
                try:
                    ns = os.readlink("/proc/%s/ns/net" % d)
                except OSError:
                    continue
                if ns == own or ns in seen:
                    continue
                dev = read_file("/proc/%s/net/dev" % d, "") or ""
                ifaces = [l.split(":")[0].strip() for l in dev.splitlines()[2:] if ":" in l]
                seen[ns] = bool([i for i in ifaces if i != "lo"])
            self._foreign_netns = len([v for v in seen.values() if v])
        return self._foreign_netns

    def firewall_coverage(self, specs):
        """Match firewall_mitigations specs against the ruleset. Returns (hits, problem):
        hits are the rules that close the path on every hook an inbound SYN can take here:
        input, plus forward when other network namespaces receive routed traffic; a prerouting
        rule covers both. problem explains why found rules are not enough; (None) when nothing
        resembling the mitigation exists at all."""
        matched, partial = [], []
        for r in self.firewall_rules():
            for sp in specs:
                if sp.get("tool") != r["tool"] or not re.search(sp["match"], r["text"]):
                    continue
                if sp.get("unless") and re.search(sp["unless"], r["text"]):
                    partial.append(r)
                else:
                    matched.append(r)
                break
        if not matched and not partial:
            return [], None
        need = set(["input"])
        nforeign = 0 if self.host.is_container else self.foreign_netns()
        if nforeign:
            need.add("forward")
        covered = set()
        good, problems = [], []
        for r in matched:
            if not r["effective"]:
                problems.append("%s %s rule '%s' sits behind accept rule '%s', SYNs can be accepted before it" %
                                (r["tool"], r["where"], r["text"], r["after"]))
                continue
            hooks = set(r["hooks"])
            if "prerouting" in hooks:
                hooks.update(["input", "forward"])
            covered.update(hooks)
            good.append(r)
        for r in partial[:2]:
            problems.append("%s %s rule '%s' is limited by interface, address or port, not counted" %
                            (r["tool"], r["where"], r["text"]))
        missing = need - covered
        if missing:
            if good:
                why = []
                if "input" in missing:
                    why.append("input (this host's own sockets) is open")
                if "forward" in missing:
                    why.append("forward is open and %d other network namespaces (containers) receive routed traffic through it" % nforeign)
                problems.append("%s rule covers only %s hook(s); %s; use raw PREROUTING" %
                                (good[0]["tool"], "/".join(sorted(covered)), "; ".join(why)))
            return [], "; ".join(problems)
        return good, None

    def as_dict(self):
        d = {"running": self.running.as_dict(), "installed": self.installed,
             "newest_installed": self.newest.as_dict() if self.newest else None,
             "modules_dir_present": self.modules_dir_present,
             "kconfig_available": bool(self.kconfig)}
        if self._fw_rules is not None:
            d["firewall_rules_on_hooks"] = len(self._fw_rules)
        if self._exposure:
            d["exposure"] = self._exposure
        return d


# ----------------------------------------------------------------------------
# Firewall rules: netfilter mitigations read from `nft list ruleset` and `iptables-save`
# ----------------------------------------------------------------------------

FW_HOOKS = ("input", "forward", "prerouting")
IPT_BUILTIN_HOOK = {"INPUT": "input", "FORWARD": "forward", "PREROUTING": "prerouting"}
NFT_TABLE_RE = re.compile(r"^table\s+(\S+)\s+(\S+)\s*\{")
NFT_CHAIN_RE = re.compile(r"^\s+chain\s+(\S+)\s*\{")
NFT_HOOK_RE = re.compile(r"^\s+type\s+(\S+)\s+hook\s+(\S+)\s")
NFT_JUMP_RE = re.compile(r"^(?:counter(?:\s+packets\s+\d+\s+bytes\s+\d+)?\s+)?(?:jump|goto)\s+(\S+)$")
IPT_JUMP_RE = re.compile(r"^-A\s+\S+\s+-j\s+(\S+)$")
IPT_COMMENT_RE = re.compile(r"\s+-m\s+comment\s+--comment\s+(\"[^\"]*\"|\S+)")
NFT_COMMENT_RE = re.compile(r"\s+comment\s+\"[^\"]*\"$")


def _hooked_rules(tool, chains, jump_of, is_accept):
    """Flatten chains into rule dicts carrying the hooks each rule is reachable from.
    chains: key -> {"hook", "type", "rules"}; key is a tuple whose last item is the chain name.
    A chain is reachable from a hook when it is a filter base chain of that hook, or when a
    reachable chain jumps to it unconditionally. A rule is "effective" when nothing before it
    on the way from the hook can accept the packet: neither an accept rule nor a jump into a
    chain that (transitively) contains one, in its own chain or in the chains it was entered
    through. An earlier accept, typically ct state established, passes a retransmitted SYN
    before the mitigation sees it; a loopback accept passes local users."""
    def chain_accept(key):
        """First accept reachable inside a chain (own rule or through a jump), memoised; None if none."""
        ch = chains[key]
        if "accept_text" in ch:
            return ch["accept_text"]
        ch["accept_text"] = None          # set before recursing: cycles resolve to None
        for t in ch["rules"]:
            if is_accept(t):
                ch["accept_text"] = t
                break
            dst = jump_of(t)
            dkey = key[:-1] + (dst,) if dst else None
            if dkey in chains and chain_accept(dkey):
                ch["accept_text"] = "%s -> %s" % (t, chains[dkey]["accept_text"])
                break
        return ch["accept_text"]

    first_accept = {}          # key -> (index of first accepting rule or jump, its text)
    for key, ch in chains.items():
        first_accept[key] = (len(ch["rules"]), None)
        for i, t in enumerate(ch["rules"]):
            if is_accept(t):
                first_accept[key] = (i, t)
                break
            dst = jump_of(t)
            dkey = key[:-1] + (dst,) if dst else None
            if dkey in chains and chain_accept(dkey):
                first_accept[key] = (i, "%s -> %s" % (t, chains[dkey]["accept_text"]))
                break
    reach, clean, blocked = {}, {}, {}
    for key, ch in chains.items():
        if ch.get("hook") in FW_HOOKS and ch.get("type", "filter") == "filter":
            reach[key] = set([ch["hook"]])
            clean[key] = set([ch["hook"]])
    changed = True
    while changed:
        changed = False
        for key in list(reach.keys()):
            fa, fatext = first_accept[key]
            for i, t in enumerate(chains[key]["rules"]):
                dst = jump_of(t)
                dkey = key[:-1] + (dst,) if dst else None
                if dkey not in chains:
                    continue
                if reach[key] - reach.get(dkey, set()):
                    reach.setdefault(dkey, set()).update(reach[key])
                    changed = True
                if key in clean and i <= fa:
                    # the jump at index fa is the first-accept item itself: its target is still
                    # entered before anything accepted, so the target's leading rules count
                    if clean[key] - clean.get(dkey, set()):
                        clean.setdefault(dkey, set()).update(clean[key])
                        changed = True
                elif dkey not in clean and dkey not in blocked:
                    blocked[dkey] = fatext if key in clean else blocked.get(key)
                    changed = True
    rules = []
    for key, hooks in reach.items():
        fa, fatext = first_accept[key]
        for i, t in enumerate(chains[key]["rules"]):
            eff = key in clean and i < fa
            rules.append({"tool": tool, "where": "/".join(key[-2:]), "hooks": sorted(clean.get(key) or hooks),
                          "text": t, "effective": eff,
                          "after": None if eff else (fatext if key in clean else blocked.get(key))})
    return rules


def _nft_chains(nft_ok):
    """Chains from `nft list ruleset`, every family, keyed (family, table, chain), with hook,
    type and policy. Rules wrapped over several lines (long sets) are joined until braces balance."""
    if not nft_ok or not which("nft"):
        return {}
    rc, out, _ = run(["nft", "list", "ruleset"])
    if rc != 0:
        return {}
    chains = {}
    cur = None
    fam = tab = None
    pending = ""
    for line in out.splitlines():
        if pending:
            pending += " " + line.strip()
            if pending.count("{") > pending.count("}"):
                continue
            cur["rules"].append(pending)
            pending = ""
            continue
        m = NFT_TABLE_RE.match(line)
        if m:
            fam, tab = m.group(1), m.group(2)
            cur = None
            continue
        m = NFT_CHAIN_RE.match(line)
        if m:
            cur = None
            if fam in ("ip", "ip6", "inet"):
                cur = chains.setdefault((fam, tab, m.group(1)), {"hook": None, "type": None, "policy": None, "rules": []})
            continue
        st = line.strip()
        if st == "}":
            cur = None
            continue
        if cur is None or not st:
            continue
        m = NFT_HOOK_RE.match(line)
        if m:
            cur["type"], cur["hook"] = m.group(1), m.group(2)
            pm = re.search(r"policy\s+(\w+)", line)
            cur["policy"] = pm.group(1) if pm else "accept"
            continue
        if st.startswith(("policy ", "comment ", "flags ", "devices ")):
            continue
        if st.count("{") > st.count("}"):
            pending = st
            continue
        cur["rules"].append(st)
    return chains


def _nft_ruleset(chains):
    """Hooked rules of the ip and inet families (hdrlength etc. are IPv4)."""
    def jump_of(t):
        m = NFT_JUMP_RE.match(NFT_COMMENT_RE.sub("", t))
        return m.group(1) if m else None
    return _hooked_rules("nft", chains, jump_of,
                         lambda t: re.search(r"\baccept\b", NFT_COMMENT_RE.sub("", t)) is not None)


def _iptables_backend(cli):
    """'nft' or 'legacy' for an iptables-save flavour, from `iptables --version` (no kernel access).
    iptables before 1.8 prints no backend: legacy."""
    if cli == "iptables-legacy-save":
        return "legacy"
    if cli == "iptables-nft-save":
        return "nft"
    rc, out, _ = run([which("iptables") or "iptables", "--version"]) if which("iptables") else (1, "", "")
    return "nft" if "nf_tables" in out else "legacy"


def _iptables_chains(nft_ok, legacy_ok, v):
    """Chains from iptables-save (v "") or ip6tables-save (v "6"), plus the legacy/nft variants
    when they show something else, keyed (cli, table, chain), with the built-in policy.
    nat table chains are not hooks here: they only see the first packet of a flow."""
    chains = {}
    seen = []
    for cli in ("ip%stables-save" % v, "ip%stables-legacy-save" % v, "ip%stables-nft-save" % v):
        if not which(cli):
            continue
        backend = _iptables_backend(cli.replace("ip6", "ip"))
        if (backend == "legacy" and not legacy_ok) or (backend == "nft" and not nft_ok):
            continue
        rc, out, _ = run([cli])
        # iptables-save and iptables-nft-save print the same ruleset under different headers
        # ... and with packet counters that move between the two calls on a busy host
        body = "\n".join(re.sub(r"\[\d+:\d+\]", "", l) for l in out.splitlines() if not l.startswith("#"))
        if rc != 0 or body in seen:
            continue
        seen.append(body)
        table = None
        for line in out.splitlines():
            if line.startswith("*"):
                table = line[1:].strip()
            elif line.startswith(":") and table:
                name = line[1:].split()[0]
                chains.setdefault((cli, table, name), {"hook": None if table == "nat" else IPT_BUILTIN_HOOK.get(name),
                                                       "type": "filter", "rules": []})["policy"] = line.split()[1].lower()
            elif line.startswith("-A ") and table:
                name = line.split()[1]
                chains.setdefault((cli, table, name), {"hook": None if table == "nat" else IPT_BUILTIN_HOOK.get(name),
                                                       "type": "filter", "rules": []})["rules"].append(line)
    return chains


def _iptables_ruleset(chains):
    def jump_of(t):
        m = IPT_JUMP_RE.match(IPT_COMMENT_RE.sub("", t))
        return m.group(1) if m else None
    return _hooked_rules("iptables", chains, jump_of,
                         lambda t: re.search(r"\s-j\s+ACCEPT\b", t) is not None)


# ----------------------------------------------------------------------------
# Reachability: can any source open a new TCP connection to a local port
# ----------------------------------------------------------------------------

def _default_ifaces(fam):
    """Interfaces carrying a default route: an accept limited to one of these is not a limit."""
    out = set()
    if fam == "ip":
        for line in (read_file("/proc/net/route", "") or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) > 7 and parts[1] == "00000000" and parts[7] == "00000000":
                out.add(parts[0])
    else:
        for line in (read_file("/proc/net/ipv6_route", "") or "").splitlines():
            parts = line.split()
            if len(parts) > 9 and parts[0] == "0" * 32 and parts[1] == "00" and parts[9] != "lo":
                out.add(parts[9])
    return out


def _port_in(spec, port):
    """True when a port list like "80,443,8000:8100" or "80-90" contains port."""
    names = {"http": 80, "https": 443, "ssh": 22}
    for item in re.split(r"[,\s]+", spec.strip("{} ")):
        if not item:
            continue
        m = re.match(r"^(\d+)[:-](\d+)$", item)
        if m:
            if int(m.group(1)) <= port <= int(m.group(2)):
                return True
        elif item.isdigit():
            if int(item) == port:
                return True
        elif names.get(item) == port:
            return True
        elif item not in names:
            return True          # named set or something else: cannot rule the port out
    return False


def _ipt_cond(text, port, pub):
    """One iptables rule seen by a new inbound TCP packet to port from a non-loopback
    interface: None when it cannot match, else {"src", "extra", "verdict", "target"}. src: the
    rule is limited to particular sources (or to an interface without a default route); extra:
    other conditions the probe does not evaluate."""
    try:
        tok = shlex.split(text)
    except ValueError:
        return {"src": False, "extra": True, "verdict": "accept", "target": None}
    r = {"src": False, "extra": False, "verdict": None, "target": None}
    i, neg = 2, False
    while i < len(tok):
        t = tok[i]
        val = tok[i + 1] if i + 1 < len(tok) else ""
        if t == "!":
            neg = True
            i += 1
            continue
        if t in ("-p", "--protocol"):
            is_tcp = val.lower() in ("tcp", "6", "all")
            if is_tcp == neg and val.lower() != "all":
                return None
            i += 1
        elif t in ("-m", "--match"):
            i += 1
        elif t == "--comment":
            i += 1
        elif t in ("-s", "--source"):
            if val not in ("0.0.0.0/0", "::/0"):
                if neg:
                    r["extra"] = True
                else:
                    r["src"] = True
            i += 1
        elif t == "--src-range":
            r["extra" if neg else "src"] = True
            i += 1
        elif t == "--match-set":
            flags = tok[i + 2] if i + 2 < len(tok) else ""
            r["src" if ("src" in flags.split(",") and not neg) else "extra"] = True
            i += 2
        elif t in ("-i", "--in-interface"):
            is_lo = val == "lo"
            if is_lo != neg and is_lo:
                return None
            if not is_lo and not neg:
                base = val.rstrip("+")
                if not any(p == val or (val.endswith("+") and p.startswith(base)) for p in pub):
                    r["src"] = True
            i += 1
        elif t in ("-o", "--out-interface"):
            return None
        elif t in ("--dport", "--dports", "--destination-port", "--destination-ports", "--ports"):
            if _port_in(val.replace(":", "-") if "," not in val else val, port) == neg:
                return None
            i += 1
        elif t in ("--sport", "--sports", "--source-port", "--source-ports"):
            i += 1
        elif t in ("--ctstate", "--state"):
            if ("NEW" in val.split(",")) == neg:
                return None
            i += 1
        elif t == "--dst-type":
            if ("LOCAL" in val.split(",")) == neg:
                return None
            i += 1
        elif t == "--tcp-flags":
            i += 2
        elif t in ("--syn",):
            pass
        elif t in ("--icmp-type", "--icmpv6-type", "-f"):
            return None
        elif t in ("-j", "--jump", "-g", "--goto"):
            tgt = val
            r["target"] = tgt
            r["verdict"] = {"ACCEPT": "accept", "DROP": "drop", "REJECT": "drop", "RETURN": "return"}.get(
                tgt, "goto" if t in ("-g", "--goto") else "jump")
            break
        elif t.startswith("-"):
            r["extra"] = True
        neg = False
        i += 1
    return r if r["verdict"] else None


NFT_VERDICT_RE = re.compile(r"\b(?:(jump|goto)\s+(\S+)|(accept|drop|return)|(reject)(?:\s+with\s+.*)?)\s*$")


def _nft_cond(text, port, fam, pub):
    """Same as _ipt_cond for one nft rule of an ip, ip6 or inet table."""
    t = NFT_COMMENT_RE.sub("", text)
    if "vmap" in t:
        if re.search(r"ct state vmap", t) and not re.search(r"\bnew\s*:", t):
            return None
        return {"src": False, "extra": True, "verdict": "accept", "target": None}
    m = NFT_VERDICT_RE.search(t)
    if not m:
        return None
    if m.group(1):
        verdict, target = m.group(1), m.group(2)
    else:
        verdict, target = ("drop" if m.group(4) else m.group(3)), None
    body = t[:m.start()]
    if re.search(r"\biif(?:name)?\s+\"?lo\"?(\s|$)", body):
        return None
    proto_rx = r"\b(meta l4proto|ip protocol|ip6 nexthdr)\s+(\{[^}]*\}|\S+)"
    if re.search(r"\b(udp|udplite|icmp|icmpv6|sctp|dccp|igmp)\s", re.sub(proto_rx, " ", body)) or \
            re.search(r"\b(meta l4proto|ip protocol|ip6 nexthdr)\s+(?!tcp\b|\{[^}]*\btcp\b)", body) or \
            re.search(r"\bpkttype\s+(broadcast|multicast)", body) or \
            re.search(r"\bfib daddr type\s+(?!local\b)", body):
        return None
    if fam == "ip6" and re.search(r"\bip (saddr|daddr|protocol)\b|meta nfproto ipv4", body):
        return None
    if fam == "ip" and re.search(r"\bip6 (saddr|daddr|nexthdr)\b|meta nfproto ipv6", body):
        return None
    cs = re.search(r"\bct state\s+(!=\s+)?(\{[^}]*\}|[a-z,]+)", body)
    if cs and (("new" in re.split(r"[,{}\s]+", cs.group(2))) == bool(cs.group(1))):
        return None
    dp = re.search(r"\b(?:tcp|th) dport\s+(!=\s+)?(\{[^}]*\}|\S+)", body)
    if dp and _port_in(dp.group(2), port) == bool(dp.group(1)):
        return None
    r = {"src": False, "extra": False, "verdict": verdict, "target": target}
    if re.search(r"\bip6? saddr\s+(?!!=)", body):
        r["src"] = True
    ifm = re.search(r"\biif(?:name)?\s+(!=\s+)?\"?([^\"\s]+)\"?", body)
    if ifm and not ifm.group(1) and ifm.group(2) not in pub:
        r["src"] = True
    rest = body
    for rx in (r"\bcounter(\s+packets\s+\d+\s+bytes\s+\d+)?", r"\b(?:tcp|th) dport\s+(!=\s+)?(\{[^}]*\}|\S+)",
               r"\bmeta l4proto\s+(\{[^}]*\}|\S+)", r"\bip protocol\s+\S+", r"\bip6 nexthdr\s+\S+",
               r"\bct state\s+(!=\s+)?(\{[^}]*\}|[a-z,]+)", r"\bip6? saddr\s+(\{[^}]*\}|\S+)",
               r"\biif(?:name)?\s+(!=\s+)?\"?[^\"\s]+\"?", r"\bfib daddr type\s+local", r"\bmeta nfproto\s+\S+",
               r"\btcp flags[^a-z]*(syn|ack|fin|rst)[a-z,/& |()]*", r"\blog(\s+prefix\s+\"[^\"]*\")?(\s+level\s+\S+)?"):
        rest = re.sub(rx, " ", rest)
    if rest.strip():
        r["extra"] = True
    return r


def _walk_base(chains, key, cond, tool):
    """Verdict of one base chain for the packet: ("open", rule text), ("restricted", count of
    limited accepts) or ("closed", 0)."""
    acc = {"open": None, "restricted": 0}

    def walk(k, src, extra, depth):
        """True when the packet's fate is settled for every source that entered this chain."""
        ch = chains.get(k)
        if ch is None or depth > 30:
            return False
        for text in ch["rules"]:
            c = cond(text)
            if not c:
                continue
            uncond = not c["src"] and not c["extra"]
            s2 = src or c["src"]
            if c["verdict"] == "accept":
                if s2:
                    acc["restricted"] += 1
                elif acc["open"] is None:
                    acc["open"] = "%s %s: %s" % (tool, "/".join(k[-2:]), text)
                if uncond:
                    return True
            elif c["verdict"] == "drop":
                if uncond:
                    return True
            elif c["verdict"] == "return":
                if uncond:
                    return False
            else:
                done = walk(k[:-1] + (c["target"],), s2, extra or c["extra"], depth + 1)
                if done and uncond:
                    return True
                if c["verdict"] == "goto" and uncond:
                    return False
        return False
    settled = walk(key, False, False, 0)
    if not settled and (chains[key].get("policy") or "accept") == "accept" and acc["open"] is None:
        acc["open"] = "%s %s: policy accept" % (tool, "/".join(key[-2:]))
    if acc["open"]:
        return ("open", acc["open"])
    if acc["restricted"]:
        return ("restricted", acc["restricted"])
    return ("closed", 0)


# ----------------------------------------------------------------------------
# PHP discovery (what is actually serving requests, on the host and in containers)
# ----------------------------------------------------------------------------

PHP_EXE_RE = re.compile(r"^(php-fpm[0-9.]*|php-cgi[0-9.]*|php[0-9.]*-cgi|frankenphp|lsphp[0-9.]*|litespeed|apache2|httpd)$")
SAPI_FOR_EXE = [
    (re.compile(r"^php-fpm"), "fpm-fcgi"),
    (re.compile(r"^(php-cgi|php[0-9.]*-cgi)"), "cgi-fcgi"),
    (re.compile(r"^frankenphp"), "frankenphp"),
    (re.compile(r"^(lsphp|litespeed)"), "litespeed"),
    (re.compile(r"^(apache2|httpd)"), "apache2handler"),
]
CGROUP_ID_RE = re.compile(r"([0-9a-f]{64})")
# LXC/Incus guests seen from the host: /lxc.payload.<name>/... (Incus, LXD), /lxc.monitor.<name>,
# classic /lxc/<name>/...; the guest runs its own probe, so its processes are skipped on the host
LXC_GUEST_RE = re.compile(r"^[^:\n]*:[^:\n]*:/lxc(?:\.payload|\.monitor)?[./]([^/\n]*)", re.M)
_LXC_GUESTS = None       # names of guests skipped this run; None inside a container (nothing skipped)
_CONTAINER_META = {}     # full container id -> (runtime, name, image) as the CLI reports it
_DEAD_CLI = set()        # (cli, endpoint) that timed out once: never called again this run
_PREFILLED = []          # non-empty once _prefill_container_meta ran
CRICTL_ENDPOINTS = (None, "unix:///run/containerd/containerd.sock", "unix:///run/k0s/containerd.sock")


def _cli_run(cli, args, endpoint=None, timeout=10):
    if (cli, endpoint) in _DEAD_CLI or not which(cli):
        return (-1, "", "unavailable")
    cmd = [cli] + (["--runtime-endpoint", endpoint] if endpoint else []) + args
    rc, out, err = run(cmd, timeout=timeout)
    if rc == -9:
        _DEAD_CLI.add((cli, endpoint))
        log("%s timed out, not calling it again" % " ".join(cmd[:3]))
    return rc, out, err


def _prefill_container_meta():
    """One `ps` per runtime fills the name cache up front, instead of one `inspect` per
    container; on a node with 150 containers and a hung daemon that is the difference
    between one timeout and 150."""
    if _PREFILLED:
        return
    _PREFILLED.append(True)
    for cli in ("docker", "podman"):
        rc, out, _ = _cli_run(cli, ["ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"])
        if rc != 0:
            continue
        for line in out.splitlines():
            parts = (line.split("\t") + ["", ""])[:3]
            if CGROUP_ID_RE.match(parts[0]) and parts[0] not in _CONTAINER_META:
                _CONTAINER_META[parts[0]] = (cli, parts[1].lstrip("/"), parts[2])
    if which("crictl"):
        for ep in CRICTL_ENDPOINTS:
            rc, out, _ = _cli_run("crictl", ["ps", "-o", "json"], endpoint=ep)
            if rc != 0:
                continue
            try:
                conts = json.loads(out).get("containers", [])
            except ValueError:
                continue
            if not conts:
                continue   # an endpoint that answers but hosts nothing is not the one we want
            for c in conts:
                labels = c.get("labels", {})
                name = "%s/%s/%s" % (labels.get("io.kubernetes.pod.namespace", "?"),
                                     labels.get("io.kubernetes.pod.name", "?"),
                                     c.get("metadata", {}).get("name") or labels.get("io.kubernetes.container.name", "?"))
                _CONTAINER_META.setdefault(c.get("id", ""), ("containerd", name, c.get("image", {}).get("image")))
            break


def describe_container(pid, cid):
    """(runtime, name, image) for a container id. Runtime comes from the cgroup path, the
    name from the runtime CLI when one answers, else from the container's own HOSTNAME.
    No CLI is ever required."""
    _prefill_container_meta()
    cg = read_file("/proc/%d/cgroup" % pid, "") or ""
    if "libpod-" in cg:
        runtime = "podman"
    elif "cri-containerd" in cg or "kubepods" in cg:
        runtime = "containerd"
    elif "docker" in cg:
        runtime = "docker"
    else:
        runtime = "unknown"
    if cid not in _CONTAINER_META and runtime in ("docker", "podman", "unknown"):
        for cli in ("docker", "podman"):
            rc, out, _ = _cli_run(cli, ["inspect", "--format", "{{.Name}}\t{{.Config.Image}}", cid])
            if rc == 0 and out.strip():
                name, image = (out.strip().split("\t") + [""])[:2]
                _CONTAINER_META[cid] = (cli, name.lstrip("/"), image)
                break
    if cid not in _CONTAINER_META:
        # No CLI available: the container's own hostname (pod name on k8s, short id on docker).
        m = re.search(r"(?:^|\0)HOSTNAME=([^\0]+)", read_file("/proc/%d/environ" % pid, "") or "")
        _CONTAINER_META[cid] = (runtime, m.group(1) if m else cid[:12], None)
    cli_runtime, name, image = _CONTAINER_META[cid]
    return (runtime if runtime != "unknown" else cli_runtime, name, image)


def _clk_tck():
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        return 100


def _btime():
    for line in (read_file("/proc/stat", "") or "").splitlines():
        if line.startswith("btime "):
            return int(line.split()[1])
    return None


def where_label(container_id, runtime, name):
    return "host" if not container_id else "%s:%s" % (runtime, name)


def process_times(pid, root, exe_path):
    """(process start time as epoch, mtime of the binary on disk); None where unreadable."""
    start = mtime = None
    try:
        stat = read_file("/proc/%d/stat" % pid, "")
        rest = stat[stat.rindex(")") + 2:].split()
        bt = _btime()
        if bt:
            start = bt + int(rest[19]) / float(_clk_tck())
    except (ValueError, IndexError, AttributeError):
        pass
    try:
        mtime = os.stat(os.path.join(root, exe_path.lstrip("/"))).st_mtime
    except OSError:
        pass
    return start, mtime


def is_stale(deleted, start_time, exe_mtime):
    """True when the binary on disk is newer than the running process (restart needed)."""
    if deleted:
        return True
    if start_time and exe_mtime:
        return exe_mtime > start_time + 1
    return False


def lxc_guest(cgroup):
    """Name of the LXC/Incus guest owning a /proc/PID/cgroup text, or None. Only on the host:
    inside a guest without a cgroup namespace its own paths carry the same prefix."""
    if _LXC_GUESTS is None:
        return None
    m = LXC_GUEST_RE.search(cgroup)
    if not m:
        return None
    _LXC_GUESTS.add(m.group(1))
    return m.group(1)


def group_processes(classify):
    """One /proc walk. classify(exe basename) returns a tag or None; processes with a tag are
    grouped by (container id, exe) -> (tag, sorted pids). The container id is the 64-hex id in
    /proc/PID/cgroup; None on the host and inside an LXC minion, where everything is "host"."""
    groups = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        if pid == os.getpid():
            continue
        try:
            exe = os.readlink("/proc/%d/exe" % pid)
        except OSError:
            continue
        tag = classify(os.path.basename(exe.replace(" (deleted)", "")))
        if tag is None:
            continue
        cg = read_file("/proc/%d/cgroup" % pid, "") or ""
        if lxc_guest(cg):
            continue
        m = CGROUP_ID_RE.search(cg)
        key = (m.group(1) if m else None, exe)
        groups.setdefault(key, (tag, []))[1].append(pid)
    for tag, pids in groups.values():
        pids.sort()
    return groups


def exec_in_root(pid, container_id, argv, errors=None):
    """Run argv inside the mount/uts/pid namespaces of pid when it is a container process,
    plainly otherwise. Returns (rc, stdout, stderr); never raises."""
    if container_id:
        if not which("nsenter"):
            if errors is not None:
                errors.append("nsenter not available, cannot inspect container")
            return (-1, "", "no nsenter")
        return run(["nsenter", "-t", str(pid), "-m", "-u", "-p", "--"] + argv, timeout=CMD_TIMEOUT)
    return run(argv, timeout=CMD_TIMEOUT)


class PhpInstance(object):
    """A group of processes sharing one executable inside one root (host or container)."""

    def __init__(self, pid, exe, container_id, host):
        self.pid = pid                    # representative (lowest) pid
        self.pids = [pid]
        self.exe = exe
        self.deleted = exe.endswith(" (deleted)")
        self.exe_path = exe.replace(" (deleted)", "")
        self.container_id = container_id  # None on host
        self.root = "/proc/%d/root" % pid
        self.host = host
        self.sapi = None
        for rx, sapi in SAPI_FOR_EXE:
            if rx.match(os.path.basename(self.exe_path)):
                self.sapi = sapi
        self.runtime = None
        self.container_name = None
        self.image = None
        self.os = parse_os_release(read_file(os.path.join(self.root, "etc/os-release"), ""))
        self.version = None               # upstream PHP version, e.g. 8.4.27
        self.version_full = None          # as printed by php -v
        self.branch = None                # 8.4
        self.built = None
        self.ini = {}
        self.package = None               # (name, version, origin)
        self.changelog = None
        self.source = None                # sury | distro | alpine | upstream-build | unknown
        self.start_time = None
        self.exe_mtime = None
        self.errors = []

    # --- collection ---------------------------------------------------------

    def collect(self):
        self._times()
        self._container_meta()
        self._package()
        self._version_and_ini()
        self._classify()

    def _times(self):
        self.start_time, self.exe_mtime = process_times(self.pid, self.root, self.exe_path)

    def _container_meta(self):
        if not self.container_id:
            return
        self.runtime, self.container_name, self.image = describe_container(self.pid, self.container_id)

    def _package(self):
        base = os.path.basename(self.exe_path)
        fam = Host._family(self.os.get("ID", ""), self.os.get("ID_LIKE", ""))
        if fam == "deb":
            status = read_file(os.path.join(self.root, "var/lib/dpkg/status"))
            if not status:
                return
            cands = []
            m = re.match(r"php-fpm(\d+\.\d+)$", base)
            if m:
                cands = ["php%s-fpm" % m.group(1), "php%s-common" % m.group(1)]
            m = re.match(r"php-cgi(\d+\.\d+)$", base) or re.match(r"php(\d+\.\d+)-cgi$", base)
            if m:
                cands = ["php%s-cgi" % m.group(1), "php%s-common" % m.group(1)]
            if base in ("apache2", "httpd"):
                lib = self._mod_php_lib()
                if lib:
                    m = re.search(r"libphp(\d+\.\d+)", lib)
                    if m:
                        cands = ["libapache2-mod-php%s" % m.group(1), "php%s-common" % m.group(1)]
            for name in cands:
                ver = self._dpkg_version(status, name)
                if ver:
                    common = re.sub(r"^(php\d+\.\d+)-.*$", r"\1-common", name) if name.startswith("php") else name
                    for doc in (common, name):
                        cl = read_gz(in_root(self.root, "/usr/share/doc/%s/changelog.Debian.gz" % doc))
                        if cl:
                            self.changelog = cl
                            break
                    # Ubuntu builds: 8.4.27-1+ubuntu24.04.1+deb.sury.org+1; Debian builds: 8.4.27-1+0~20261021.134+debian13~1.gbp...
                    sury = ("deb.sury.org" in ver or re.search(r"\+0~\d{8}\.\d+\+(debian|ubuntu)", ver) is not None
                            or "@sury.org" in (self.changelog or "")[:3000])
                    self.package = (name, ver, "sury" if sury else "distro")
                    return
        elif fam == "apk":
            m = re.match(r"php-fpm(\d+)$", base)
            wanted = ["php%s-fpm" % m.group(1), "php%s" % m.group(1)] if m else ["php-fpm", "php"]
            found = apk_version(read_file(os.path.join(self.root, "lib/apk/db/installed")), wanted)
            if found:
                self.package = (found[0], found[1], "alpine")

    @staticmethod
    def _dpkg_version(status, name):
        m = re.search(r"^Package: %s\n(?:(?!\n\n).)*?^Version: (\S+)" % re.escape(name), status, re.M | re.S)
        if not m:
            return None
        blk = status[m.start():m.end()]
        if re.search(r"^Status: .*installed", blk, re.M):
            return m.group(1)
        return None

    def _mod_php_lib(self):
        maps = read_file("/proc/%d/maps" % self.pid, "") or ""
        m = re.search(r"\S*libphp\S*\.so", maps)
        return m.group(0) if m else None

    def _exec_in_root(self, argv):
        return exec_in_root(self.pid, self.container_id, argv, self.errors)

    def _version_and_ini(self):
        if self.sapi == "apache2handler":
            lib = self._mod_php_lib()
            m = re.search(r"libphp(\d+\.\d+)", lib or "")
            if m:
                self.branch = m.group(1)
                self.version = (self.package[1].split("-")[0].split(":")[-1] if self.package else None)
                self._ini_from_files("/etc/php/%s/apache2" % self.branch)
            else:
                self.errors.append("apache without mod_php mapping, skipped")
            return
        exe = self.exe_path
        rc, out, err = self._exec_in_root([exe, "-v"])
        m = re.search(r"PHP (\d+\.\d+\.\d+)(\S*)", out + err)
        if m:
            self.version = m.group(1)       # upstream part only; sury prints 7.4.33-31+ubuntu... here
            self.version_full = m.group(1) + m.group(2)
            self.branch = ".".join(self.version.split(".")[:2])
            self.built = parse_build_date(out)
        else:
            self.errors.append("php -v failed: rc=%s %s" % (rc, (err or out).strip()[:200]))
            return
        rc, out, err = self._exec_in_root([exe, "-i"])
        for line in out.splitlines():
            m = re.match(r"^([a-zA-Z0-9_.]+) => (.*?)(?: => (.*))?$", line)
            if m and m.group(1) in ("memory_limit", "session.upload_progress.enabled", "fatal_error_backtraces",
                                    "Loaded Configuration File", "Server API"):
                # local value => master value; the first is what applies
                self.ini[m.group(1)] = m.group(2).strip()
        if not self.ini and rc != 0:
            self.errors.append("php -i failed: rc=%s %s" % (rc, (err or out).strip()[:200]))

    def _ini_from_files(self, confdir):
        files = [os.path.join(confdir, "php.ini")] + sorted(glob.glob(os.path.join(confdir, "conf.d", "*.ini")))
        for f in files:
            for line in (read_file(in_root(self.root, f), "") or "").splitlines():
                m = re.match(r"^\s*(memory_limit|session\.upload_progress\.enabled|fatal_error_backtraces)\s*=\s*(.*?)\s*(;.*)?$", line)
                if m:
                    self.ini[m.group(1)] = m.group(2).strip().strip('"')
        self.ini.setdefault("memory_limit", "128M")
        self.ini.setdefault("session.upload_progress.enabled", "1")

    def _classify(self):
        if self.package:
            self.source = self.package[2]
        elif self.exe_path.startswith("/usr/local/"):
            self.source = "upstream-build"
        else:
            self.source = "unknown"

    # --- derived -------------------------------------------------------------

    def stale(self):
        return is_stale(self.deleted, self.start_time, self.exe_mtime)

    def label(self):
        return "%s %s (%s)" % (os.path.basename(self.exe_path), self.version or "?",
                               where_label(self.container_id, self.runtime, self.container_name))

    def as_dict(self):
        return {"pid": self.pid, "workers": len(self.pids), "exe": self.exe_path, "sapi": self.sapi,
                "container_id": self.container_id, "runtime": self.runtime, "container": self.container_name,
                "image": self.image, "os": "%s %s" % (self.os.get("ID", "?"), self.os.get("VERSION_ID", "")),
                "version": self.version, "version_full": self.version_full, "branch": self.branch,
                "built": str(self.built) if self.built else None,
                "package": self.package, "source": self.source, "ini": self.ini, "stale": self.stale(),
                "errors": self.errors}


def discover_php(host):
    instances = []
    for (cid, exe), (tag, pids) in group_processes(lambda b: True if PHP_EXE_RE.match(b) else None).items():
        inst = PhpInstance(pids[0], exe, cid, host)
        inst.pids = list(pids)
        if inst.sapi == "apache2handler" and not inst._mod_php_lib():
            continue  # apache without mod_php is not a PHP runtime
        log("php instance pid=%d exe=%s container=%s" % (inst.pid, inst.exe, inst.container_id))
        inst.collect()
        instances.append(inst)
    return sorted(instances, key=lambda i: (i.container_id or "", i.exe))


# ----------------------------------------------------------------------------
# Trust stores (the host and every container root), for CA compromise rules
# ----------------------------------------------------------------------------

TRUST_BUNDLES = [
    "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu, Alpine
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # RHEL family
    "/etc/ssl/ca-bundle.pem",                             # SUSE
    "/etc/ssl/cert.pem",                                  # symlink on Alpine/RHEL, real file elsewhere
]
PEM_CERT_RE = re.compile(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", re.S)


def pem_fingerprints(text):
    """SHA-256 fingerprints (upper-case hex, no colons) of every certificate in a PEM bundle."""
    fps = []
    for m in PEM_CERT_RE.finditer(text or ""):
        try:
            der = base64.b64decode("".join(m.group(1).split()))
        except (binascii.Error, ValueError):
            continue
        fps.append(hashlib.sha256(der).hexdigest().upper())
    return fps


class TrustStore(object):
    """The CA bundle of one root: the host, or a container seen through /proc/PID/root."""

    def __init__(self, root, container_id=None, pid=None):
        self.root = root
        self.container_id = container_id
        self.pid = pid
        self.runtime = None
        self.container_name = None
        self.image = None
        self.os = parse_os_release(read_file(os.path.join(root, "etc/os-release"), ""))
        self.bundle = None
        self.fingerprints = []
        self.package = None
        self.disabled = []   # Debian/Ubuntu: entries prefixed with "!" in /etc/ca-certificates.conf

    def collect(self):
        if self.container_id:
            self.runtime, self.container_name, self.image = describe_container(self.pid, self.container_id)
        for p in TRUST_BUNDLES:
            full = in_root(self.root, p)
            if os.path.isfile(full):
                fps = pem_fingerprints(read_file(full, ""))
                if fps:
                    self.bundle, self.fingerprints = p, fps
                    break
        conf = read_file(os.path.join(self.root, "etc/ca-certificates.conf"), "") or ""
        self.disabled = [l[1:].strip() for l in conf.splitlines() if l.startswith("!")]
        fam = Host._family(self.os.get("ID", ""), self.os.get("ID_LIKE", ""))
        found = _package_in_root(self.root, fam, {"deb": ["ca-certificates"], "apk": ["ca-certificates-bundle", "ca-certificates"],
                                                  "rpm": ["ca-certificates"]}.get(fam), self.container_id)
        if found:
            self.package = found[1]

    def label(self):
        return where_label(self.container_id, self.runtime, self.container_name)

    def as_dict(self):
        return {"where": self.label(), "container_id": self.container_id, "runtime": self.runtime,
                "container": self.container_name, "image": self.image,
                "os": "%s %s" % (self.os.get("ID", "?"), self.os.get("VERSION_ID", "")),
                "bundle": self.bundle, "certificates": len(self.fingerprints), "package": self.package,
                "disabled": self.disabled}


def discover_containers():
    """Candidate pids (lowest first, at most three) per container id seen in /proc/PID/cgroup.
    Pids in the probe's own mount namespace are skipped: conmon, shims or the probe's own
    ancestors can carry a container id in their cgroup while seeing the host filesystem."""
    try:
        own_mnt = os.readlink("/proc/self/ns/mnt")
    except OSError:
        own_mnt = None
    cands = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        cg = read_file("/proc/%d/cgroup" % pid, "") or ""
        if lxc_guest(cg):
            continue
        m = CGROUP_ID_RE.search(cg)
        if not m:
            continue
        try:
            if own_mnt and os.readlink("/proc/%d/ns/mnt" % pid) == own_mnt:
                continue
        except OSError:
            continue
        lst = cands.setdefault(m.group(1), [])
        if len(lst) < 3 or pid < lst[-1]:
            lst.append(pid)
            lst.sort()
            del lst[3:]
    return cands


_CONTAINER_ROOTS = None


def container_roots():
    """[(container id, pid)] with a readable /proc/PID/root/etc, one per container, cached."""
    global _CONTAINER_ROOTS
    if _CONTAINER_ROOTS is None:
        _CONTAINER_ROOTS = []
        for cid, pids in sorted(discover_containers().items(), key=lambda kv: kv[1][0]):
            for pid in pids:
                if os.path.isdir("/proc/%d/root/etc" % pid):
                    _CONTAINER_ROOTS.append((cid, pid))
                    break
            else:
                log("container %s: no readable root among pids %s, skipped" % (cid[:12], pids))
    return _CONTAINER_ROOTS


def discover_trust_stores():
    stores = [TrustStore("/")]
    for cid, pid in container_roots():
        stores.append(TrustStore("/proc/%d/root" % pid, cid, pid))
    out = []
    for st in stores:
        st.collect()
        if st.bundle is None and st.container_id:
            log("trust store %s: no CA bundle (pause or distroless image), skipped" % st.container_id[:12])
            continue
        log("trust store %s: %s certs=%d pkg=%s" % (st.label(), st.bundle, len(st.fingerprints), st.package))
        out.append(st)
    return out


# ----------------------------------------------------------------------------
# Runtime binaries (kind: runtime): processes whose executable vendors a vulnerable library
# (Node.js, Bun) plus the system copy of that library in every root
# ----------------------------------------------------------------------------

def listening_sockets(pids):
    """Listening sockets held by any of these processes: TCP ports as "3000", Unix sockets as
    "unix:/path". Each distinct network namespace among the pids is read once; socket inodes
    from /proc/PID/fd are matched against the namespace tables."""
    inodes = set()
    ns_pid = {}
    for pid in pids:
        try:
            fds = os.listdir("/proc/%d/fd" % pid)
        except OSError:
            continue
        for fd in fds:
            try:
                l = os.readlink("/proc/%d/fd/%s" % (pid, fd))
            except OSError:
                continue
            if l.startswith("socket:["):
                inodes.add(l[8:-1])
        try:
            ns_pid.setdefault(os.readlink("/proc/%d/ns/net" % pid), pid)
        except OSError:
            pass
    out = set()
    for pid in ns_pid.values():
        for f in ("tcp", "tcp6"):
            for line in (read_file("/proc/%d/net/%s" % (pid, f), "") or "").splitlines()[1:]:
                parts = line.split()
                if len(parts) > 9 and parts[3] == "0A" and parts[9] in inodes:
                    out.add(str(int(parts[1].rsplit(":", 1)[1], 16)))
        for line in (read_file("/proc/%d/net/unix" % pid, "") or "").splitlines()[1:]:
            parts = line.split()
            # Num RefCount Protocol Flags Type St Inode Path; Flags 00010000 = ACC (listening)
            if len(parts) >= 7 and parts[3] == "00010000" and parts[6] in inodes:
                out.add("unix:" + (parts[7] if len(parts) > 7 else "?"))
    return sorted(out, key=lambda x: (x.startswith("unix:"), x))


def listening_endpoints(pids):
    """TCP listening sockets of these processes as (family, kind, port): family "ip"/"ip6",
    kind "any", "loopback" or "addr". An IPv6 wildcard socket also counts for IPv4."""
    inodes = set()
    ns_pid = {}
    for pid in pids:
        try:
            for fd in os.listdir("/proc/%d/fd" % pid):
                try:
                    l = os.readlink("/proc/%d/fd/%s" % (pid, fd))
                except OSError:
                    continue
                if l.startswith("socket:["):
                    inodes.add(l[8:-1])
            ns_pid.setdefault(os.readlink("/proc/%d/ns/net" % pid), pid)
        except OSError:
            continue
    out = set()
    for pid in ns_pid.values():
        for f in ("tcp", "tcp6"):
            for line in (read_file("/proc/%d/net/%s" % (pid, f), "") or "").splitlines()[1:]:
                parts = line.split()
                if len(parts) <= 9 or parts[3] != "0A" or parts[9] not in inodes:
                    continue
                addr, port = parts[1].rsplit(":", 1)
                port = int(port, 16)
                b = []
                for w in range(0, len(addr), 8):
                    b.extend(int(addr[w + j:w + j + 2], 16) for j in (6, 4, 2, 0))
                if len(b) == 16 and b[:10] == [0] * 10 and b[10:12] == [255, 255]:
                    b = b[12:]
                fam = "ip" if len(b) == 4 else "ip6"
                if not any(b):
                    out.add((fam, "any", port))
                    if fam == "ip6":
                        out.add(("ip", "any", port))
                elif (fam == "ip" and b[0] == 127) or (fam == "ip6" and b == [0] * 15 + [1]):
                    out.add((fam, "loopback", port))
                else:
                    out.add((fam, "addr", port))
    return sorted(out)


def _netns_local_ips(pid):
    """IPv4 addresses local to the network namespace of pid, from its fib_trie."""
    ips, prev = set(), None
    for line in (read_file("/proc/%d/net/fib_trie" % pid, "") or "").splitlines():
        m = re.search(r"\|--\s+(\d+\.\d+\.\d+\.\d+)", line)
        if m:
            prev = m.group(1)
        elif "/32 host LOCAL" in line and prev and not prev.startswith("127."):
            ips.add(prev)
    return ips


def netns_reachability(pid, runtime, kf):
    """("open"|"restricted", text) for a container in its own network namespace: open when a
    DNAT rule or a docker-proxy on the host forwards to one of its addresses, or when the
    runtime is not Docker/podman (cannot be proven); restricted when it publishes nothing."""
    if kf._publish_texts is None:
        ch = kf.fw_chains()
        texts = [t for c in list(ch["ip"].values()) + list(ch["nft"].values()) for t in c["rules"]]
        for d in os.listdir("/proc"):
            if d.isdigit() and (read_file("/proc/%s/comm" % d, "") or "").strip() == "docker-proxy":
                texts.append((read_file("/proc/%s/cmdline" % d, "") or "").replace("\0", " "))
        kf._publish_texts = [t for t in texts if re.search(r"--to-destination|dnat (ip )?to|-container-ip", t)]
    for ip in sorted(_netns_local_ips(pid)):
        rx = re.compile(r"(--to-destination|dnat (ip )?to|-container-ip)\s+%s(:|\s|$)" % re.escape(ip))
        if any(rx.search(t) for t in kf._publish_texts):
            return "open", "container address %s is published (DNAT/proxy rule on the host), sources not evaluated" % ip
    if runtime in ("docker", "podman"):
        return "restricted", "container publishes no port, reachable only from the host and its container networks"
    return "open", "container reachability cannot be proven for runtime %s" % (runtime or "unknown")


def instance_reachability(inst, kf, ports=None):
    """("open"|"restricted", text) for a runtime instance's TCP listeners. Host network
    namespace: judged from the input hook rules per port. Other namespaces: open when a DNAT
    rule or a docker-proxy forwards to the container, or when the runtime is not Docker/podman
    (cannot be proven); restricted when a Docker/podman container publishes nothing."""
    eps = [e for e in inst.endpoints if not ports or e[2] in ports] or inst.endpoints
    if not eps:
        return "open", "listening sockets not readable"
    if all(e[1] == "loopback" for e in eps):
        return "restricted", "listens on loopback only"
    try:
        own_ns = os.readlink("/proc/self/ns/net") == os.readlink("/proc/%d/ns/net" % inst.pid)
    except OSError:
        own_ns = not inst.container_id
    if not own_ns:
        return netns_reachability(inst.pid, inst.runtime, kf)
    v6_global = any(len(l.split()) > 5 and l.split()[3] == "00" and l.split()[5] != "lo"
                    for l in (read_file("/proc/net/if_inet6", "") or "").splitlines())
    checked, limited = [], []
    for fam, port in sorted(set((e[0], e[2]) for e in eps if e[1] != "loopback")):
        if fam == "ip6" and not v6_global:
            continue
        state, detail = kf.port_reachability(fam, port)
        if state == "open":
            return "open", "port %d%s open to any source (%s)" % (port, "/ipv6" if fam == "ip6" else "", detail)
        checked.append(str(port))
        if state == "restricted":
            limited.append("%d: %d limited accept rule(s)" % (port, detail))
    if not checked:
        return "restricted", "no non-loopback listener on a routable address family"
    return "restricted", "firewall accepts port(s) %s only from particular sources or interfaces (%s)" % (
        ",".join(sorted(set(checked), key=int)), "; ".join(limited) or "no accept rule at all")


def read_config_tree(root, path, include_re=None, limit=500):
    """Text of a configuration file inside a root with include directives followed (globs, paths
    relative to the main file's directory), comments stripped. include_re captures the pattern
    list in group 1; the default is nginx's `include pattern;`. None if unreadable."""
    seen, out = set(), []
    base = os.path.dirname(path)

    def rd(p, depth):
        full = in_root(root, p)
        if depth > 8 or len(seen) >= limit or full in seen:
            return
        seen.add(full)
        text = read_file(full)
        if text is None:
            return
        text = re.sub(r"(?m)(^|\s)#[^\n]*", r"\1", text)
        out.append(text)
        for m in re.finditer(include_re or r"(?:^|[;{}])\s*include\s+([^;]+);", text, re.M):
            for pat in m.group(1).split():
                pat = pat.strip("\"'")
                if not pat.startswith("/"):
                    pat = os.path.join(base, pat)
                g = os.path.join(root, pat.lstrip("/"))
                for hit in (sorted(glob.glob(g)) if re.search(r"[*?\[]", pat) else [g]):
                    rd("/" + os.path.relpath(hit, root), depth + 1)
    rd(path, 0)
    return "\n".join(out) if out else None


def _package_in_root(root, fam, names, container_id):
    """(name, version) of the first installed package among names inside a root: dpkg status
    (or distroless status.d), apk db, or rpm on the host. None when none is installed or the
    database cannot be read (rpm-based containers)."""
    if not names:
        return None
    if isinstance(names, str):
        names = [names]
    status = db = None
    if fam == "deb":
        status = read_file(os.path.join(root, "var/lib/dpkg/status"))
    elif fam == "apk":
        db = read_file(os.path.join(root, "lib/apk/db/installed"))
    for name in names:
        ver = None
        if fam == "deb":
            if status:
                ver = PhpInstance._dpkg_version(status, name)
            else:
                m = re.search(r"^Version: (\S+)", read_file(os.path.join(root, "var/lib/dpkg/status.d", name), "") or "", re.M)
                ver = m.group(1) if m else None
        elif fam == "apk":
            found = apk_version(db, [name])
            ver = found[1] if found else None
        elif fam == "rpm" and container_id is None:
            rc, out, _ = run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}\n", name], timeout=10)
            ver = out.strip().split("\n")[0] if rc == 0 and out.strip() else None   # first arch on multilib
        if ver:
            return (name, ver)
    return None


class RuntimeInstance(object):
    """A group of processes sharing one runtime executable inside one root."""

    def __init__(self, name, spec, pid, exe, container_id):
        self.name = name                  # runtime key from the rule, e.g. "node"
        self.spec = spec
        self.pid = pid
        self.pids = [pid]
        self.exe = exe
        self.deleted = exe.endswith(" (deleted)")
        self.exe_path = exe.replace(" (deleted)", "")
        self.container_id = container_id
        self.root = "/proc/%d/root" % pid
        self.runtime = None
        self.container_name = None
        self.image = None
        self.os = parse_os_release(read_file(os.path.join(self.root, "etc/os-release"), ""))
        self.version = None               # of the binary on disk (what a restart would run)
        self.package = None               # (name, version) when the binary is a distro package
        self.listening = []
        self.endpoints = []               # (family, kind, port) of TCP listeners
        self._config = False              # config dump: False = not read yet, None = unreadable
        self._variant = False
        self.variant_version = None
        self.banner = ""                  # raw output of the version command
        self._maps = None
        self.start_time = None
        self.exe_mtime = None
        self.errors = []

    def config(self):
        """The runtime's configuration as text: the main file (the path after spec config_arg on
        a process command line, else the first existing of spec config_files) with its include
        directives followed, read from the instance's root, comments removed. Nothing is
        executed. It is the configuration on disk. None when no file can be read."""
        if self._config is False:
            self._config = None
            path = None
            arg = self.spec.get("config_arg")
            if arg:
                for pid in self.pids:
                    m = re.search(r"\s%s\s*(/\S+)" % re.escape(arg), (read_file("/proc/%d/cmdline" % pid, "") or "").replace("\0", " "))
                    if m:
                        path = m.group(1).rstrip(";")
                        break
            for cand in ([path] if path else []) + list(self.spec.get("config_files", [])):
                text = read_config_tree(self.root, cand, self.spec.get("config_include_re"))
                if text:
                    self._config = text
                    break
            else:
                self.errors.append("no readable configuration file (%s)" % ", ".join(([path] if path else []) + list(self.spec.get("config_files", []))))
        return self._config

    def variant(self):
        """The first of the spec's variants this instance is, else None: recognised by a marker
        file in the root or by a regex over the binary's version banner. A variant is the
        runtime shipped inside a product with its own lifecycle (ingress-nginx, OpenResty): it
        carries a label and a remedy, and optionally its own name, version_re (the product's
        full version, kept in variant_version) and fixed table."""
        if self._variant is False:
            self._variant = None
            for v in self.spec.get("variants", []):
                if (v.get("file") and os.path.exists(in_root(self.root, v["file"]))) or \
                        (v.get("banner") and re.search(v["banner"], self.banner)):
                    self._variant = v
                    m = re.search(v["version_re"], self.banner) if v.get("version_re") else None
                    self.variant_version = m.group(1) if m else None
                    break
        return self._variant

    def display(self):
        """(name, version) as shown to people: the variant's own where it has them."""
        v = self.variant()
        if v and v.get("name") and self.variant_version:
            return v["name"], self.variant_version
        return self.name, self.version or "?"

    def collect(self):
        if self.container_id:
            self.runtime, self.container_name, self.image = describe_container(self.pid, self.container_id)
        self.start_time, self.exe_mtime = process_times(self.pid, self.root, self.exe_path)
        arg = self.spec.get("version_arg", "--version")
        rc, out, err = exec_in_root(self.pid, self.container_id, [self.exe_path, arg], self.errors)
        self.banner = ((out or "") + "\n" + (err or ""))[:600]
        m = re.search(self.spec.get("version_re", r"(\d+\.\d+\.\d+)"), self.banner)
        if m:
            self.version = m.group(1)
        else:
            self.errors.append("%s %s: rc=%s %s" % (self.exe_path, arg, rc, (err or out or "").strip()[:120]))
        fam = Host._family(self.os.get("ID", ""), self.os.get("ID_LIKE", ""))
        if self.exe_path.startswith(("/usr/bin/", "/usr/sbin/", "/usr/lib/", "/usr/libexec/", "/bin/", "/sbin/")):
            self.package = _package_in_root(self.root, fam, self.spec.get("packages", {}).get(fam), self.container_id)
        self.listening = listening_sockets(self.pids)
        self.endpoints = listening_endpoints(self.pids)

    def maps(self):
        """/proc/PID/maps of the first process: which shared objects it really runs with."""
        if self._maps is None:
            self._maps = read_file("/proc/%d/maps" % self.pid, "") or ""
        return self._maps

    def links_system_lib(self, soname):
        """True when the running process has the shared library mapped (distro builds, as opposed
        to upstream binaries that vendor a static copy)."""
        maps = read_file("/proc/%d/maps" % self.pid, "") or ""
        return bool(soname) and re.search(r"/%s(\.|\s|$)" % re.escape(soname), maps) is not None

    def stale(self):
        return is_stale(self.deleted, self.start_time, self.exe_mtime)

    def label(self):
        return "%s %s (%s)" % (self.display() + (where_label(self.container_id, self.runtime, self.container_name),))

    def as_dict(self):
        return {"runtime": self.name, "exe": self.exe, "version": self.version, "pids": sorted(self.pids),
                "where": where_label(self.container_id, self.runtime, self.container_name),
                "container_id": self.container_id, "container": self.container_name,
                "image": self.image, "os": "%s %s" % (self.os.get("ID", "?"), self.os.get("VERSION_ID", "")),
                "package": self.package, "listening": self.listening, "stale": self.stale(), "errors": self.errors}


class SystemLibrary(object):
    """One root's installed copy of a library package (host, or a container via /proc/PID/root)."""

    def __init__(self, root, container_id=None, pid=None):
        self.root = root
        self.container_id = container_id
        self.pid = pid
        self.runtime = None
        self.container_name = None
        self.image = None
        self.os = parse_os_release(read_file(os.path.join(root, "etc/os-release"), ""))
        self.family = Host._family(self.os.get("ID", ""), self.os.get("ID_LIKE", ""))
        self.name = None
        self.version = None
        self.present = False

    def collect(self, lib):
        if self.container_id:
            self.runtime, self.container_name, self.image = describe_container(self.pid, self.container_id)
        names = lib.get("packages", {}).get(self.family)
        found = _package_in_root(self.root, self.family, names, self.container_id)
        soname = lib.get("soname")
        if found:
            self.name, self.version = found
            self.present = True
        elif soname:
            self.name = names[0] if isinstance(names, list) else names
            self.present = bool(glob.glob(os.path.join(self.root, "usr/lib*", soname + "*")) or
                                glob.glob(os.path.join(self.root, "usr/lib/*", soname + "*")) or
                                glob.glob(os.path.join(self.root, "lib*", soname + "*")))

    def label(self):
        return where_label(self.container_id, self.runtime, self.container_name)

    def as_dict(self):
        return {"where": self.label(), "container_id": self.container_id, "container": self.container_name,
                "image": self.image, "os": "%s %s" % (self.os.get("ID", "?"), self.os.get("VERSION_ID", "")),
                "package": self.name, "version": self.version, "present": self.present}


def discover_runtimes(rules):
    """Processes matching any runtime of the given rules, grouped by (container, exe). The
    exec details (version_arg, version_re) come from the first rule naming the runtime; the
    verdict tables are taken per rule at evaluation time."""
    specs = {}
    for r in rules:
        for name, spec in r.get("runtimes", {}).items():
            specs.setdefault(name, (re.compile(spec["exe"]), spec))
    if not specs:
        return []

    def classify(base):
        for n, (rx, spec) in specs.items():
            if rx.match(base):
                return n
        return None
    out = []
    for (cid, exe), (name, pids) in group_processes(classify).items():
        inst = RuntimeInstance(name, specs[name][1], pids[0], exe, cid)
        inst.pids = list(pids)
        inst.collect()
        log("runtime %s exe=%s container=%s listening=%s pkg=%s stale=%s" % (
            inst.label(), inst.exe, inst.container_id, inst.listening, inst.package, inst.stale()))
        out.append(inst)
    return sorted(out, key=lambda i: (i.container_id or "", i.exe))


def discover_libraries(rule):
    """The rule's library package in the host root and every container root."""
    lib = rule.get("library")
    if not lib:
        return []
    out = []
    for root, cid, pid in [("/", None, None)] + [("/proc/%d/root" % pid, cid, pid) for cid, pid in container_roots()]:
        sl = SystemLibrary(root, cid, pid)
        sl.collect(lib)
        if sl.present:
            out.append(sl)
    log("library %s: %d roots have it" % (lib.get("packages"), len(out)))
    return out


# ----------------------------------------------------------------------------
# Rules
# ----------------------------------------------------------------------------

def load_rules(rules_dir, only=None):
    rules = []
    for p in sorted(glob.glob(os.path.join(rules_dir, "*.json"))):
        try:
            with open(p) as f:
                r = json.load(f)
        except (IOError, ValueError) as e:
            raise RuntimeError("bad rule file %s: %s" % (p, e))
        r["_file"] = os.path.basename(p)
        if only and r.get("family") not in only and not (set(r.get("cves", {}).keys()) & set(only)):
            continue
        rules.append(r)
    return rules


class Finding(object):
    def __init__(self, family, cve, subject, status, evidence, extra=None):
        self.family = family
        self.cve = cve
        self.subject = subject
        self.status = status
        self.severity = STATUS_SEVERITY[status]
        self.evidence = evidence
        self.extra = extra or {}
        self.instances = []               # runtime instances behind the finding, for reachability
        self.severity_default = self.severity
        self.severity_exposure = self.severity
        self.severity_reason = None
        self.vector = None

    def as_dict(self):
        d = {"family": self.family, "cve": self.cve, "subject": self.subject, "status": self.status,
             "severity": self.severity, "evidence": self.evidence,
             "severity_default": self.severity_default, "severity_exposure": self.severity_exposure}
        if self.vector:
            d["vector"] = self.vector
        if self.severity_reason:
            d["severity_reason"] = self.severity_reason
        d.update(self.extra)
        return d


# --- kernel rules ------------------------------------------------------------

def _kernel_fixed_by_table(rule, cdef, image, host):
    """Return (fixed_bool_or_None, evidence) from the per-distro fixed-version table.
    A CVE-level table wins over the family-level one."""
    tables = cdef.get("fixed") or rule.get("fixed") or {}
    table = tables.get(host.distro) or tables.get(host.family)
    if not table:
        return None, "no fixed-version table for %s" % host.distro
    subject = image.distro_version_string()
    if not subject:
        return None, "cannot determine distro kernel version string"
    for entry in table:
        if entry.get("release") and str(entry["release"]) != str(host.release) and host.codename != entry["release"]:
            continue
        if not re.search(entry["match"], image.release) and not re.search(entry["match"], subject):
            continue
        if entry.get("fixed") is None:
            return False, "%s: vendor lists this kernel series as vulnerable, no fix released (table)" % subject
        r = vercmp(subject, entry["fixed"])
        if r >= 0:
            return True, "%s >= fixed %s (table)" % (subject, entry["fixed"])
        return False, "%s < fixed %s (table)" % (subject, entry["fixed"])
    return None, "no table entry matches %s" % image.release


def _kernel_status_for_image(rule, cve, image, host):
    """Decide fixed / vulnerable / unknown for one kernel image; returns (status, evidence)."""
    cdef = rule["cves"][cve]
    if image.changelog and cve in image.changelog:
        return "fixed", "%s listed in %s changelog" % (cve, image.changelog_from)
    fixed, ev = _kernel_fixed_by_table(rule, cdef, image, host)
    if fixed is True:
        return "fixed", ev
    public = parse_date(cdef.get("public") or rule.get("public"))
    if fixed is False:
        return "vulnerable", ev
    # No table verdict. Fall back on the build date.
    if image.build_date and public:
        if image.build_date < public:
            return "vulnerable", "kernel built %s, before disclosure %s; %s" % (image.build_date, public, ev)
        if image.changelog:
            return "fixed" if cve in image.changelog else "vulnerable", \
                "kernel built %s after disclosure but %s not in changelog; %s" % (image.build_date, cve, ev)
        return "unknown", "kernel built %s after disclosure, no changelog or table to confirm; %s" % (image.build_date, ev)
    return "unknown", ev


def eval_kernel_rule(rule, host, kf):
    findings = []
    run_img = kf.running
    for cve, cdef in sorted(rule["cves"].items()):
        subject = "kernel %s" % run_img.release
        extra = {"kernel": run_img.release}
        # Upstream range: kernels before the regression are not affected at all.
        frm = version_tuple(cdef.get("affected_from") or rule.get("affected_from") or "")
        if frm and run_img.upstream and run_img.upstream < frm:
            findings.append(Finding(rule["family"], cve, subject, "not_applicable",
                                    "upstream %s predates the regression (affected from %s)" %
                                    (".".join(map(str, run_img.upstream)), cdef.get("affected_from") or rule.get("affected_from")), extra))
            continue
        # Kernels from an upstream release that already contains the fix (newer HWE lines).
        before = version_tuple(cdef.get("affected_before") or rule.get("affected_before") or "")
        if before and run_img.upstream and run_img.upstream >= before:
            findings.append(Finding(rule["family"], cve, subject, "fixed",
                                    "upstream %s already contains the fix (affected before %s)" %
                                    (".".join(map(str, run_img.upstream)), cdef.get("affected_before") or rule.get("affected_before")), extra))
            continue
        distros_na = cdef.get("not_affected_distros") or rule.get("not_affected_distros") or {}
        na_list = distros_na.get(host.distro) or ([] if host.family not in distros_na else distros_na[host.family])
        if na_list and ("*" in na_list or str(host.release) in na_list or host.codename in na_list):
            findings.append(Finding(rule["family"], cve, subject, "not_applicable",
                                    "%s %s marked not affected by vendor" % (host.distro, host.release), extra))
            continue
        status, ev = _kernel_status_for_image(rule, cve, run_img, host)
        # Exposure hints: evidence only, never a status change.
        if status != "fixed":
            hints = [kf.exposure(n) for n in cdef.get("exposure") or rule.get("exposure") or []]
            hints = [h for h in hints if h]
            if hints:
                ev += "; exposure: " + "; ".join(h["text"] for h in hints)
                extra["exposure"] = hints
        # Mitigations: modules and sysctl.
        mods = cdef.get("modules") or rule.get("modules") or []
        mod_states = [kf.module_state(m) for m in mods]
        mitigated_by = []
        blocked_all = bool(mods)
        for st in mod_states:
            if st["state"] in ("blocked", "absent", "blacklisted"):
                mitigated_by.append("%s %s (%s)" % (st["module"], st["state"], st["evidence"]))
            else:
                blocked_all = False
        for sm in cdef.get("sysctl_mitigations") or rule.get("sysctl_mitigations") or []:
            v = kf.sysctl_value(sm["key"])
            if v is not None and str(v) == str(sm["value"]):
                mitigated_by.append("sysctl %s=%s" % (sm["key"], v))
                blocked_all = True
        fw_specs = cdef.get("firewall_mitigations") or rule.get("firewall_mitigations") or []
        fw_problem = None
        if fw_specs and status != "fixed":
            fw_hits, fw_problem = kf.firewall_coverage(fw_specs)
            if fw_hits:
                mitigated_by.extend("firewall %s %s: %s" % (r["tool"], r["where"], r["text"]) for r in fw_hits[:2])
                blocked_all = True
            extra["firewall"] = [r["text"] for r in fw_hits] if fw_hits else []
        remedy = cdef.get("remedy") or rule.get("remedy")
        loaded = [st["module"] for st in mod_states if st["state"] == "loaded"]
        builtin = [st["module"] for st in mod_states if st["state"] == "builtin"]
        extra["modules"] = dict((st["module"], st["state"]) for st in mod_states)
        if host.is_container:
            if status in ("vulnerable", "unknown") and fw_specs and blocked_all and not loaded and not builtin and mitigated_by:
                findings.append(Finding(rule["family"], cve, subject, "mitigated",
                                        "running inside %s container, kernel belongs to the host; by version: %s; this container's own netfilter closes the path: %s" % (host.virt, ev, "; ".join(mitigated_by)), extra))
            elif status in ("vulnerable", "unknown"):
                findings.append(Finding(rule["family"], cve, subject, "host_managed",
                                        "running inside %s container, kernel belongs to the host; by version: %s; mitigation state on host not visible%s" %
                                        (host.virt, ev, "; firewall mitigation incomplete: " + fw_problem if fw_problem else ""), extra))
            else:
                findings.append(Finding(rule["family"], cve, subject, status, ev + " (kernel belongs to %s host)" % host.virt, extra))
            continue
        if status == "fixed":
            findings.append(Finding(rule["family"], cve, subject, "fixed", ev, extra))
            continue
        # vulnerable or unknown by version: overlay mitigation and reboot_pending.
        if loaded:
            ev += "; module(s) %s currently loaded, not mitigable without unload" % ",".join(loaded)
        elif builtin:
            ev += "; module(s) %s built into the kernel, not mitigable via modprobe" % ",".join(builtin)
        if blocked_all and not loaded and not builtin and mitigated_by:
            findings.append(Finding(rule["family"], cve, subject, "mitigated", ev + "; mitigated by " + "; ".join(mitigated_by), extra))
            continue
        if fw_problem:
            ev += "; firewall mitigation incomplete: " + fw_problem
        if kf.newest:
            nst, nev = _kernel_status_for_image(rule, cve, kf.newest, host)
            if nst == "fixed":
                findings.append(Finding(rule["family"], cve, subject, "reboot_pending",
                                        ev + "; installed %s is fixed (%s), reboot needed" % (kf.newest.release, nev), extra))
                continue
            ev += "; installed %s is not fixed either (%s)" % (kf.newest.release, nev)
        if not kf.modules_dir_present and status == "vulnerable" and mods and all(st["state"] == "absent" for st in mod_states):
            findings.append(Finding(rule["family"], cve, subject, "mitigated",
                                    ev + "; module files for the running kernel are gone, modules cannot load", extra))
            continue
        if kf.newest and kf.newest.release != run_img.release and vercmp(kf.newest.release, run_img.release) < 0:
            ev += "; WARNING next boot kernel %s is older than the running one" % kf.newest.release
        if status == "vulnerable" and remedy:
            ev += "; remedy: " + remedy
        findings.append(Finding(rule["family"], cve, subject, status, ev, extra))
    return findings


# --- php rules ---------------------------------------------------------------

def _php_fixed(rule, inst, host, cve):
    """(status, evidence) for a PHP instance ignoring mitigations and staleness."""
    if inst.version is None:
        return "unknown", "could not determine PHP version: %s" % "; ".join(inst.errors)
    br = inst.branch
    if inst.changelog and cve in inst.changelog:
        return "fixed", "%s listed in %s changelog (%s)" % (cve, inst.package[0], inst.package[1])
    fixed_pk = rule.get("fixed_packages", {})
    if inst.package:
        name, ver, origin = inst.package
        tbl = None
        if origin == "sury":
            tbl = fixed_pk.get("sury", {}).get(br)
            if tbl:
                r = vercmp(ver.split("+")[0], tbl)
                return ("fixed" if r >= 0 else "vulnerable"), "sury %s %s %s fixed %s" % (name, ver, ">=" if r >= 0 else "<", tbl)
        elif origin == "distro":
            osid = inst.os.get("ID", "")
            osrel = inst.os.get("VERSION_ID", "")
            tbl = fixed_pk.get(osid, {}).get(osrel, {}).get("php%s" % br)
            if tbl:
                r = vercmp(ver, tbl)
                return ("fixed" if r >= 0 else "vulnerable"), "%s %s %s %s %s fixed %s" % (osid, osrel, name, ver, ">=" if r >= 0 else "<", tbl)
    up = rule.get("fixed_upstream", {}).get(br)
    if up:
        r = vercmp(inst.version, up)
        if r >= 0:
            return "fixed", "PHP %s >= fixed %s" % (inst.version, up)
        if inst.source in ("upstream-build", "alpine", "unknown"):
            return "vulnerable", "PHP %s < fixed %s (%s)" % (inst.version, up, inst.source)
        return "vulnerable", "PHP %s < fixed %s and no distro backport evidence" % (inst.version, up)
    if br in rule.get("eol_branches", []):
        return "vulnerable", "PHP %s branch is end of life, no fixed release exists; rebuild on a supported branch" % br
    return "unknown", "no fixed version known for branch %s" % br


def _ini_matches(cond, value):
    if value is None:
        return False
    v = value.strip().lower()
    if "equals" in cond:
        return v == str(cond["equals"]).lower()
    if "in" in cond:
        return v in [str(x).lower() for x in cond["in"]]
    return False


def eval_php_rule(rule, host, instances):
    findings = []
    exposed = set(rule.get("sapi_exposed", ["fpm-fcgi", "cgi-fcgi", "apache2handler", "frankenphp", "litespeed"]))
    for inst in instances:
        if inst.sapi not in exposed:
            continue
        for cve, cdef in sorted(rule["cves"].items()):
            subject = "php %s" % inst.label()
            extra = {"php": inst.as_dict()}
            status, ev = _php_fixed(rule, inst, host, cve)
            if status == "fixed":
                if inst.stale():
                    findings.append(Finding(rule["family"], cve, subject, "stale_workers",
                                            ev + "; running processes predate the binary on disk, restart needed", extra))
                else:
                    findings.append(Finding(rule["family"], cve, subject, "fixed", ev, extra))
                continue
            mits = []
            for cond in cdef.get("mitigations", []):
                if cond.get("branch_min") and version_tuple(inst.branch or "0") and version_tuple(inst.branch) < version_tuple(cond["branch_min"]):
                    continue
                val = inst.ini.get(cond["ini"])
                if _ini_matches(cond, val):
                    mits.append("%s=%s" % (cond["ini"], val))
                else:
                    mits = None
                    break
            if status == "vulnerable" and mits:
                findings.append(Finding(rule["family"], cve, subject, "mitigated", ev + "; mitigated by " + ", ".join(mits), extra))
            else:
                findings.append(Finding(rule["family"], cve, subject, status, ev, extra))
    return findings


# --- runtime rules -----------------------------------------------------------

_CHANGELOGS = {}


def changelog_lists(root, fam, name, container_id, cve):
    """True when the changelog of an installed package names the CVE id: the vendor's own
    statement that this package carries the fix. deb: usr/share/doc/<name>/changelog.Debian.gz
    (or changelog.gz) inside the root; rpm: `rpm -q --changelog` on the host. False when there
    is no changelog (Alpine, images with stripped docs) or no entry, which proves nothing."""
    key = (root, name)
    if key not in _CHANGELOGS:
        text = None
        if fam == "deb":
            d = in_root(root, "/usr/share/doc/%s" % name)        # may be a symlink to another package's dir
            text = read_gz(os.path.join(d, "changelog.Debian.gz")) or read_gz(os.path.join(d, "changelog.gz"))
        elif fam == "rpm" and container_id is None:
            rc, out, _ = run(["rpm", "-q", "--changelog", name], timeout=30)
            text = out if rc == 0 else None
        _CHANGELOGS[key] = text or ""
    return bool(cve) and re.search(r"%s(?!\d)" % re.escape(cve), _CHANGELOGS[key]) is not None


def _upstream_part(ver):
    m = re.match(r"(\d+(?:\.\d+)*)", ver.split(":")[-1])
    return m.group(1) if m else ver


def _library_status(rule, lib, cve=None):
    """(status, evidence) for one root's copy of the library."""
    L = rule.get("library", {})
    if lib.version is None:
        return "unknown", "%s present, version not readable" % (lib.name or L.get("soname"))
    if changelog_lists(lib.root, lib.family, lib.name, lib.container_id, cve):
        return "fixed", "%s listed in %s %s changelog" % (cve, lib.name, lib.version)
    osid, osrel = lib.os.get("ID", "").lower(), lib.os.get("VERSION_ID", "")
    tbl = L.get("fixed_packages", {})
    fixed = tbl.get(osid, {}).get(osrel)
    if fixed is None and lib.family == "rpm":
        fixed = tbl.get("rpm", {}).get(osrel.split(".")[0])
    if fixed:
        r = vercmp(lib.version, fixed)
        return ("fixed" if r >= 0 else "vulnerable"), "%s %s %s fixed %s" % (lib.name, lib.version, ">=" if r >= 0 else "<", fixed)
    up = _upstream_part(lib.version)
    branch = ".".join(up.split(".")[:2])
    upfix = L.get("fixed_upstream", {}).get(branch)
    if upfix:
        r = vercmp(up, upfix)
        if r >= 0:
            return "fixed", "%s %s >= upstream fix %s" % (lib.name, lib.version, upfix)
        return "vulnerable", "%s %s < upstream fix %s, no distro backport table for %s %s" % (lib.name, lib.version, upfix, osid, osrel)
    return "unknown", "%s %s: no fixed version known for branch %s" % (lib.name, lib.version, branch)


def _runtime_status(rule, inst, libs, cdef=None, cve=None):
    spec = rule["runtimes"][inst.name]
    if inst.version is None:
        return "unknown", "could not determine %s version: %s" % (inst.name, "; ".join(inst.errors) or "no output")
    frm = (cdef or {}).get("affected_from")
    if frm and vercmp(inst.version, frm) < 0:
        return "not_applicable", "%s %s predates the vulnerable code (affected from %s)" % (inst.name, inst.version, frm)
    var = inst.variant() or {}
    core = ".".join(inst.version.split(".")[:2])
    if var.get("fixed", {}).get(core) and inst.variant_version:
        # the product backports fixes without changing the core version: its own release decides
        r = vercmp(inst.variant_version, var["fixed"][core])
        return ("fixed" if r >= 0 else "vulnerable"), "%s %s %s fixed %s release %s" % (
            var.get("name", inst.name), inst.variant_version, ">=" if r >= 0 else "<", var.get("name", inst.name), var["fixed"][core])
    if "fixed_packages" in spec or "fixed_upstream" in spec:
        shown = "%s %s" % (inst.name, inst.version)
        if var.get("name") and inst.variant_version:
            shown = "%s %s (%s core %s)" % (var["name"], inst.variant_version, inst.name, inst.version)
        # the runtime's own package: distro table first (backports keep the upstream version),
        # third-party builds and unlisted releases by the upstream fix of their branch
        third = spec.get("third_party_re")
        osid, osrel = inst.os.get("ID", "").lower(), inst.os.get("VERSION_ID", "")
        tbl = spec.get("fixed_packages", {}).get(osid)
        if tbl is None and Host._family(osid, inst.os.get("ID_LIKE", "")) == "rpm":
            # RHEL family (rhel, centos, almalinux, rocky, ol): one table keyed by major release
            tbl, osrel = spec.get("fixed_packages", {}).get("rpm", {}), osrel.split(".")[0]
        tbl = tbl or {}
        foreign = ""
        pkg = inst.package
        if pkg and _upstream_part(pkg[1]) != _upstream_part(inst.version):
            # the running binary is not the one the package ships (replaced by hand): the
            # package database says nothing about it
            foreign = "; binary %s does not match package %s %s, package ignored" % (inst.version, pkg[0], pkg[1])
            pkg = None
        if osrel not in tbl and ".".join(osrel.split(".")[:2]) in tbl:
            osrel = ".".join(osrel.split(".")[:2])          # alpine: VERSION_ID 3.22.1, table key 3.22
        branch_of = lambda v: ".".join(_upstream_part(v).split(".")[:2])
        ups = spec.get("fixed_upstream", {})
        if vercmp(inst.version, ups.get(branch_of(inst.version), "999999")) >= 0:
            # an upstream release that contains the fix is fixed whoever packaged it; the
            # distro table is only needed for backports, which keep an older upstream version
            return "fixed", "%s%s >= upstream fix %s%s" % (shown, " (%s %s)" % pkg if pkg else "",
                                                            ups[branch_of(inst.version)], foreign)
        if pkg and changelog_lists(inst.root, Host._family(osid, inst.os.get("ID_LIKE", "")), pkg[0], inst.container_id, cve):
            # the vendor's own statement, per CVE; needs no table and survives a stale one
            return "fixed", "%s listed in %s %s changelog" % (cve, pkg[0], pkg[1])
        if pkg and tbl.get(osrel) and branch_of(pkg[1]) != branch_of(tbl[osrel]):
            # a package from another branch than the distro's own (mainline image, PPA): its
            # version sorting above the distro backport proves nothing
            foreign = "; package %s %s is not the %s %s branch %s, distro table not applied" % (
                pkg[0], pkg[1], osid, osrel, branch_of(tbl[osrel]))
            tbl = {}
        if pkg and osrel in tbl and not (third and re.search(third, pkg[1])):
            fixed = tbl[osrel]
            if fixed is None:
                return "vulnerable", "%s %s: %s %s has released no fixed package yet" % (inst.package[0], inst.package[1], osid, osrel)
            r = vercmp(inst.package[1], fixed)
            return ("fixed" if r >= 0 else "vulnerable"), "%s %s %s fixed %s" % (inst.package[0], inst.package[1], ">=" if r >= 0 else "<", fixed)
        branch = ".".join(inst.version.split(".")[:2])
        what = shown + (" (%s %s)" % pkg if pkg else "")
        if branch in ups:
            r = vercmp(inst.version, ups[branch])
            return ("fixed" if r >= 0 else "vulnerable"), "%s %s upstream fix %s%s" % (what, ">=" if r >= 0 else "<", ups[branch], foreign)
        newest = sorted(ups.values(), key=version_tuple)[-1] if ups else None
        if newest and vercmp(inst.version, newest) >= 0:
            return "fixed", "%s is newer than the fixed release %s%s" % (what, newest, foreign)
        return "vulnerable", "%s: branch %s has no upstream fix (fixed in %s)%s" % (
            what, branch, " / ".join(sorted(ups.values(), key=version_tuple)),
            foreign or ("" if not pkg else ", no distro fix table entry for %s %s" % (osid, osrel)))
    na = spec.get("not_affected_before")
    if na and vercmp(inst.version, na) < 0:
        return "not_applicable", "%s %s predates the vendored library (affected from %s)" % (inst.name, inst.version, na)
    soname = rule.get("library", {}).get("soname")
    if inst.links_system_lib(soname):
        same = [l for l in libs if l.container_id == inst.container_id]
        pkg = "%s %s" % inst.package if inst.package else "%s %s" % (inst.name, inst.version)
        if same and same[0].version:
            st, ev = _library_status(rule, same[0], cve)
            return st, "%s has the system %s mapped: %s" % (pkg, soname, ev)
        return "unknown", "%s has the system %s mapped but its package version is not readable" % (pkg, soname)
    major = inst.version.split(".")[0]
    fixed = spec.get("fixed", {}).get(major)
    if fixed:
        r = vercmp(inst.version, fixed)
        return ("fixed" if r >= 0 else "vulnerable"), "%s %s %s fixed %s" % (inst.name, inst.version, ">=" if r >= 0 else "<", fixed)
    if major in [str(x) for x in spec.get("eol_lines", [])]:
        return "vulnerable", "%s %s is an end-of-life line, no fixed release exists; move to %s" % (
            inst.name, inst.version, "/".join(sorted(spec.get("fixed", {}).values())))
    return "unknown", "no fixed version known for %s line %s" % (inst.name, major)


def _multi_root_subject(prefix, members, describe, limit=10):
    """(subject, where-list) for one status across the host root and container roots, so a node
    with 150 containers yields a few findings, not 150. members have .container_id; describe(m)
    gives the per-root text."""
    hosts = [m for m in members if not m.container_id]
    conts = [m for m in members if m.container_id]
    subject = prefix + ": " + " + ".join(
        (["host"] if hosts else []) + (["%d container%s" % (len(conts), "s" if len(conts) != 1 else "")] if conts else []))
    where = [describe(m) for m in hosts + conts[:limit]]
    if len(conts) > limit:
        where.append("+%d more" % (len(conts) - limit))
    return subject, where


def _listen_ports(conf, param):
    """Ports of the listen directives carrying a parameter (e.g. http2) in a config dump."""
    ports = set()
    for m in re.finditer(r"(?:^|[;{}])\s*listen\s+([^;]*)\b%s\b[^;]*(?=;)" % re.escape(param), conf, re.M):
        first = m.group(1).split()[0] if m.group(1).split() else ""
        pm = re.search(r"(?:^|:)(\d+)$", first)
        ports.add(int(pm.group(1)) if pm else 80)
    return ports


def eval_runtime_rule(rule, host, instances, libs, kf=None):
    findings = []
    remedy = rule.get("remedy")
    for cve, cdef in sorted(rule["cves"].items()):
        rem = cdef.get("remedy", remedy)
        results = []
        for inst in instances:
            if inst.name not in rule.get("runtimes", {}):
                continue
            subject = inst.label()
            extra = {"runtime": inst.as_dict()}
            # the bug exists only in builds running with particular libraries (requires_mapped,
            # e.g. musl), and not where another one is in use (exempt_if: mapped, plus a config
            # directive when the library alone does not settle it)
            unmapped = [rx for rx in cdef.get("requires_mapped", []) if not re.search(rx, inst.maps())]
            ex = cdef.get("exempt_if") or {}
            exempt = bool(ex) and re.search(ex.get("mapped", "$^"), inst.maps()) is not None and (
                not ex.get("config") or re.search(ex["config"], inst.config() or "", re.M) is not None)
            if unmapped or exempt:
                results.append((inst, subject, "not_applicable", "%s %s: %s" % (
                    inst.name, inst.version or "?", cdef.get("exempt_text" if exempt and not unmapped else "unmapped_text",
                                                             "this build is not the affected one")), extra))
                continue
            status, ev = _runtime_status(rule, inst, libs, cdef, cve)
            if status == "fixed" and inst.stale():
                status = "stale_workers"
                ev += "; running processes predate the binary on disk, restart needed"
            elif status == "vulnerable" and (cdef.get("requires_config") or cdef.get("mitigated_if_config") or cdef.get("reachability")):
                # the bug needs particular directives; without them the path is closed. With
                # them, severity follows who can reach the listening ports.
                conf = inst.config()
                missing = [] if conf is None else [rx for rx in cdef.get("requires_config", []) if not re.search(rx, conf, re.M)]
                off = cdef.get("mitigated_if_config")
                if not missing and conf and off and re.search(off, conf, re.M) and not (
                        cdef.get("unless_config") and re.search(cdef["unless_config"], conf, re.M)):
                    status = "mitigated"
                    ev += "; %s (configuration on disk)" % cdef.get("config_off_text", "the feature is switched off")
                elif missing:
                    # "mitigated" where switching the feature off is a deliberate act, the
                    # rule's config_absent_status (not_applicable) where it was never in use
                    status = cdef.get("config_absent_status", "mitigated")
                    ev += "; %s (configuration on disk, %d of %d required directive patterns absent)" % (
                        cdef.get("config_absent_text", "the required configuration is not present"),
                        len(missing), len(cdef.get("requires_config", [])))
                else:
                    if conf is None:
                        ev += "; configuration could not be read, assumed affected"
                    ports = None
                    if conf and cdef.get("listen_param") and not (cdef.get("listen_all_if") and re.search(cdef["listen_all_if"], conf, re.M)):
                        ports = _listen_ports(conf, cdef["listen_param"])
                    state, why = instance_reachability(inst, kf, ports) if kf is not None else ("open", "firewall not evaluated")
                    extra["reachability"] = {"state": state, "detail": why}
                    if state != "open":
                        status = "restricted"
                    ev += "; %s: %s" % (cdef.get("config_present_text", "required configuration present"), why)
                    hints = [kf.exposure(n) for n in cdef.get("exposure") or rule.get("exposure") or []] if kf is not None else []
                    hints = [h for h in hints if h]
                    if hints:
                        ev += "; exposure: " + "; ".join(h["text"] for h in hints)
                    var = inst.variant()
                    if var:
                        ev += "; %s; remedy: %s" % (var.get("label", "variant"), var.get("remedy", rem))
                        extra["variant"] = var.get("label")
                    elif rem:
                        ev += "; remedy: " + rem
            elif status == "vulnerable":
                if inst.listening:
                    ev += "; listening on %s" % ",".join(inst.listening[:6])
                else:
                    status = "unknown"
                    ev += "; no listening socket, %s" % cdef.get(
                        "no_listener_text", rule.get("no_listener_text", "exposure depends on fetch()/zlib use on untrusted data"))
                var = inst.variant()
                if var:
                    ev += "; %s; remedy: %s" % (var.get("label", "variant"), var.get("remedy", rem))
                    extra["variant"] = var.get("label")
                elif rem:
                    ev += "; remedy: " + rem
            results.append((inst, subject, status, ev, extra))
        # containers with the same runtime version, status and evidence (pod replicas) share a finding
        grouped, order = {}, []
        for inst, subject, status, ev, extra in results:
            key = (inst.name, inst.version, status, ev) if inst.container_id else id(inst)
            if key not in grouped:
                order.append(key)
            grouped.setdefault(key, []).append((inst, subject, extra))
        for key in order:
            members = grouped[key]
            inst, subject, extra = members[0]
            status, ev = [r for r in results if r[0] is inst][0][2:4]
            if len(members) > 1:
                names = [where_label(m[0].container_id, m[0].runtime, m[0].container_name) for m in members]
                subject = "%s %s: %d containers" % (inst.display() + (len(members),))
                ev = "%s%s: %s" % (", ".join(names[:6]), " +%d more" % (len(names) - 6) if len(names) > 6 else "", ev)
                extra = {"runtimes": [m[2]["runtime"] for m in members]}
                for m in members:
                    if "reachability" in m[2]:
                        extra["reachability"] = m[2]["reachability"]
                        break
            fnd = Finding(rule["family"], cve, subject, status, ev, extra)
            fnd.instances = [m[0] for m in members]
            findings.append(fnd)
        # system library: one finding per status across host and containers
        groups = {}
        unreadable = [lib for lib in libs if lib.version is None]
        if unreadable:
            # library file present but no readable package database (rpm-based image seen from a
            # dpkg host, image without package manager): informational, in --facts and verbose only
            log("library %s: version not readable in %s" % (rule["family"], ", ".join(l.label() for l in unreadable[:10])))
        for lib in libs:
            if lib.version is None:
                continue
            st, ev = _library_status(rule, lib, cve)
            groups.setdefault(st, []).append((lib, ev))
        for status, members in sorted(groups.items()):
            evs = dict((id(lib), ev) for lib, ev in members)
            subject, where = _multi_root_subject(members[0][0].name, [lib for lib, _ in members],
                                                 lambda lib: "%s (%s)" % (lib.label(), evs[id(lib)]), limit=6)
            ev = "; ".join(where)
            lib_rem = rule.get("library", {}).get("remedy", rem)
            if status == "vulnerable" and lib_rem:
                ev += "; remedy: " + lib_rem
            extra = {"libraries": [lib.as_dict() for lib, _ in members]}
            findings.append(Finding(rule["family"], cve, subject, status, ev, extra))
    return findings


# --- trust store rules -------------------------------------------------------

def _cert_disabled(cert, store):
    """True when the root is shipped by the package but switched off locally with a "!" line
    in /etc/ca-certificates.conf. A vendor fix writes the same "!" line and deletes the file,
    so a missing file means removed, not disabled."""
    files = cert.get("files", []) + ["mozilla/%s.crt" % cert["name"].replace(" ", "_")]
    return any(d in files and os.path.exists(os.path.join(store.root, "usr/share/ca-certificates", d))
               for d in store.disabled)


def eval_trust_rule(rule, host, stores):
    """One finding per (status, set of trusted bad roots) covering the host and all its
    containers, so a node with 150 containers produces a few lines, not 150."""
    findings = []
    for cve, cdef in sorted(rule["cves"].items()):
        certs = cdef.get("certs", rule.get("certs", []))
        groups = {}
        for st in stores:
            if st.bundle is None:
                key = ("unknown", ())
            else:
                present = tuple(c["name"] for c in certs if c["sha256"].replace(":", "").upper() in st.fingerprints)
                key = ("vulnerable", present) if present else ("fixed", ())
            groups.setdefault(key, []).append(st)
        for (status, present), members in sorted(groups.items()):
            def describe(st, status=status):
                if st.container_id:
                    return st.label()
                how = "disabled in /etc/ca-certificates.conf" if status == "fixed" and any(_cert_disabled(c, st) for c in certs) else None
                det = ", ".join(x for x in (how, "ca-certificates %s" % st.package if st.package else None) if x)
                return "host (%s)" % det if det else "host"
            subject, where = _multi_root_subject("trust store", members, describe)
            extra = {"present": list(present), "stores": [st.as_dict() for st in members]}
            if status == "vulnerable":
                remedy = cdef.get("remedy", rule.get("remedy", "remove the certificates from the trust store"))
                ev = "still trusts %s: %s; %s" % (", ".join(present), ", ".join(where), remedy)
            elif status == "fixed":
                ev = "none of the %d listed roots trusted: %s" % (len(certs), ", ".join(where))
            else:
                ev = "no CA bundle found (looked at %s): %s" % (", ".join(TRUST_BUNDLES), ", ".join(where))
            findings.append(Finding(rule["family"], cve, subject, status, ev, extra))
    return findings


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Exposure-aware severity (--severity exposure): who can reach the host, who can run code on it
# ----------------------------------------------------------------------------

# Service classes for a listener. Open to any source, every class but "admin" is an entry point
# for foreign code; accepted only from particular sources, "admin", "data" and "system" are not
# and the classes in ENTRY_CLASSES are. Families are matched by executable name; where the name
# is ambiguous (java, beam.smp, master, python running salt) the command line or the path
# decides. A name not listed is "application" when it runs from an application directory or in
# a container, else "unknown": both count, unknown is the list worth a human look.
SERVICE_CLASS_RE = [
    ("admin", re.compile(r"^sshd$")),
    ("data", re.compile(r"^(mysqld|mariadbd|mysqld_safe|postgres|postmaster|redis-server|redis-sentinel|redis-check-rdb|"
                        r"valkey-server|valkey-sentinel|valkey-check-rdb|keydb-server|memcached|mongod|mongos|clickhouse|"
                        r"clickhouse-server|etcd|consul|minio|proxysql|pgbouncer|slapd|glusterfsd|glusterd|glusterfs|"
                        r"nsqd|nsqlookupd|nsqadmin|searchd|typesense-server|gearmand|bao)$")),
    ("system", re.compile(r"^(smtpd|exim4|dovecot|cyrus-master|pop3d|imapd|rpcbind|systemd-resolved|named|unbound|dnsmasq|"
                          r"aardvark-dns|chronyd|ntpd|danted|sockd|squid|squid-\w+|tinyproxy|3proxy|openvpn|pptpd|xinetd|"
                          r"qemu-system-\w+|lxd|incusd|cupsd|hfaxd|epmd|zabbix_server|zabbix_proxy|zabbix_agentd|"
                          r"zabbix_agent2|netdata|vmagent|vmserver|vmstorage|vmselect|vminsert|victoria-metrics[\w-]*|"
                          r"victoria-logs[\w-]*|loki|alertmanager|promtail|telegraf|vector|fluent-bit|filebeat|alloy|"
                          r"\w+[_-]exporter)$")),
    ("exec", re.compile(r"^(olivetin|dockerd|webhook|pinokio)$", re.I)),
    ("transfer", re.compile(r"^(proftpd|vsftpd|pure-ftpd|syncthing)$")),
    ("web", re.compile(r"^(nginx|apache2|httpd|caddy|traefik|envoy|varnishd|php-fpm[\d.]*|php[\d.]*|node|nodejs|bun|deno|"
                       r"ruby[\d.]*|python[\d.]*|perl[\d.]*|uwsgi|gunicorn|dotnet|grafana|grafana-server|centrifugo|"
                       r"binom-observer|jsvc|asterisk|bearerbox|smsbox|evostreamms|java|beam\.smp)$")),
]
JAVA_DATA_RE = re.compile(r"kafka\.Kafka|org\.apache\.zookeeper|org\.elasticsearch|org\.opensearch|org\.apache\.cassandra")
SERVICE_LABEL = {"asterisk": "telephony service", "bearerbox": "messaging gateway", "smsbox": "messaging gateway",
                 "evostreamms": "media server"}
ENTRY_CLASSES = ("web", "application", "transfer", "exec", "unknown")
PROXIED_CLASSES = ("web", "application", "unknown")      # may carry a request on to an application
APP_PATH_RE = re.compile(r"^/(srv|opt|home|var/www|usr/local|app|data)/")
PORT_HOLDERS = ("docker-proxy", "conmon")                # hold a host port for a container
CLASS_RANK = {"admin": 0, "system": 1, "data": 2, "unknown": 3, "application": 4, "transfer": 5, "web": 6, "exec": 7}
DATA_PORTS = set([3306, 5432, 6379, 26379, 27017, 11211])
CI_RUNNER_RE = re.compile(r"^(gitlab-runner|gitlab-runner-helper|Runner\.Listener|Runner\.Worker|buildkite-agent|"
                          r"act_runner|forgejo-runner|drone-runner-[\w-]+|woodpecker-agent|circleci-runner)$")
CI_JAVA_RE = re.compile(r"agent\.jar|remoting\.jar|slave\.jar|jetbrains\.buildServer\.agent|hudson\.remoting")
NOLOGIN_SHELL_RE = re.compile(r"(/nologin|/false|/sync|/halt|/shutdown|git-shell)$")
ADMIN_GROUPS = ("root", "sudo", "wheel", "admin")
EXPOSURE_RANK = {"closed": 0, "restricted": 1, "open": 2}


def _listen_addr(addr_hex):
    """(family, kind) of a hex local address from /proc/net/tcp{,6}."""
    b = []
    for w in range(0, len(addr_hex), 8):
        b.extend(int(addr_hex[w + j:w + j + 2], 16) for j in (6, 4, 2, 0))
    if len(b) == 16 and b[:10] == [0] * 10 and b[10:12] == [255, 255]:
        b = b[12:]
    fam = "ip" if len(b) == 4 else "ip6"
    if not any(b):
        return fam, "any"
    if (fam == "ip" and b[0] == 127) or (fam == "ip6" and b == [0] * 15 + [1]):
        return fam, "loopback"
    return fam, "addr"


def haproxy_ports(pid):
    """{port: (class, evidence)} for every bind of a running haproxy, from the configuration files
    on its command line (inside its root). A port counts by what it carries: mode http with
    servers is web; mode http or tcp serving only haproxy's own stats is system; mode tcp is
    data only with positive evidence (a database health check, or every backend server on a
    well-known data port), because tcp mode also passes TLS through to web servers. Returns {}
    when nothing can be read: the caller then treats the port as web."""
    # The worker that holds the sockets is usually chrooted (global: chroot /var/lib/haproxy),
    # so its root does not show the configuration: read through the master process instead.
    try:
        ppid = int((read_file("/proc/%d/stat" % pid, "") or "").rsplit(")", 1)[1].split()[1])
        if os.path.basename(os.readlink("/proc/%d/exe" % ppid).replace(" (deleted)", "")) == "haproxy":
            pid = ppid
    except (IndexError, ValueError, OSError):
        pass
    root = "/proc/%d/root" % pid
    argv = (read_file("/proc/%d/cmdline" % pid, "") or "").split("\0")
    files, i = [], 0
    while i < len(argv):
        if argv[i] == "-f" and i + 1 < len(argv):
            files.append(argv[i + 1])
            i += 1
        elif argv[i] == "--":
            files.extend(a for a in argv[i + 1:] if a)
            break
        i += 1
    paths = []
    for f in files or ["/etc/haproxy/haproxy.cfg"]:
        full = in_root(root, f)
        if os.path.isdir(full):
            paths.extend(sorted(glob.glob(os.path.join(full, "*.cfg"))))
        else:
            paths.append(full)
    sections, cur, dmode = [], None, None
    for path in paths:
        for raw in (read_file(path, "") or "").splitlines():
            line = re.sub(r"(^|\s)#.*$", "", raw).strip()
            if not line:
                continue
            tok = line.split()
            kw = tok[0]
            if kw in ("global", "defaults", "frontend", "listen", "backend", "resolvers", "userlist", "peers", "mailers",
                      "cache", "program", "ring", "http-errors", "fcgi-app", "crt-store"):
                cur = {"type": kw, "name": tok[1] if len(tok) > 1 else "", "mode": None, "dmode": dmode, "binds": [],
                       "refs": [], "servers": [], "stats": False, "dbcheck": False}
                if kw == "defaults":
                    dmode = None
                sections.append(cur)
                continue
            if cur is None:
                continue
            if kw == "mode" and len(tok) > 1:
                cur["mode"] = tok[1]
                if cur["type"] == "defaults":
                    dmode = tok[1]
            elif kw == "bind" and len(tok) > 1:
                for part in tok[1].split(","):
                    m = re.search(r":(\d+)(?:-(\d+))?$", part)
                    if m:
                        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
                        cur["binds"].extend(range(lo, min(hi, lo + 2000) + 1))
            elif kw in ("default_backend", "use_backend") and len(tok) > 1:
                cur["refs"].append(tok[1])
            elif kw in ("server", "server-template") and len(tok) > 2:
                addr = tok[3] if kw == "server-template" and len(tok) > 3 else tok[2]
                m = re.search(r":(\d+)$", addr)
                cur["servers"].append(int(m.group(1)) if m else None)
            elif kw == "stats" or "prometheus-exporter" in line:
                cur["stats"] = True
            elif re.match(r"option\s+(mysql-check|pgsql-check|redis-check)", line) or \
                    (kw == "tcp-check" and re.search(r"PING|PONG|info\\? replication|role:master|AUTH|SELECT", line)):
                cur["dbcheck"] = True
    backends = dict((x["name"], x) for x in sections if x["type"] in ("backend", "listen"))
    out = {}
    for sec in sections:
        if sec["type"] not in ("frontend", "listen") or not sec["binds"]:
            continue
        parts = [sec] + [backends[r] for r in sec["refs"] if r in backends]
        missing = [r for r in sec["refs"] if r not in backends]
        mode = sec["mode"] or sec["dmode"] or "tcp"
        servers = [p for x in parts for p in x["servers"]]
        stats = any(x["stats"] for x in parts)
        how = "mode %s%s" % (mode, "" if sec["mode"] else " from defaults")
        if not servers and stats and not missing:
            verdict = ("system", "haproxy %s %s: %s, only its own stats or metrics" % (sec["type"], sec["name"], how))
        elif mode == "http":
            verdict = ("web", "haproxy %s %s: %s" % (sec["type"], sec["name"], how))
        elif any(x["dbcheck"] for x in parts):
            verdict = ("data", "haproxy %s %s: %s, database health check" % (sec["type"], sec["name"], how))
        elif servers and not missing and all(p in DATA_PORTS for p in servers):
            verdict = ("data", "haproxy %s %s: %s, every backend server on data port %s" % (
                sec["type"], sec["name"], how, ",".join(str(p) for p in sorted(set(servers)))))
        else:
            verdict = ("web", "haproxy %s %s: %s without evidence of a data protocol, may pass TLS to web servers" % (
                sec["type"], sec["name"], how))
        for port in sec["binds"]:
            if port not in out or CLASS_RANK[verdict[0]] > CLASS_RANK[out[port][0]]:
                out[port] = verdict
    return out


class HostExposure(object):
    """What the host itself shows about being reachable and about running foreign code. An
    upper bound: a firewall or NAT in front of the host may close what looks open from here.
    Anything that cannot be determined counts as exposed."""

    def __init__(self, host, kf):
        self.host = host
        self.kf = kf
        self.error = None
        self.listeners = {}       # port -> {"owners", "pids", "state", "detail", "class", "evidence"}
        self.containers = []      # {"id", "pid", "ns", "where", "runtime", "state", "detail", "entry", "evidence"}
        self.lxc_guests = set()
        self.runners = set()
        self.accounts = []
        self.entry_points = []
        self._ns_pids = {}        # netns link -> pids, for looking inside containers
        self._haproxy = {}        # pid -> haproxy_ports()
        try:
            self._collect()
        except Exception as e:      # noqa: any failure means "could not tell"
            self.error = "%s: %s" % (type(e).__name__, e)
            log("host exposure failed: %s" % self.error)

    # --- classification ---------------------------------------------------------------------

    def classify(self, exe, pid, port):
        """(class, evidence) of one process listening on a port."""
        name = exe
        argv = (read_file("/proc/%d/cmdline" % pid, "") or "").replace("\0", " ") if pid else ""
        if exe == "haproxy" and pid:
            if pid not in self._haproxy:
                try:
                    self._haproxy[pid] = haproxy_ports(pid)
                except Exception as e:      # noqa
                    log("haproxy config of pid %d not parsed: %s" % (pid, e))
                    self._haproxy[pid] = {}
            if port in self._haproxy[pid]:
                return self._haproxy[pid][port]
            return "web", "haproxy: port %d not found in a readable configuration, treated as HTTP" % port
        if exe == "master":
            try:
                path = os.readlink("/proc/%d/exe" % pid)
            except OSError:
                path = ""
            return ("system", "postfix") if "postfix" in path else ("unknown", name)
        if re.match(r"^python[\d.]*$", exe) and re.search(r"\bsalt-(master|minion|api|syndic)\b", argv):
            return ("system", "salt") if "salt-api" not in argv else ("web", "salt-api")
        if exe == "java" and JAVA_DATA_RE.search(argv):
            return "data", "java: %s" % JAVA_DATA_RE.search(argv).group(0)
        if exe == "beam.smp" and re.search(r"rabbit", argv):
            return "data", "rabbitmq"
        for cls, rx in SERVICE_CLASS_RE:
            if rx.match(exe):
                return cls, name
        try:
            path = os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", "") if pid else ""
        except OSError:
            path = ""
        if APP_PATH_RE.match(path) or (pid and CGROUP_ID_RE.search(read_file("/proc/%d/cgroup" % pid, "") or "")):
            return "application", name
        return "unknown", name

    def classify_owners(self, pids, port):
        """Class of a port with these {exe: pid} holders: the most exposing one."""
        best = ("unknown", "unknown process") if not pids else None
        for exe, pid in sorted(pids.items()):
            c = self.classify(exe, pid, port)
            if best is None or CLASS_RANK[c[0]] > CLASS_RANK[best[0]]:
                best = c
        return best

    def published_target(self, port):
        """(container ip, container port) a host port is forwarded to, from the DNAT rules, or None."""
        for t in self.kf._publish_texts or []:
            if not re.search(r"dports? (\S*,)?%d\b" % port, t):
                continue
            m = re.search(r"(?:--to-destination|dnat (?:ip )?to)\s+(\d+\.\d+\.\d+\.\d+):(\d+)", t)
            if m:
                return m.group(1), int(m.group(2))
        return None

    def inside(self, ip, cport):
        """(class, evidence, container) of whatever listens on cport inside the container that owns
        ip, or None when that cannot be found."""
        for c in self.containers:
            if ip not in c["ips"]:
                continue
            inodes = set()
            for f in ("tcp", "tcp6"):
                for line in (read_file("/proc/%d/net/%s" % (c["pid"], f), "") or "").splitlines()[1:]:
                    parts = line.split()
                    if len(parts) > 9 and parts[3] == "0A" and int(parts[1].rsplit(":", 1)[1], 16) == cport:
                        inodes.add(parts[9])
            holders = {}
            for pid in self._ns_pids.get(c["ns"], []):
                try:
                    for fd in os.listdir("/proc/%d/fd" % pid):
                        l = os.readlink("/proc/%d/fd/%s" % (pid, fd))
                        if l.startswith("socket:[") and l[8:-1] in inodes:
                            holders.setdefault(os.path.basename(os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", "")), pid)
                except OSError:
                    continue
            if not holders:
                return None
            cls, ev = self.classify_owners(holders, cport)
            return cls, "%s in %s" % (ev, c["where"]), c
        return None

    # --- collection -------------------------------------------------------------------------

    def _collect(self):
        try:
            own_ns = os.readlink("/proc/self/ns/net")
        except OSError:
            own_ns = None
        sockets = {}              # inode -> set of (family, kind, port)
        for f in ("tcp", "tcp6"):
            for line in (read_file("/proc/net/%s" % f, "") or "").splitlines()[1:]:
                parts = line.split()
                if len(parts) > 9 and parts[3] == "0A":
                    addr, port = parts[1].rsplit(":", 1)
                    fam, kind = _listen_addr(addr)
                    eps = sockets.setdefault(parts[9], set())
                    eps.add((fam, kind, int(port, 16)))
                    if fam == "ip6" and kind == "any":
                        eps.add(("ip", "any", int(port, 16)))
        owners = {}               # inode -> {exe basename: pid}
        proxies = {}              # docker-proxy pid -> (container ip, container port)
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            pid = int(d)
            cg = read_file("/proc/%d/cgroup" % pid, "") or ""
            if not self.host.is_container:
                m = LXC_GUEST_RE.search(cg)
                if m:
                    self.lxc_guests.add(m.group(1))
                    continue
            try:
                exe = os.path.basename(os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", ""))
            except OSError:
                continue
            argv = (read_file("/proc/%d/cmdline" % pid, "") or "").split("\0")
            arg0 = os.path.basename(argv[0]) if argv and argv[0] else ""
            if CI_RUNNER_RE.match(exe) or CI_RUNNER_RE.match(arg0) or \
                    (exe == "java" and CI_JAVA_RE.search(" ".join(argv))):
                self.runners.add(exe if CI_RUNNER_RE.match(exe) else (arg0 if CI_RUNNER_RE.match(arg0) else "java build agent"))
            if exe == "docker-proxy" and "-container-ip" in argv and "-container-port" in argv:
                try:
                    proxies[pid] = (argv[argv.index("-container-ip") + 1], int(argv[argv.index("-container-port") + 1]))
                except (IndexError, ValueError):
                    pass
            try:
                ns = os.readlink("/proc/%d/ns/net" % pid)
            except OSError:
                continue
            if own_ns and ns != own_ns:
                self._ns_pids.setdefault(ns, []).append(pid)
                continue
            try:
                fds = os.listdir("/proc/%d/fd" % pid)
            except OSError:
                continue
            for fd in fds:
                try:
                    l = os.readlink("/proc/%d/fd/%s" % (pid, fd))
                except OSError:
                    continue
                if l.startswith("socket:[") and l[8:-1] in sockets:
                    owners.setdefault(l[8:-1], {}).setdefault(exe, pid)
        # A socket-activated service is listened on by systemd: name the unit it starts instead.
        # With other holders present (sshd next to ssh.socket) systemd is just dropped.
        units = None
        for inode, names in owners.items():
            if "systemd" not in names:
                continue
            del names["systemd"]
            if names:
                continue
            if units is None:
                units = {}
                if which("systemctl"):
                    rc, out, _ = run(["systemctl", "list-sockets", "--no-legend", "--no-pager"], timeout=10)
                    for line in out.splitlines() if rc == 0 else []:
                        parts = line.split()
                        m = re.search(r":(\d+)$", parts[0]) if len(parts) >= 3 else None
                        if m:
                            units[int(m.group(1))] = parts[-1]
            for fam, kind, port in sockets[inode]:
                unit = units.get(port, "")
                names["sshd" if re.match(r"sshd?(@.*)?\.service$", unit) else (unit or "systemd socket")] = 0
        # containers with their own network namespace
        for cid, pid in container_roots():
            try:
                ns = os.readlink("/proc/%d/ns/net" % pid)
            except OSError:
                continue
            if own_ns and ns == own_ns:
                continue          # host network: its listeners are judged with the host's
            runtime, name, _ = describe_container(pid, cid)
            state, detail = netns_reachability(pid, runtime, self.kf)
            self.containers.append({"id": cid, "pid": pid, "ns": ns, "ips": _netns_local_ips(pid), "runtime": runtime,
                                    "where": where_label(cid, runtime, name), "state": state, "detail": detail,
                                    "entry": state == "open", "evidence": detail})
        # a published Docker/podman container counts by what listens inside on the published ports
        texts = self.kf._publish_texts or []
        for c in self.containers:
            if c["state"] != "open" or c["runtime"] not in ("docker", "podman"):
                continue
            cports = set()
            for ip in c["ips"]:
                for t in texts:
                    for m in re.finditer(r"(?:--to-destination|dnat (?:ip )?to)\s+%s:(\d+)" % re.escape(ip), t):
                        cports.add(int(m.group(1)))
                    m = re.search(r"-container-ip\s+%s\s.*-container-port\s+(\d+)" % re.escape(ip), t)
                    if m:
                        cports.add(int(m.group(1)))
            found = [self.inside(sorted(c["ips"])[0], p) for p in sorted(cports)] if c["ips"] else []
            if cports and all(found):
                worst = max(found, key=lambda x: CLASS_RANK[x[0]])
                c["entry"] = worst[0] in ENTRY_CLASSES
                c["evidence"] = "published port(s) %s: %s" % (",".join(str(p) for p in sorted(cports)),
                                                              "; ".join(sorted(set(x[1] for x in found))))
        v6_global = any(len(l.split()) > 5 and l.split()[3] == "00" and l.split()[5] != "lo"
                        for l in (read_file("/proc/net/if_inet6", "") or "").splitlines())
        for inode, eps in sockets.items():
            for fam, kind, port in eps:
                if kind == "loopback" or (fam == "ip6" and not v6_global):
                    continue
                state, detail = self.kf.port_reachability(fam, port)
                L = self.listeners.setdefault(port, {"owners": set(), "pids": {}, "state": "closed", "detail": "",
                                                     "class": None, "evidence": "", "container": None})
                L["owners"].update(owners.get(inode, {}).keys())
                for exe, pid in owners.get(inode, {}).items():
                    L["pids"].setdefault(exe, pid)
                if EXPOSURE_RANK[state] >= EXPOSURE_RANK[L["state"]]:
                    L["state"], L["detail"] = state, detail
        for port, L in self.listeners.items():
            if L["owners"] and set(L["owners"]) <= set(PORT_HOLDERS):
                # the port is held for a container: it counts by what listens inside
                target = proxies.get(L["pids"].get("docker-proxy")) or self.published_target(port)
                got = self.inside(*target) if target else None
                if got:
                    L["class"], L["evidence"], L["container"] = got[0], got[1], got[2]["where"]
                else:
                    L["class"], L["evidence"] = "unknown", "published container port, listener inside not identified"
                continue
            L["class"], L["evidence"] = self.classify_owners(L["pids"], port)
        self._accounts()
        self._entry_points()

    def _accounts(self):
        """Login accounts that are not administrators: a normal uid, a real login shell, able to
        log in (usable password hash or a non-empty authorized_keys), and neither in an admin
        group nor named in sudoers. Unreadable sudoers means not an administrator."""
        m = re.search(r"^\s*UID_MIN\s+(\d+)", read_file("/etc/login.defs", "") or "", re.M)
        uid_min = int(m.group(1)) if m else 1000
        shadow = dict((l.split(":")[0], l.split(":")[1]) for l in (read_file("/etc/shadow", "") or "").splitlines() if l.count(":") >= 2)
        groups, gid_name = {}, {}
        for l in (read_file("/etc/group", "") or "").splitlines():
            parts = l.split(":")
            if len(parts) >= 4:
                gid_name[parts[2]] = parts[0]
                for u in parts[3].split(","):
                    if u:
                        groups.setdefault(u, set()).add(parts[0])
        sudoers = read_file("/etc/sudoers", "") or ""
        for p in sorted(glob.glob("/etc/sudoers.d/*")):
            sudoers += "\n" + (read_file(p, "") or "")
        sudo_names = set(l.split()[0] for l in sudoers.splitlines() if l.strip() and not l.lstrip().startswith(("#", "Defaults")))
        for l in (read_file("/etc/passwd", "") or "").splitlines():
            parts = l.split(":")
            if len(parts) < 7 or not parts[2].isdigit():
                continue
            name, uid, gid, home, shell = parts[0], int(parts[2]), parts[3], parts[5], parts[6]
            if uid < uid_min or uid >= 65534 or NOLOGIN_SHELL_RE.search(shell):
                continue
            pw = shadow.get(name, "*")
            keys = any(os.path.getsize(k) > 0 for k in (os.path.join(home, ".ssh/authorized_keys"), os.path.join(home, ".ssh/authorized_keys2"))
                       if os.path.isfile(k))
            if (pw.startswith(("!", "*")) or pw == "x") and not keys:
                continue
            mine = groups.get(name, set()) | set([gid_name.get(gid, "")])
            if mine & set(ADMIN_GROUPS) or name in sudo_names or any("%" + g in sudo_names for g in mine):
                continue
            self.accounts.append(name)

    def _entry_points(self):
        ep = []
        for port, L in sorted(self.listeners.items()):
            if L["container"]:
                continue          # a published container: reported with the containers below
            who = ",".join(sorted(L["owners"])) or "unknown process"
            what = "%s port %d" % (who, port) if L["evidence"] in L["owners"] or not L["evidence"] else "%s port %d: %s" % (who, port, L["evidence"])
            if L["state"] == "open" and L["class"] != "admin":
                ep.append("service open to any source (%s)" % what)
            elif L["state"] == "restricted" and L["class"] in ENTRY_CLASSES:
                label = next((SERVICE_LABEL[o] for o in sorted(L["owners"]) if o in SERVICE_LABEL), None)
                if L["class"] == "exec":
                    ep.append("service that runs commands by design (%s)" % what)
                elif L["class"] == "unknown":
                    ep.append("unclassified service accepted from particular sources (%s)" % what)
                elif L["class"] == "transfer":
                    ep.append("file transfer service accepted from particular sources (%s)" % what)
                elif L["class"] == "application":
                    ep.append("application service accepted from particular sources, which may be a proxy (%s)" % what)
                elif label:
                    ep.append("%s accepted from particular sources (%s)" % (label, what))
                else:
                    ep.append("web or application service accepted from particular sources, which may be a proxy (%s)" % what)
        for c in self.containers:
            if not c["entry"]:
                continue
            if c["runtime"] in ("docker", "podman"):
                ep.append("published container (%s: %s)" % (c["where"], c["evidence"]))
        other = [c for c in self.containers if c["entry"] and c["runtime"] not in ("docker", "podman")]
        if other:
            ep.append("%d container(s) of a runtime that cannot be judged (%s)" % (
                len(other), ", ".join(c["where"] for c in other[:3]) + (", ..." if len(other) > 3 else "")))
        if self.lxc_guests:
            ep.append("%d LXC/Incus guest(s) run on this kernel" % len(self.lxc_guests))
        for r in sorted(self.runners):
            ep.append("CI runner or build agent (%s)" % r)
        if self.accounts:
            ep.append("non-admin login account(s): %s" % ", ".join(self.accounts[:5]) + (", ..." if len(self.accounts) > 5 else ""))
        self.entry_points = ep

    def judge(self, instances, through_proxy):
        """Reachability of a remote bug: ("open"|"proxy"|"limited"|"closed", text). The ports
        judged are the instance's own non-loopback TCP listeners in the host namespace; for a
        container its own publication; otherwise, and for a kernel bug, every listener of the
        host. through_proxy bugs travel in an ordinary request, so a source-limited port may
        still deliver them (the sources may be a load balancer); for those, host-wide judgement
        keeps only ports whose service class may carry a request on to an application."""
        own_ports, hostwide = set(), not instances
        try:
            own_ns = os.readlink("/proc/self/ns/net")
        except OSError:
            own_ns = None
        for inst in instances:
            try:
                same = own_ns is not None and os.readlink("/proc/%d/ns/net" % inst.pid) == own_ns
            except OSError:
                same = not inst.container_id
            if not same:
                for c in self.containers:
                    if c["id"] == inst.container_id and c["state"] == "open":
                        return "open", c["detail"]
                hostwide = True
                continue
            mine = set(e[2] for e in getattr(inst, "endpoints", []) if e[1] != "loopback")
            if mine:
                own_ports.update(mine)
            else:
                hostwide = True
        cand = []                 # (port, state)
        for port, L in self.listeners.items():
            if port in own_ports:
                cand.append((port, L["state"]))
            elif hostwide and not (through_proxy and L["class"] not in PROXIED_CLASSES):
                cand.append((port, L["state"]))
        if hostwide:
            for c in self.containers:
                if c["state"] == "open" and (c["entry"] or not through_proxy):
                    return "open", "%s: %s" % (c["where"], c["detail"])
        opened = sorted(p for p, st in cand if st == "open")
        if opened:
            return "open", "port %s open to any source" % ",".join(str(p) for p in opened[:6])
        limited = sorted(p for p, st in cand if st == "restricted")
        if limited:
            ports = ",".join(str(p) for p in limited[:6])
            if through_proxy:
                return "proxy", "port %s accepted from particular sources, which may be a proxy" % ports
            return "limited", "port %s accepted only from particular sources" % ports
        if cand:
            return "closed", "no accept rule for port %s" % ",".join(str(p) for p, _ in sorted(cand)[:6])
        return "closed", "no TCP listener reachable from outside the host" if hostwide else "no non-loopback listener"

    def as_dict(self):
        return {"error": self.error,
                "listeners": [{"port": p, "owners": sorted(L["owners"]), "state": L["state"], "class": L["class"],
                               "evidence": L["evidence"]} for p, L in sorted(self.listeners.items())],
                "open_ports": sorted(p for p, L in self.listeners.items() if L["state"] == "open"),
                "limited_ports": sorted(p for p, L in self.listeners.items() if L["state"] == "restricted"),
                "containers": [{"where": c["where"], "state": c["state"], "entry": c["entry"], "evidence": c["evidence"]}
                               for c in self.containers],
                "lxc_guests": sorted(self.lxc_guests), "ci_runners": sorted(self.runners),
                "non_admin_accounts": self.accounts, "entry_points": self.entry_points}

    def summary(self):
        if self.error:
            return "could not be determined (%s), assumed exposed" % self.error
        d = self.as_dict()
        return "open to any: %s; limited: %s; entry points: %d" % (
            ",".join(str(p) for p in d["open_ports"]) or "-", ",".join(str(p) for p in d["limited_ports"]) or "-", len(self.entry_points))


def exposure_severity(f, rule, hx):
    """(severity, reason) of a finding in exposure mode; sets f.vector. Only vulnerable findings
    are touched, and only lowered from critical to major. A rule without a vector is remote, a
    remote rule that does not say passes a reverse proxy: the cautious defaults."""
    cdef = rule.get("cves", {}).get(f.cve, {})
    vector = cdef.get("vector") or rule.get("vector") or "remote"
    if "libraries" in f.extra:
        vector = rule.get("library", {}).get("vector") or vector
    f.vector = vector
    if f.status != "vulnerable":
        return STATUS_SEVERITY[f.status], None
    if hx.error:
        return "critical", "host exposure could not be determined (%s): assumed exposed" % hx.error
    if vector == "library":
        return "major", "installed library, no exposed process found using it"
    if vector == "trust":
        return "major", "needs a position in the network path"
    if vector == "local":
        if hx.entry_points:
            more = " (+%d more)" % (len(hx.entry_points) - 1) if len(hx.entry_points) > 1 else ""
            return "critical", "local bug: entry point found: %s%s" % (hx.entry_points[0], more)
        return "major", "local bug: no entry point for foreign code found on this host"
    through = cdef.get("through_proxy", rule.get("through_proxy", True))
    state, why = hx.judge(f.instances, through)
    if state == "open":
        return "critical", "remote bug: %s" % why
    if state == "proxy":
        return "critical", "remote bug that passes a reverse proxy: %s" % why
    return "major", "remote bug: %s" % why


def worst(findings):
    sev = "ok"
    for f in findings:
        if SEVERITY_RANK[f.severity] > SEVERITY_RANK[sev]:
            sev = f.severity
    return sev


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description="Read-only probe for a curated list of critical CVEs.")
    ap.add_argument("--rules-dir", default=RULES_DIR)
    ap.add_argument("--only", action="append", help="rule family or CVE id to evaluate (repeatable)")
    ap.add_argument("--kernel-only", action="store_true")
    ap.add_argument("--php-only", action="store_true")
    ap.add_argument("--json", action="store_true", help="print JSON report instead of text")
    ap.add_argument("--facts", action="store_true", help="include raw facts in JSON output")
    ap.add_argument("--all", action="store_true", help="text output: list ok findings too")
    ap.add_argument("--severity", choices=["default", "exposure"], default="default",
                    help="severity scheme for the headline severity and exit code: default (fixed per status) or "
                         "exposure (vulnerable findings weighed by who can reach the host or run code on it)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--version", action="version", version="cve_probe %s" % VERSION)
    args = ap.parse_args()
    VERBOSE = args.verbose

    if os.geteuid() != 0:
        sys.stderr.write("cve_probe: must run as root (reads /proc/PID/root and nsenter)\n")
        return EXIT_PROBE_ERROR

    started = time.time()
    try:
        rules = load_rules(args.rules_dir, args.only)
    except RuntimeError as e:
        sys.stderr.write("cve_probe: %s\n" % e)
        return EXIT_PROBE_ERROR
    if not rules:
        sys.stderr.write("cve_probe: no rules loaded from %s\n" % args.rules_dir)
        return EXIT_PROBE_ERROR

    host = Host()
    log("host: %s" % host.as_dict())
    global _LXC_GUESTS
    if not host.is_container:
        _LXC_GUESTS = set()
    kinds = set(r.get("kind") for r in rules)
    kf = None
    instances = []
    if "kernel" in kinds and not args.php_only:
        kf = KernelFacts(host)
        log("kernel: %s" % kf.as_dict())
    if "php" in kinds and not args.kernel_only:
        instances = discover_php(host)
    stores = []
    if "trust_store" in kinds and not args.kernel_only and not args.php_only:
        stores = discover_trust_stores()
    runtimes, libs = [], {}
    if "runtime" in kinds and not args.kernel_only and not args.php_only:
        rt_rules = [r for r in rules if r.get("kind") == "runtime"]
        runtimes = discover_runtimes(rt_rules)
        libs = dict((r["family"], discover_libraries(r)) for r in rt_rules)

    findings = []
    for rule in rules:
        if rule.get("kind") == "kernel" and kf is not None:
            findings.extend(eval_kernel_rule(rule, host, kf))
        elif rule.get("kind") == "php" and not args.kernel_only:
            findings.extend(eval_php_rule(rule, host, instances))
        elif rule.get("kind") == "trust_store" and stores:
            findings.extend(eval_trust_rule(rule, host, stores))
        elif rule.get("kind") == "runtime" and rule["family"] in libs:
            if kf is None and any(c.get("requires_config") or c.get("mitigated_if_config") or c.get("reachability")
                                  for c in rule["cves"].values()):
                kf = KernelFacts(host)        # reachability and module evidence need it
            findings.extend(eval_runtime_rule(rule, host, runtimes, libs[rule["family"]], kf))

    # Both severities are always computed; --severity only chooses the headline one.
    sev_default = worst(findings)
    hx = HostExposure(host, kf if kf is not None else KernelFacts(host))
    log("host exposure: %s" % hx.as_dict())
    by_family = dict((r["family"], r) for r in rules)
    for f in findings:
        f.severity_exposure, f.severity_reason = exposure_severity(f, by_family.get(f.family, {}), hx)
        if args.severity == "exposure":
            f.severity = f.severity_exposure
    sev_exposure = "ok"
    for f in findings:
        if SEVERITY_RANK[f.severity_exposure] > SEVERITY_RANK[sev_exposure]:
            sev_exposure = f.severity_exposure
    sev = worst(findings)
    report = {
        "probe": "cve_probe", "version": VERSION, "host": host.as_dict(),
        "severity": sev, "exit_code": SEVERITY_EXIT[sev],
        "severity_mode": args.severity,
        "severity_default": sev_default, "exit_code_default": SEVERITY_EXIT[sev_default],
        "severity_exposure": sev_exposure, "exit_code_exposure": SEVERITY_EXIT[sev_exposure],
        "host_exposure": hx.as_dict(),
        "rules": [r["_file"] for r in rules],
        "findings": [f.as_dict() for f in findings],
        "duration_s": round(time.time() - started, 1),
    }
    if args.facts:
        report["facts"] = {"kernel": kf.as_dict() if kf else None,
                           "lxc_guests_skipped": sorted(_LXC_GUESTS or []),
                           "php": [i.as_dict() for i in instances],
                           "trust_stores": [s.as_dict() for s in stores],
                           "runtimes": [i.as_dict() for i in runtimes],
                           "libraries": dict((k, [l.as_dict() for l in v]) for k, v in libs.items())}

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("%s %s %s %s virt=%s" % (host.hostname, host.distro, host.release, host.arch, host.virt))
        if kf:
            print("kernel %s built %s pkg=%s newest_installed=%s" % (
                kf.running.release, kf.running.build_date, kf.running.version,
                kf.newest.release if kf.newest else "-"))
        for inst in instances:
            print("php %s sapi=%s source=%s pkg=%s ini=%s workers=%d%s" % (
                inst.label(), inst.sapi, inst.source, inst.package[1] if inst.package else "-",
                json.dumps(dict((k, v) for k, v in inst.ini.items() if k in ("memory_limit", "session.upload_progress.enabled", "fatal_error_backtraces"))),
                len(inst.pids), " STALE" if inst.stale() else ""))
            for e in inst.errors:
                print("    error: %s" % e)
        if stores:
            print("trust stores: host%s" % (" + %d containers" % (len(stores) - 1) if len(stores) > 1 else ""))
        if _LXC_GUESTS:
            print("lxc guests skipped (own minions): %s" % ", ".join(sorted(_LXC_GUESTS)))
        for inst in runtimes:
            print("runtime %s listening=%s pkg=%s procs=%d%s" % (
                inst.label(), ",".join(inst.listening) or "-",
                "%s %s" % inst.package if inst.package else "-", len(inst.pids), " STALE" if inst.stale() else ""))
            for e in inst.errors:
                print("    error: %s" % e)
        if args.severity == "exposure":
            print("host exposure: %s" % hx.summary())
        print("")
        hidden = 0
        for f in sorted(findings, key=lambda f: (-SEVERITY_RANK[f.severity], f.family, f.cve)):
            if f.severity == "ok" and not args.all:
                hidden += 1
                continue
            print("%-9s %-15s %-17s %s" % (f.severity.upper(), f.status, f.cve, f.subject))
            if args.severity == "exposure" and f.severity_reason:
                print("          %s; severity: %s, %s" % (f.evidence, f.severity, f.severity_reason))
            else:
                print("          %s" % f.evidence)
        if hidden:
            print("%d ok findings not listed (use --all)" % hidden)
        print("")
        print("overall: %s (exit %d), %d findings, %.1fs%s" % (
            sev, SEVERITY_EXIT[sev], len(findings), report["duration_s"],
            ", severity mode exposure" if args.severity == "exposure" else ""))
    return SEVERITY_EXIT[sev]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_PROBE_ERROR)
