# ruff: noqa
# type: ignore
# Device nodes, /proc and /sys, the environment and the C getenv.
import ctypes
import fcntl
import io
import os
import select
import selectors
import stat
import sys
import termios

libc = ctypes.CDLL(None, use_errno=True)

# device nodes
for dev in (
    "/dev",
    "/dev/null",
    "/dev/zero",
    "/dev/urandom",
    "/dev/random",
    "/dev/tty",
    "/dev/stdin",
    "/dev/stdout",
    "/dev/stderr",
    "/dev/full",
    "/dev/ptmx",
    "/dev/console",
    "/dev/fd",
    "/dev/fd/0",
    "/dev/fd/1",
    "/dev/shm",
    "/dev/pts",
    "/dev/mem",
    "/dev/kmsg",
    "/dev/stdin/",
    "/dev/null/x",
):
    n = dev
    case("dev-exists-" + n, os.path.exists, dev)
    case(
        "dev-stat-" + n,
        lambda dev=dev: (lambda s: (stat.filemode(s.st_mode), os.major(s.st_rdev), os.minor(s.st_rdev)))(os.stat(dev)),
    )
    case("dev-lstat-mode-" + n, lambda dev=dev: stat.filemode(os.lstat(dev).st_mode))
    case(
        "dev-open-r-" + n,
        lambda dev=dev: (lambda fd: (os.fstat(fd).st_mode & 0o170000, os.close(fd))[0])(os.open(dev, os.O_RDONLY)),
    )
    case("dev-open-w-" + n, lambda dev=dev: (lambda fd: os.close(fd))(os.open(dev, os.O_WRONLY)))
    case("dev-open-rw-" + n, lambda dev=dev: (lambda fd: os.close(fd))(os.open(dev, os.O_RDWR)))
    case("dev-read-" + n, lambda dev=dev: (lambda fd: len(os.read(fd, 16)))(os.open(dev, os.O_RDONLY)))
    case("dev-write-" + n, lambda dev=dev: (lambda fd: os.write(fd, b"abcd"))(os.open(dev, os.O_WRONLY)))
    case("dev-isatty-" + n, lambda dev=dev: os.isatty(os.open(dev, os.O_RDONLY)))
    case("dev-lseek-" + n, lambda dev=dev: os.lseek(os.open(dev, os.O_RDONLY), 0, 2))
    case("dev-access-" + n, lambda dev=dev: (os.access(dev, os.R_OK), os.access(dev, os.W_OK)))
    case("dev-readlink-" + n, lambda dev=dev: os.readlink(dev))
    case("dev-isdir-isfile-" + n, lambda dev=dev: (os.path.isdir(dev), os.path.isfile(dev), os.path.islink(dev)))
case("dev-listdir", lambda: sorted(os.listdir("/dev")))
case("dev-urandom-read-len", lambda: len(open("/dev/urandom", "rb").read(100)))
case("dev-urandom-read-two-differ", lambda: open("/dev/urandom", "rb").read(16) != open("/dev/urandom", "rb").read(16))
case("dev-zero-read-all-zero", lambda: open("/dev/zero", "rb").read(100) == bytes(100))
case("dev-null-write-big", lambda: open("/dev/null", "wb").write(b"x" * 100000))
case("dev-null-read-empty", lambda: open("/dev/null", "rb").read())
case(
    "dev-null-seek-tell",
    lambda: (lambda f: (f.seek(100), f.tell(), f.write(b"x"), f.tell()))(open("/dev/null", "r+b", buffering=0)),
)
case("dev-null-truncate", lambda: open("/dev/null", "r+b").truncate(0))
case("dev-null-fsync", lambda: os.fsync(os.open("/dev/null", os.O_WRONLY)))
case("dev-null-mmap", lambda: __import__("mmap").mmap(os.open("/dev/null", os.O_RDWR), 10))
case("dev-null-unlink", lambda: os.unlink("/dev/null"))
case("dev-null-chmod", lambda: os.chmod("/dev/null", 0o666))
case(
    "dev-null-stat-fstat-equal",
    lambda: (
        os.stat("/dev/null")[:3] == os.fstat(os.open("/dev/null", os.O_RDONLY))[:3]
        if False
        else os.stat("/dev/null").st_mode == os.fstat(os.open("/dev/null", os.O_RDONLY)).st_mode
    ),
)
case("dev-urandom-os-urandom", lambda: len(os.urandom(10)))
case("dev-getrandom", lambda: len(os.getrandom(10)) if hasattr(os, "getrandom") else "no")
case("dev-random-module", lambda: type(__import__("random").SystemRandom().random()).__name__)
case("dev-secrets", lambda: len(__import__("secrets").token_bytes(8)))
case("dev-zero-mmap", lambda: bytes(__import__("mmap").mmap(os.open("/dev/zero", os.O_RDWR), 4096)[:4]))
case("dev-tty-open-w", lambda: open("/dev/tty", "w").write(""))
case("dev-stdin-open-read", lambda: open("/dev/stdin", "rb").read())
case("dev-stdout-open-write", lambda: open("/dev/stdout", "w").write("[devstdout]\n"))
case("dev-stderr-open-write", lambda: open("/dev/stderr", "w").write("[devstderr]\n"))
case("dev-fd-1-open-write", lambda: open("/dev/fd/1", "w").write("[devfd1]\n"))

# /proc and /sys
for pth in (
    "/proc",
    "/proc/self",
    "/proc/self/fd",
    "/proc/self/cmdline",
    "/proc/self/exe",
    "/proc/self/cwd",
    "/proc/self/maps",
    "/proc/self/status",
    "/proc/self/environ",
    "/proc/self/stat",
    "/proc/cpuinfo",
    "/proc/meminfo",
    "/proc/version",
    "/proc/uptime",
    "/proc/loadavg",
    "/proc/sys",
    "/proc/mounts",
    "/proc/filesystems",
    "/sys",
    "/sys/devices",
    "/sys/devices/system/cpu",
    "/sys/kernel",
    "/etc",
    "/etc/passwd",
    "/etc/hosts",
    "/etc/resolv.conf",
    "/etc/os-release",
    "/etc/localtime",
    "/bin",
    "/usr",
    "/usr/bin/env",
    "/lib",
    "/var",
    "/var/tmp",
    "/run",
    "/mnt",
    "/root",
    "/home",
    "/home/pyodide",
    "/tmp",
    "/lib/python3.15",
    "/lib/python315.zip",
):
    case("path-exists-" + pth, os.path.exists, pth)
    case("path-isdir-" + pth, os.path.isdir, pth)
    case("path-stat-mode-" + pth, lambda pth=pth: stat.filemode(os.stat(pth).st_mode))
for pth in (
    "/",
    "/proc",
    "/sys",
    "/etc",
    "/home",
    "/home/pyodide",
    "/dev",
    "/lib",
    "/usr",
    "/var",
    "/run",
    "/mnt",
    "/bin",
):
    case("listdir-" + pth, lambda pth=pth: sorted(os.listdir(pth)))
case("proc-self-fd-listdir", lambda: sorted(os.listdir("/proc/self/fd")))
case("proc-self-read", lambda: open("/proc/self/status").read()[:10])
case("proc-cpuinfo-read", lambda: open("/proc/cpuinfo").read()[:10])
case("os-cpu_count", lambda: os.cpu_count() > 0)
case("os-uname", lambda: tuple(os.uname())[:2])
case("os-getuid", lambda: (os.getuid(), os.getgid(), os.geteuid(), os.getegid()))
case("os-getlogin", lambda: os.getlogin())
case("os-sched_getaffinity", lambda: len(os.sched_getaffinity(0)) > 0)
case("os-getloadavg", lambda: len(os.getloadavg()))
case("os-sysconf-pagesize", lambda: os.sysconf("SC_PAGE_SIZE"))
case(
    "os-sysconf-names",
    lambda: sorted(
        k
        for k in os.sysconf_names
        if k in ("SC_OPEN_MAX", "SC_CLK_TCK", "SC_NPROCESSORS_ONLN", "SC_PHYS_PAGES", "SC_ARG_MAX")
    ),
)
for nm in (
    "SC_OPEN_MAX",
    "SC_CLK_TCK",
    "SC_NPROCESSORS_ONLN",
    "SC_PHYS_PAGES",
    "SC_ARG_MAX",
    "SC_PAGESIZE",
    "SC_IOV_MAX",
    "SC_HOST_NAME_MAX",
):
    case("sysconf-" + nm, lambda nm=nm: os.sysconf(nm))
case("resource-nofile", lambda: __import__("resource").getrlimit(__import__("resource").RLIMIT_NOFILE))
case("resource-stack", lambda: __import__("resource").getrlimit(__import__("resource").RLIMIT_STACK))

# environment
case("env-roundtrip", lambda: (os.environ.__setitem__("DP_X", "v1"), os.environ["DP_X"], os.getenv("DP_X"))[1:])
case("env-putenv-getenv", lambda: (os.putenv("DP_Y", "v2"), os.getenv("DP_Y"), os.environ.get("DP_Y"))[1:])
case(
    "env-putenv-c-getenv",
    lambda: (os.putenv("DP_Z", "v3"), (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_Z"))[1])[1],
)
case(
    "env-environ-set-c-getenv",
    lambda: (
        os.environ.__setitem__("DP_W", "v4"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_W"))[1],
    )[1],
)
case(
    "env-unsetenv-c-getenv",
    lambda: (
        os.environ.__setitem__("DP_V", "v5"),
        os.unsetenv("DP_V"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_V"))[2],
    )[2],
)
case(
    "env-del-c-getenv",
    lambda: (
        os.environ.__setitem__("DP_U", "v6"),
        os.environ.__delitem__("DP_U"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_U"))[2],
    )[2],
)
case("env-c-setenv-os-getenv", lambda: (libc.setenv(b"DP_T", b"v7", 1), os.getenv("DP_T"), os.environ.get("DP_T"))[1:])
case(
    "env-c-setenv-no-overwrite",
    lambda: (
        libc.setenv(b"DP_S", b"a", 1),
        libc.setenv(b"DP_S", b"b", 0),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_S"))[1],
    )[2],
)
case(
    "env-c-unsetenv",
    lambda: (
        libc.setenv(b"DP_R", b"a", 1),
        libc.unsetenv(b"DP_R"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_R"))[2],
    )[2],
)
case(
    "env-c-putenv",
    lambda: (
        libc.putenv(b"DP_Q=pp"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_Q"))[1],
        os.getenv("DP_Q"),
    )[1:],
)
case("env-c-setenv-bad-name-empty", lambda: (libc.setenv(b"", b"a", 1), ctypes.get_errno())[1])
case("env-c-setenv-bad-name-eq", lambda: (libc.setenv(b"A=B", b"a", 1), ctypes.get_errno())[1])
case("env-c-unsetenv-bad-name", lambda: (libc.unsetenv(b"A=B"), ctypes.get_errno())[1])
case("env-putenv-empty-name", lambda: os.putenv("", "x"))
case("env-putenv-eq-name", lambda: os.putenv("A=B", "x"))
case("env-putenv-nul", lambda: os.putenv("A\0B", "x"))
case("env-putenv-nul-value", lambda: os.putenv("DP_A", "x\0y"))
case("env-setitem-eq", lambda: os.environ.__setitem__("A=B", "x"))
case("env-setitem-empty", lambda: os.environ.__setitem__("", "x"))
case(
    "env-empty-value",
    lambda: (
        os.environ.__setitem__("DP_E", ""),
        os.getenv("DP_E"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_E"))[1],
    )[1:],
)
case(
    "env-nonascii",
    lambda: (
        os.environ.__setitem__("DP_N", "ключ"),
        os.getenv("DP_N"),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_N"))[1],
    )[1:],
)
case("env-nonascii-key", lambda: (os.environ.__setitem__("к", "v"), os.getenv("к"))[1])
case("env-surrogate-value", lambda: (os.environ.__setitem__("DP_SG", "\udcff"), os.getenv("DP_SG"))[1])
case("env-bytes-env", lambda: (os.environb.__setitem__(b"DP_B", b"\xff"), os.environb[b"DP_B"], os.environ["DP_B"])[1:])
case("env-big-value", lambda: (os.environ.__setitem__("DP_BIG", "x" * 100000), len(os.environ["DP_BIG"]))[1])
case("env-huge-value", lambda: (os.environ.__setitem__("DP_HUGE", "x" * 10000000), len(os.environ["DP_HUGE"]))[1])
case(
    "env-many",
    lambda: (
        all(os.environ.__setitem__("DP_M%d" % i, "v") is None for i in range(2000)),
        len([k for k in os.environ if k.startswith("DP_M")]),
    )[1],
)
case("env-os-environ-has-keys", lambda: sorted(k for k in os.environ if not k.startswith("DP_")))
case(
    "env-os-environ-values-sane",
    lambda: {
        k: v
        for k, v in os.environ.items()
        if k
        in (
            "HOME",
            "PATH",
            "USER",
            "LANG",
            "PWD",
            "TZ",
            "TMPDIR",
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONUNBUFFERED",
            "TERM",
        )
    },
)
case("env-C-environ", lambda: ctypes.c_char_p.in_dll(libc, "environ").value is not None)
case(
    "env-c-environ-contains-set",
    lambda: (
        os.environ.__setitem__("DP_ENV", "zz"),
        (lambda p: any(p[i] == b"DP_ENV=zz" for i in range(300) if p[i]))(
            ctypes.cast(ctypes.c_void_p.in_dll(libc, "environ").value, ctypes.POINTER(ctypes.c_char_p))
        ),
    )[1],
)
case("env-os-getenvb", lambda: os.getenvb(b"NO_SUCH_VAR"))
case(
    "env-clear-then-c-getenv",
    lambda: (
        os.environ.__setitem__("DP_CLR", "1"),
        os.environ.clear(),
        (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"DP_CLR"))[2],
    )[2],
)
case("env-after-clear-set", lambda: (os.environ.__setitem__("DP_AC", "1"), os.getenv("DP_AC"))[1])
case(
    "env-expandvars", lambda: (os.environ.__setitem__("DP_EV", "q"), os.path.expandvars("$DP_EV/${DP_EV}/$NOPE_XYZ"))[1]
)
case("env-expanduser", lambda: os.path.expanduser("~"))
case("env-gettempdir", lambda: __import__("tempfile").gettempdir())
case("env-getcwd", lambda: os.getcwd())
case(
    "env-tzset", lambda: (os.environ.__setitem__("TZ", "UTC"), __import__("time").tzset(), __import__("time").tzname)[2]
)
case(
    "env-tz-offset",
    lambda: (os.environ.__setitem__("TZ", "EST5EDT"), __import__("time").tzset(), __import__("time").timezone)[2],
)
case(
    "env-tz-localtime",
    lambda: (os.environ.__setitem__("TZ", "EST5"), __import__("time").tzset(), __import__("time").localtime(0).tm_hour)[
        2
    ],
)
case(
    "env-tz-zoneinfo-name",
    lambda: (
        os.environ.__setitem__("TZ", "Europe/Kyiv"),
        __import__("time").tzset(),
        __import__("time").localtime(0).tm_hour,
    )[2],
)
case("env-uname-hostname", lambda: __import__("socket").gethostname())
case("env-pyvars", lambda: sorted(k for k in os.environ if k.startswith("PYTHON")))
