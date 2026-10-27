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
import glob
import gzip
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import date, datetime

VERSION = "1.0"
RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
CMD_TIMEOUT = 20

# Status -> severity (agreed with the fleet alert policy), severity -> exit code.
STATUS_SEVERITY = {
    "vulnerable": "critical",
    "reboot_pending": "major",
    "stale_workers": "major",
    "host_managed": "major",
    "unknown": "major",
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
    """Resolve path inside another root (e.g. /proc/PID/root), following one level
    of symlink without escaping the root. Good enough for dpkg doc dir symlinks."""
    full = os.path.join(root, path.lstrip("/"))
    try:
        if os.path.islink(full):
            target = os.readlink(full)
            if target.startswith("/"):
                full = os.path.join(root, target.lstrip("/"))
            else:
                full = os.path.normpath(os.path.join(os.path.dirname(full), target))
    except OSError:
        pass
    return full


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
        self._module_cache = {}

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
                # modprobe prints nothing for builtin modules it knows about; treat as builtin if the
                # kconfig says =y, otherwise loadable.
                st["state"] = "unknown"
                st["evidence"] = "modprobe -n printed nothing"
            else:
                st["state"] = "unknown"
                st["evidence"] = text[-200:] if text else "no modprobe output"
        self._module_cache[mod] = st
        return st

    def as_dict(self):
        return {"running": self.running.as_dict(), "installed": self.installed,
                "newest_installed": self.newest.as_dict() if self.newest else None,
                "modules_dir_present": self.modules_dir_present,
                "kconfig_available": bool(self.kconfig)}


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
        try:
            stat = read_file("/proc/%d/stat" % self.pid, "")
            rest = stat[stat.rindex(")") + 2:].split()
            starttime = int(rest[19])
            bt = _btime()
            if bt:
                self.start_time = bt + starttime / float(_clk_tck())
        except (ValueError, IndexError, AttributeError):
            pass
        try:
            self.exe_mtime = os.stat(os.path.join(self.root, self.exe_path.lstrip("/"))).st_mtime
        except OSError:
            pass

    def _container_meta(self):
        if not self.container_id:
            return
        cg = read_file("/proc/%d/cgroup" % self.pid, "") or ""
        if "libpod-" in cg:
            self.runtime = "podman"
        elif "cri-containerd" in cg or "kubepods" in cg:
            self.runtime = "containerd"
        elif "docker" in cg:
            self.runtime = "docker"
        else:
            self.runtime = "unknown"
        cid = self.container_id
        if self.runtime in ("docker", "podman", "unknown"):
            for cli in ("docker", "podman"):
                if not which(cli):
                    continue
                rc, out, _ = run([cli, "inspect", "--format", "{{.Name}}\t{{.Config.Image}}", cid], timeout=10)
                if rc == 0 and out.strip():
                    name, image = (out.strip().split("\t") + [""])[:2]
                    self.container_name, self.image = name.lstrip("/"), image
                    if self.runtime == "unknown":
                        self.runtime = cli
                    return
        if self.runtime in ("containerd", "unknown") and which("crictl"):
            for ep in (None, "unix:///run/containerd/containerd.sock", "unix:///run/k0s/containerd.sock"):
                cmd = ["crictl"] + (["--runtime-endpoint", ep] if ep else []) + ["inspect", cid]
                rc, out, _ = run(cmd, timeout=10)
                if rc == 0:
                    try:
                        d = json.loads(out)
                        labels = d.get("status", {}).get("labels", {})
                        self.container_name = "%s/%s" % (labels.get("io.kubernetes.pod.namespace", "?"),
                                                         labels.get("io.kubernetes.pod.name", cid[:12]))
                        self.image = d.get("status", {}).get("image", {}).get("image")
                    except ValueError:
                        pass
                    return
        if self.container_name is None:
            self.container_name = cid[:12]

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
            db = read_file(os.path.join(self.root, "lib/apk/db/installed"))
            if not db:
                return
            m = re.match(r"php-fpm(\d+)$", base)
            wanted = ["php%s-fpm" % m.group(1), "php%s" % m.group(1)] if m else ["php-fpm", "php"]
            cur = {}
            for block in db.split("\n\n"):
                rec = dict((l[0], l[2:]) for l in block.splitlines() if len(l) > 2 and l[1] == ":")
                if rec.get("P") in wanted:
                    cur[rec["P"]] = rec.get("V")
            for w in wanted:
                if w in cur:
                    self.package = (w, cur[w], "alpine")
                    return

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
        if self.container_id:
            if not which("nsenter"):
                self.errors.append("nsenter not available, cannot inspect container")
                return (-1, "", "no nsenter")
            return run(["nsenter", "-t", str(self.pid), "-m", "-u", "-p", "--"] + argv, timeout=CMD_TIMEOUT)
        return run(argv, timeout=CMD_TIMEOUT)

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
        """True when the binary on disk is newer than the running process (restart needed)."""
        if self.deleted:
            return True
        if self.start_time and self.exe_mtime:
            return self.exe_mtime > self.start_time + 1
        return False

    def label(self):
        where = "host" if not self.container_id else "%s:%s" % (self.runtime, self.container_name)
        return "%s %s (%s)" % (os.path.basename(self.exe_path), self.version or "?", where)

    def as_dict(self):
        return {"pid": self.pid, "workers": len(self.pids), "exe": self.exe_path, "sapi": self.sapi,
                "container_id": self.container_id, "runtime": self.runtime, "container": self.container_name,
                "image": self.image, "os": "%s %s" % (self.os.get("ID", "?"), self.os.get("VERSION_ID", "")),
                "version": self.version, "version_full": self.version_full, "branch": self.branch,
                "built": str(self.built) if self.built else None,
                "package": self.package, "source": self.source, "ini": self.ini, "stale": self.stale(),
                "errors": self.errors}


def discover_php(host):
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
        base = os.path.basename(exe.replace(" (deleted)", ""))
        if not PHP_EXE_RE.match(base):
            continue
        cg = read_file("/proc/%d/cgroup" % pid, "") or ""
        m = CGROUP_ID_RE.search(cg)
        cid = m.group(1) if m else None
        if host.is_container and cid is None:
            pass  # inside an LXC minion everything is "host"
        key = (cid, exe)
        if key in groups:
            groups[key].pids.append(pid)
            if pid < groups[key].pid:
                groups[key].pid = pid
                groups[key].root = "/proc/%d/root" % pid
        else:
            groups[key] = PhpInstance(pid, exe, cid, host)
    instances = []
    for inst in groups.values():
        if inst.sapi == "apache2handler" and not inst._mod_php_lib():
            continue  # apache without mod_php is not a PHP runtime
        log("php instance pid=%d exe=%s container=%s" % (inst.pid, inst.exe, inst.container_id))
        inst.collect()
        instances.append(inst)
    return sorted(instances, key=lambda i: (i.container_id or "", i.exe))


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

    def as_dict(self):
        d = {"family": self.family, "cve": self.cve, "subject": self.subject, "status": self.status,
             "severity": self.severity, "evidence": self.evidence}
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
        distros_na = cdef.get("not_affected_distros") or rule.get("not_affected_distros") or {}
        na_list = distros_na.get(host.distro) or ([] if host.family not in distros_na else distros_na[host.family])
        if na_list and ("*" in na_list or str(host.release) in na_list or host.codename in na_list):
            findings.append(Finding(rule["family"], cve, subject, "not_applicable",
                                    "%s %s marked not affected by vendor" % (host.distro, host.release), extra))
            continue
        status, ev = _kernel_status_for_image(rule, cve, run_img, host)
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
        loaded = [st["module"] for st in mod_states if st["state"] == "loaded"]
        builtin = [st["module"] for st in mod_states if st["state"] == "builtin"]
        extra["modules"] = dict((st["module"], st["state"]) for st in mod_states)
        if host.is_container:
            if status in ("vulnerable", "unknown"):
                findings.append(Finding(rule["family"], cve, subject, "host_managed",
                                        "running inside %s container, kernel belongs to the host; by version: %s; mitigation state on host not visible" % (host.virt, ev), extra))
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


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

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
    kinds = set(r.get("kind") for r in rules)
    kf = None
    instances = []
    if "kernel" in kinds and not args.php_only:
        kf = KernelFacts(host)
        log("kernel: %s" % kf.as_dict())
    if "php" in kinds and not args.kernel_only:
        instances = discover_php(host)

    findings = []
    for rule in rules:
        if rule.get("kind") == "kernel" and kf is not None:
            findings.extend(eval_kernel_rule(rule, host, kf))
        elif rule.get("kind") == "php" and not args.kernel_only:
            findings.extend(eval_php_rule(rule, host, instances))

    sev = worst(findings)
    report = {
        "probe": "cve_probe", "version": VERSION, "host": host.as_dict(),
        "severity": sev, "exit_code": SEVERITY_EXIT[sev],
        "rules": [r["_file"] for r in rules],
        "findings": [f.as_dict() for f in findings],
        "duration_s": round(time.time() - started, 1),
    }
    if args.facts:
        report["facts"] = {"kernel": kf.as_dict() if kf else None,
                           "php": [i.as_dict() for i in instances]}

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
        print("")
        hidden = 0
        for f in sorted(findings, key=lambda f: (-SEVERITY_RANK[f.severity], f.family, f.cve)):
            if f.severity == "ok" and not args.all:
                hidden += 1
                continue
            print("%-9s %-15s %-17s %s" % (f.severity.upper(), f.status, f.cve, f.subject))
            print("          %s" % f.evidence)
        if hidden:
            print("%d ok findings not listed (use --all)" % hidden)
        print("")
        print("overall: %s (exit %d), %d findings, %.1fs" % (sev, SEVERITY_EXIT[sev], len(findings), report["duration_s"]))
    return SEVERITY_EXIT[sev]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_PROBE_ERROR)
