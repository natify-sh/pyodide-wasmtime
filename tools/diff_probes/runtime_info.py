# ruff: noqa
# type: ignore
# RUNTIME INFO: sys/os/platform/resource/locale/environ values that must be deterministic.
import errno
import os
import sys


N = 0


def c(cid, f):
    global N
    N += 1
    if N <= globals().get("SKIP", 0):
        return
    print(">> " + cid, flush=True)
    try:
        r = f()
        print(cid, "|", r, flush=True)
    except OSError as e:
        print(cid, "| ERR", errno.errorcode.get(e.errno, e.errno), flush=True)
    except BaseException as e:
        print(cid, "| EXC", type(e).__name__, str(e)[:80], flush=True)


ei = sys._emscripten_info
c("emscripten_info keys", lambda: sorted(ei._fields))
c("emscripten_version", lambda: ei.emscripten_version)
c("pthreads", lambda: ei.pthreads)
c("shared_memory", lambda: ei.shared_memory)
for n in [
    "platform",
    "byteorder",
    "maxsize",
    "maxunicode",
    "hexversion",
    "api_version",
    "abiflags",
    "float_repr_style",
    "pycache_prefix",
    "dont_write_bytecode",
    "getfilesystemencoding()",
    "getfilesystemencodeerrors()",
    "getdefaultencoding()",
    "stdout.encoding",
    "stdout.errors",
    "stderr.encoding",
    "stderr.errors",
    "stdin.encoding",
    "stdin.errors",
    "stdout.isatty()",
    "stderr.isatty()",
    "stdout.line_buffering",
    "stderr.line_buffering",
    "stdout.fileno()",
    "stdin.fileno()",
    "implementation.name",
    "implementation.cache_tag",
    "implementation.version",
    "implementation._multiarch",
    "flags",
    "float_info",
    "int_info",
    "hash_info",
    "thread_info",
    "version",
    "version_info",
    "prefix",
    "exec_prefix",
    "base_prefix",
    "executable",
    "argv",
    "orig_argv",
    "warnoptions",
    "_xoptions",
    "path",
    "meta_path",
    "path_hooks",
    "builtin_module_names",
    "stdlib_module_names.__len__()",
    "getrecursionlimit()",
    "getswitchinterval()",
    "is_finalizing()",
    "getsizeof(1)",
    "get_int_max_str_digits()",
    "_git",
    "_framework",
    "platlibdir",
    "unraisablehook.__name__",
    "excepthook.__name__",
    "displayhook.__name__",
    "_is_gil_enabled()",
    "_stdlib_dir",
    "flags.dev_mode",
    "flags.utf8_mode",
]:
    c("sys." + n, lambda: eval("sys." + n))
import platform

for n in [
    "machine",
    "node",
    "platform",
    "processor",
    "python_implementation",
    "python_version",
    "python_build",
    "python_compiler",
    "release",
    "system",
    "version",
    "uname",
    "architecture",
    "libc_ver",
    "mac_ver",
    "win32_ver",
    "freedesktop_os_release",
    "python_branch",
    "python_revision",
    "java_ver",
]:
    c("platform." + n, lambda: getattr(platform, n)() if n != "platform" else platform.platform())
c("platform.platform terse", lambda: platform.platform(terse=True))
c("platform.platform aliased", lambda: platform.platform(aliased=True))
c("os.name", lambda: os.name)
c(
    "os.sep etc",
    lambda: (os.sep, os.altsep, os.pathsep, os.curdir, os.pardir, os.extsep, os.linesep, os.devnull, os.defpath),
)
c("os.uname", lambda: tuple(os.uname()))
c("os.uname fields", lambda: os.uname()._fields)
for n in [
    "getpid",
    "getppid",
    "getuid",
    "geteuid",
    "getgid",
    "getegid",
    "getgroups",
    "getlogin",
    "getpgrp",
    "getsid",
    "getpgid",
    "getresuid",
    "getresgid",
    "getpriority",
    "getloadavg",
    "cpu_count",
    "process_cpu_count",
    "getcwd",
    "getcwdb",
    "umask",
    "ctermid",
    "get_terminal_size",
    "get_blocking",
    "times",
    "uname",
    "getrandom",
    "sched_getaffinity",
    "sched_getscheduler",
    "sched_get_priority_max",
    "sched_get_priority_min",
    "getenv",
    "getxattr",
    "listxattr",
    "fork",
    "forkpty",
    "wait",
    "setsid",
    "setpgrp",
    "nice",
    "tcgetpgrp",
    "ttyname",
    "isatty",
    "openpty",
    "pipe",
    "pipe2",
    "login_tty",
    "posix_spawn",
    "execv",
    "system",
    "popen",
    "spawnv",
    "register_at_fork",
    "sysconf",
    "confstr",
    "pathconf",
    "fpathconf",
    "getgrouplist",
    "initgroups",
    "setuid",
    "setgid",
    "seteuid",
    "setegid",
    "setgroups",
    "setreuid",
    "setregid",
    "setresuid",
    "setresgid",
    "chroot",
    "sync",
    "lockf",
    "posix_fadvise",
    "posix_fallocate",
    "copy_file_range",
    "sendfile",
    "splice",
    "eventfd",
    "memfd_create",
    "pidfd_open",
    "waitid",
    "wait3",
    "wait4",
    "waitpid",
    "killpg",
    "plock",
    "mkfifo",
    "mknod",
    "major",
    "minor",
    "makedev",
    "unshare",
    "setns",
    "timerfd_create",
    "sched_yield",
    "sched_setaffinity",
    "sched_param",
    "sched_setparam",
    "sched_rr_get_interval",
]:
    c("os.has " + n, lambda: hasattr(os, n))
c("getpid value", lambda: os.getpid())
c("getppid", lambda: os.getppid())
c("getuid", lambda: (os.getuid(), os.geteuid(), os.getgid(), os.getegid()))
c("getgroups", lambda: os.getgroups())
c("getlogin", lambda: os.getlogin())
c("getpgrp", lambda: os.getpgrp())
c("getsid 0", lambda: os.getsid(0))
c("getpgid 0", lambda: os.getpgid(0))
c("getresuid", lambda: os.getresuid())
c("getpriority", lambda: os.getpriority(os.PRIO_PROCESS, 0))
c("getloadavg", lambda: os.getloadavg())
c("cpu_count", lambda: os.cpu_count())
c("process_cpu_count", lambda: os.process_cpu_count() if hasattr(os, "process_cpu_count") else "n/a")
c("sched_getaffinity", lambda: os.sched_getaffinity(0))
c("umask", lambda: (os.umask(0o22), os.umask(0o22)))
c("ctermid", lambda: os.ctermid())
c("get_terminal_size", lambda: os.get_terminal_size())
c("get_terminal_size(0)", lambda: os.get_terminal_size(0))
c("isatty 0,1,2", lambda: (os.isatty(0), os.isatty(1), os.isatty(2)))
c("ttyname 0", lambda: os.ttyname(0))
c("get_blocking 0,1,2", lambda: (os.get_blocking(0), os.get_blocking(1), os.get_blocking(2)))
c("setuid 0", lambda: os.setuid(0))
c("setuid 1", lambda: os.setuid(1))
c("setgid 1", lambda: os.setgid(1))
c("setsid", lambda: os.setsid())
c("setpgid 0 0", lambda: os.setpgid(0, 0))
c("nice 0", lambda: os.nice(0))
c("nice 5", lambda: os.nice(5))
c("setpriority", lambda: os.setpriority(os.PRIO_PROCESS, 0, 0))
c("fork", lambda: os.fork())
c("wait", lambda: os.wait())
c("waitpid", lambda: os.waitpid(-1, os.WNOHANG))
c("system", lambda: os.system("true"))
c("popen", lambda: os.popen("true").read())
c("posix_spawn", lambda: os.posix_spawn("/bin/true", ["true"], {}))
c("chroot", lambda: os.chroot("/"))
c("sync", lambda: os.sync())
c("sched_yield", lambda: os.sched_yield())
c("getrandom sizes", lambda: [len(os.getrandom(n)) for n in (0, 1, 16, 255, 256, 257, 1000, 100000)])
c("getrandom flags", lambda: len(os.getrandom(4, os.GRND_NONBLOCK)))
c("getrandom neg", lambda: os.getrandom(-1))
c("getrandom huge", lambda: len(os.getrandom(2**20)))
c("getrandom bad flags", lambda: os.getrandom(4, 1 << 20))
c("urandom sizes", lambda: [len(os.urandom(n)) for n in (0, 1, 16, 255, 256, 257, 1000, 100000, 2**20)])
c("urandom neg", lambda: os.urandom(-1))
c("urandom str", lambda: os.urandom("1"))
c("urandom differs", lambda: os.urandom(16) != os.urandom(16))
import random
import secrets

c("random seeded differ", lambda: random.Random().random() != random.Random().random())
c("secrets", lambda: len(secrets.token_bytes(32)))
c("SystemRandom", lambda: 0 <= random.SystemRandom().random() < 1)
for n in [
    "SC_PAGESIZE",
    "SC_PAGE_SIZE",
    "SC_NPROCESSORS_ONLN",
    "SC_NPROCESSORS_CONF",
    "SC_CLK_TCK",
    "SC_OPEN_MAX",
    "SC_ARG_MAX",
    "SC_PHYS_PAGES",
    "SC_AVPHYS_PAGES",
    "SC_CHILD_MAX",
    "SC_NGROUPS_MAX",
    "SC_HOST_NAME_MAX",
    "SC_LOGIN_NAME_MAX",
    "SC_LINE_MAX",
    "SC_SEM_NSEMS_MAX",
    "SC_IOV_MAX",
    "SC_MONOTONIC_CLOCK",
    "SC_THREADS",
    "SC_SYMLOOP_MAX",
    "SC_TTY_NAME_MAX",
    "SC_TZNAME_MAX",
    "SC_VERSION",
    "SC_XOPEN_VERSION",
    "SC_MINSIGSTKSZ",
    "SC_SIGQUEUE_MAX",
    "SC_RTSIG_MAX",
    "SC_DELAYTIMER_MAX",
    "SC_TIMER_MAX",
    "SC_AIO_MAX",
    "SC_MQ_OPEN_MAX",
    "SC_SEM_VALUE_MAX",
    "SC_RE_DUP_MAX",
    "SC_BC_BASE_MAX",
    "SC_COLL_WEIGHTS_MAX",
    "SC_EXPR_NEST_MAX",
    "SC_ATEXIT_MAX",
    "SC_GETPW_R_SIZE_MAX",
    "SC_GETGR_R_SIZE_MAX",
    "SC_2_VERSION",
    "SC_CPUTIME",
    "SC_THREAD_CPUTIME",
    "SC_SHARED_MEMORY_OBJECTS",
    "SC_FSYNC",
    "SC_MAPPED_FILES",
    "SC_SPAWN",
    "SC_REGEXP",
    "SC_SHELL",
]:
    c("sysconf " + n, lambda: os.sysconf(getattr(os, n)) if hasattr(os, n) else "no-name")
c("sysconf_names keys", lambda: sorted(os.sysconf_names))
for n in sorted(os.sysconf_names):
    c("sysconf name " + n, lambda: os.sysconf(n))
c("sysconf bad", lambda: os.sysconf(99999))
c("sysconf bad name", lambda: os.sysconf("SC_NOPE"))
c("sysconf -1", lambda: os.sysconf(-1))
c("confstr_names", lambda: sorted(os.confstr_names))
for n in sorted(os.confstr_names):
    c("confstr " + n, lambda: os.confstr(n))
c("pathconf_names", lambda: sorted(os.pathconf_names))
for n in sorted(os.pathconf_names):
    c("pathconf / " + n, lambda: os.pathconf("/", n))
    c("pathconf /tmp " + n, lambda: os.pathconf("/tmp", n))
try:
    import resource
except ImportError as e:
    print("import resource | ImportError", str(e).splitlines()[0][:60], flush=True)
    resource = type("R", (), {})()

for n in [
    "RLIMIT_CPU",
    "RLIMIT_FSIZE",
    "RLIMIT_DATA",
    "RLIMIT_STACK",
    "RLIMIT_CORE",
    "RLIMIT_RSS",
    "RLIMIT_NPROC",
    "RLIMIT_NOFILE",
    "RLIMIT_MEMLOCK",
    "RLIMIT_AS",
    "RLIMIT_MSGQUEUE",
    "RLIMIT_NICE",
    "RLIMIT_RTPRIO",
    "RLIMIT_RTTIME",
    "RLIMIT_SIGPENDING",
    "RLIMIT_OFILE",
]:
    c("getrlimit " + n, lambda: resource.getrlimit(getattr(resource, n)) if hasattr(resource, n) else "no-name")
c("getrlimit bad", lambda: resource.getrlimit(999))
c("getrlimit -1", lambda: resource.getrlimit(-1))
c(
    "setrlimit NOFILE same",
    lambda: resource.setrlimit(resource.RLIMIT_NOFILE, resource.getrlimit(resource.RLIMIT_NOFILE)),
)
c("setrlimit CORE 0", lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
c("setrlimit bad", lambda: resource.setrlimit(resource.RLIMIT_NOFILE, (10, 5)))
c("prlimit", lambda: resource.prlimit(0, resource.RLIMIT_NOFILE) if hasattr(resource, "prlimit") else "n/a")
c("getpagesize", lambda: resource.getpagesize())
c("RLIM_INFINITY", lambda: resource.RLIM_INFINITY)
c("getrusage fields", lambda: resource.getrusage(resource.RUSAGE_SELF)._fields)
c("getrusage types", lambda: [type(x).__name__ for x in resource.getrusage(resource.RUSAGE_SELF)])
c("getrusage self nonneg", lambda: all(x >= 0 for x in resource.getrusage(resource.RUSAGE_SELF)))
c("getrusage maxrss>0", lambda: resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 0)
c("getrusage children", lambda: tuple(resource.getrusage(resource.RUSAGE_CHILDREN)))
c("getrusage thread", lambda: resource.getrusage(resource.RUSAGE_THREAD).ru_utime >= 0)
c("getrusage bad", lambda: resource.getrusage(99))
c("getrusage -2", lambda: resource.getrusage(-2))
c("RUSAGE consts", lambda: (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN, getattr(resource, "RUSAGE_THREAD", None)))
for n in [
    "HOME",
    "USER",
    "LOGNAME",
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "TERM",
    "SHELL",
    "TMPDIR",
    "HOSTNAME",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONUTF8",
    "PYTHONCOERCECLOCALE",
    "PYTHONSAFEPATH",
]:
    c("environ " + n, lambda: os.environ.get(n))
c("environ keys sorted", lambda: sorted(k for k in os.environ if k not in ("TZ", "PWD", "_")))
c(
    "environ set/get",
    lambda: (os.environ.__setitem__("DPK", "v"), os.environ["DPK"], os.getenv("DPK"), os.environ.pop("DPK"))[1:3],
)
c(
    "putenv visible to libc",
    lambda: (os.putenv("DPK2", "x"), __import__("ctypes").CDLL(None).getenv(b"DPK2"))[1] is not None,
)
c("environb", lambda: type(os.environb).__name__)
c("environ bad key", lambda: os.environ.__setitem__("A=B", "x"))
c("environ nul value", lambda: os.environ.__setitem__("A", "x\0y"))
c("unsetenv missing", lambda: os.unsetenv("DPK_NOPE"))
c("putenv empty name", lambda: os.putenv("", "x"))
c("getenv surrogate", lambda: os.putenv("DPK3", "\udcff") or os.environ.get("DPK3"))
c(
    "environ non-ascii",
    lambda: (os.environ.__setitem__("DPK4", "é中"), __import__("ctypes").CDLL(None).getenv(b"DPK4") is not None)[1],
)
import locale

c("locale.getlocale", lambda: locale.getlocale())
c("locale.getencoding", lambda: locale.getencoding())
c("locale.getpreferredencoding", lambda: locale.getpreferredencoding(False))
c(
    "locale.setlocale query",
    lambda: [
        locale.setlocale(x)
        for x in (
            locale.LC_ALL,
            locale.LC_CTYPE,
            locale.LC_NUMERIC,
            locale.LC_TIME,
            locale.LC_COLLATE,
            locale.LC_MONETARY,
            locale.LC_MESSAGES,
        )
    ],
)
c("locale.setlocale C", lambda: locale.setlocale(locale.LC_ALL, "C"))
c("locale.setlocale ''", lambda: locale.setlocale(locale.LC_ALL, ""))
c("locale.setlocale C.UTF-8", lambda: locale.setlocale(locale.LC_ALL, "C.UTF-8"))
c("locale.setlocale en_US.UTF-8", lambda: locale.setlocale(locale.LC_ALL, "en_US.UTF-8"))
c("locale.setlocale bad", lambda: locale.setlocale(locale.LC_ALL, "xx_YY"))
c("locale.localeconv", lambda: sorted(locale.localeconv().items()))
c("locale.nl_langinfo CODESET", lambda: locale.nl_langinfo(locale.CODESET))
c("locale.nl_langinfo DAY_1", lambda: locale.nl_langinfo(locale.DAY_1))
c("locale.nl_langinfo RADIXCHAR", lambda: locale.nl_langinfo(locale.RADIXCHAR))
c(
    "locale.strcoll",
    lambda: (locale.strcoll("a", "b"), locale.strcoll("b", "a"), locale.strcoll("a", "a"), locale.strcoll("a", "B")),
)
c("locale.strxfrm", lambda: locale.strxfrm("abc"))
c("locale.format_string", lambda: locale.format_string("%d", 1234567, grouping=True))
c("locale.currency", lambda: locale.currency(1234.5))
c("locale.normalize", lambda: locale.normalize("en_US"))
c("str.upper non-ascii", lambda: "éßı".upper())
c("time.strftime locale month", lambda: __import__("time").strftime("%B %A", (2020, 1, 1, 0, 0, 0, 2, 1, 0)))
c("open default encoding", lambda: (open("/dev/null").encoding, open("/dev/null").errors))
c("print non-ascii", lambda: (print("é中\U0001f600", flush=True), 1)[1])
c("print surrogate", lambda: (print("\udcff", flush=True), 1)[1])
c("stdout types", lambda: (type(sys.stdout).__name__, type(sys.stdout.buffer).__name__))
import ctypes

C = ctypes.CDLL(None)
c("progname call", lambda: (lambda b: (C._emscripten_get_progname(b, 64), b.value)[1])(ctypes.create_string_buffer(64)))
c(
    "progname call small",
    lambda: (lambda b: (C._emscripten_get_progname(b, 3), b.raw[:4])[1])(ctypes.create_string_buffer(64)),
)
c(
    "progname call 1",
    lambda: (lambda b: (C._emscripten_get_progname(b, 1), b.raw[:2])[1])(ctypes.create_string_buffer(b"zz", 64)),
)
c(
    "progname call 0",
    lambda: (lambda b: (C._emscripten_get_progname(b, 0), b.raw[:2])[1])(ctypes.create_string_buffer(b"zz", 64)),
)


def hm():
    f = C.emscripten_get_heap_max
    f.restype = ctypes.c_size_t
    return f()


c("emscripten_get_heap_max", hm)


def rh(n):
    f = C.emscripten_resize_heap
    f.argtypes = [ctypes.c_size_t]
    return f(n)


c("resize_heap 0xFFFF0000", lambda: rh(0xFFFF0000))
c("resize_heap 0xFFFF0001", lambda: rh(0xFFFF0001))
c("resize_heap 0xFFFFFFFF", lambda: rh(0xFFFFFFFF))
c("resize_heap 1", lambda: rh(1))
c("resize_heap 0", lambda: rh(0))


def dbl(n):
    f = getattr(C, n)
    f.restype = ctypes.c_double
    return f()


c("emscripten_get_now>0", lambda: dbl("emscripten_get_now") > 0)
c("emscripten_date_now whole", lambda: dbl("emscripten_date_now") % 1 == 0)
c("emscripten_get_now_res", lambda: dbl("emscripten_get_now_res"))
c("emscripten_get_now monotonic", lambda: dbl("emscripten_get_now") <= dbl("emscripten_get_now"))
c("emscripten_get_sbrk_ptr", lambda: C.emscripten_get_sbrk_ptr() > 0)
c("emscripten_stack_get_free", lambda: C.emscripten_stack_get_free() > 0)
c("getpagesize libc", lambda: C.getpagesize())
c("sysconf libc pagesize", lambda: C.sysconf(30))
c("gethostname", lambda: (lambda b: (C.gethostname(b, 64), b.value)[1])(ctypes.create_string_buffer(64)))
c("getdomainname", lambda: (lambda b: (C.getdomainname(b, 64), b.value)[1])(ctypes.create_string_buffer(64)))
c("socket.gethostname", lambda: __import__("socket").gethostname())
c("getpwuid", lambda: tuple(__import__("pwd").getpwuid(os.getuid())))
c("getpwnam root", lambda: tuple(__import__("pwd").getpwnam("root")))
c("getgrgid", lambda: tuple(__import__("grp").getgrgid(os.getgid())))
c("getpass.getuser", lambda: __import__("getpass").getuser())
c("expanduser", lambda: os.path.expanduser("~"))
c("tempfile.gettempdir", lambda: __import__("tempfile").gettempdir())
c("sys.path[0:3]", lambda: sys.path[:3])
c("site.getsitepackages", lambda: __import__("site").getsitepackages())
c("site.ENABLE_USER_SITE", lambda: __import__("site").ENABLE_USER_SITE)
c(
    "sysconfig vars",
    lambda: [
        __import__("sysconfig").get_config_var(k)
        for k in (
            "SOABI",
            "EXT_SUFFIX",
            "MULTIARCH",
            "HOST_GNU_TYPE",
            "Py_ENABLE_SHARED",
            "prefix",
            "LIBDIR",
            "MACHDEP",
            "ABIFLAGS",
            "Py_GIL_DISABLED",
            "SIZEOF_LONG",
            "SIZEOF_VOID_P",
            "SIZEOF_WCHAR_T",
            "SHLIB_SUFFIX",
        )
    ],
)
c("sysconfig platform", lambda: __import__("sysconfig").get_platform())
c("sysconfig paths", lambda: sorted(__import__("sysconfig").get_paths().items()))
c("EXTENSION_SUFFIXES", lambda: __import__("importlib.machinery").machinery.EXTENSION_SUFFIXES)
c("MAGIC_NUMBER", lambda: __import__("importlib.util").util.MAGIC_NUMBER)
c(
    "find_spec sample",
    lambda: [
        m
        for m in (
            "_sqlite3",
            "pwd",
            "grp",
            "resource",
            "fcntl",
            "termios",
            "_posixsubprocess",
            "select",
            "_socket",
            "_ssl",
            "_ctypes",
            "zlib",
            "_hashlib",
            "_lzma",
            "_bz2",
            "_decimal",
            "unicodedata",
            "mmap",
            "readline",
            "_curses",
            "_tkinter",
            "syslog",
            "_multiprocessing",
            "_posixshmem",
            "_uuid",
            "_zoneinfo",
            "_asyncio",
            "_pickle",
            "_json",
            "array",
            "math",
            "cmath",
            "binascii",
        )
        if __import__("importlib.util").util.find_spec(m)
    ],
)
c("threading.active_count", lambda: __import__("threading").active_count())
c("threading.stack_size", lambda: __import__("threading").stack_size())
c("threading.Thread.start", lambda: __import__("threading").Thread(target=lambda: None).start())
c("multiprocessing.cpu_count", lambda: __import__("multiprocessing").cpu_count())
c("subprocess.run", lambda: __import__("subprocess").run(["true"]))
c("asyncio.run", lambda: __import__("asyncio").run(__import__("asyncio").sleep(0, "ok")))
c("selectors default", lambda: type(__import__("selectors").DefaultSelector()).__name__)
c("shutil.get_terminal_size", lambda: tuple(__import__("shutil").get_terminal_size()))
c("shutil.disk_usage /", lambda: [type(x).__name__ for x in __import__("shutil").disk_usage("/")])
c("shutil.which sh", lambda: __import__("shutil").which("sh"))
c("os.get_exec_path", lambda: os.get_exec_path())
c("os.fsencode surrogate", lambda: os.fsencode("\udcff"))
c("os.fsdecode high", lambda: os.fsdecode(b"\xff\xfe"))
c("os.supports_bytes_environ", lambda: os.supports_bytes_environ)
c("os.supports_fd names", lambda: sorted(f.__name__ for f in os.supports_fd))
c("os.supports_dir_fd names", lambda: sorted(f.__name__ for f in os.supports_dir_fd))
c("os.supports_follow_symlinks names", lambda: sorted(f.__name__ for f in os.supports_follow_symlinks))
c("os.supports_effective_ids names", lambda: sorted(f.__name__ for f in os.supports_effective_ids))
c("os dir names", lambda: sorted(n for n in dir(os) if not n.startswith("_")))
c("signal dir names", lambda: sorted(n for n in dir(__import__("signal")) if not n.startswith("_")))
c("time dir names", lambda: sorted(n for n in dir(__import__("time")) if not n.startswith("_")))
c("select dir names", lambda: sorted(n for n in dir(__import__("select")) if not n.startswith("_")))
c("errno consts", lambda: sorted((n, getattr(errno, n)) for n in dir(errno) if n.startswith("E")))
c("os.strerror 0..140", lambda: [os.strerror(i) for i in range(0, 140)])
c("os.strerror bad", lambda: os.strerror(99999))
