# type: ignore
# ruff: noqa
# fmt: off
import ctypes
L = ctypes.CDLL(None)
def has(n):
    try: getattr(L, n); return True
    except AttributeError: return False
names = ['posix_fallocate', 'fallocate', 'mknod', 'mknodat', 'mkfifo', 'mkfifoat', 'renameat2', 'renameat', 'futimens', 'utimensat', 'fdatasync', 'syncfs', 'sync', 'fchmodat', 'fchownat', 'lchown', 'faccessat', 'eaccess', 'euidaccess', 'statfs', 'fstatfs', 'fstatvfs', 'readlinkat', 'symlinkat', 'linkat', 'unlinkat', 'mkdirat', 'openat', 'fstatat', 'getdents64', 'getdents', 'preadv', 'pwritev', 'preadv2', 'pwritev2', 'dup3', 'pipe2', 'umask', 'chroot', 'copy_file_range', 'sendfile', 'splice', 'truncate', 'ftruncate', 'lseek64', 'posix_fadvise', 'readahead', 'syncfs', 'fsync', 'flock', 'lockf', 'getcwd', 'realpath', 'open_by_handle_at', 'name_to_handle_at', 'utimes', 'futimes', 'lutimes', 'utime', 'fchdir', 'chdir', 'ioctl', 'fcntl', 'memfd_create', 'timerfd_create', 'inotify_init1', 'setxattr', 'getxattr', 'listxattr', 'statx', 'fchmod', 'chmod', 'close_range', 'creat', 'ftw', 'nftw', 'glob', 'fnmatch', 'mkstemp', 'mkdtemp', 'tmpfile', 'fopen', 'opendir', 'readdir', 'rewinddir', 'seekdir', 'telldir', 'scandir', 'alphasort', 'remove', 'rename', 'rmdir', 'unlink', 'symlink', 'link', 'readlink', 'access', 'stat', 'lstat', 'fstat', 'ttyname', 'isatty']
case('ctypes names present', lambda: ' '.join('%s=%d' % (n, has(n)) for n in names))
