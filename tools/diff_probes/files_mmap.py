# type: ignore
# ruff: noqa
# fmt: off
import mmap
def new(data=b'0123456789', flags=os.O_RDWR):
    w(B + '/io', data)
    return os.open(B + '/io', flags)
case('mmap read len 0, fd RDWR', lambda: (lambda m: (m[:3], m.close()))(mmap.mmap(new(), 0, access=mmap.ACCESS_READ))[0])
case('mmap read len 10, fd RDWR', lambda: (lambda m: (m[:3], m.close()))(mmap.mmap(new(), 10, access=mmap.ACCESS_READ))[0])
case('mmap read, fd RDONLY', lambda: (lambda m: (m[:3], m.close()))(mmap.mmap(new(flags=os.O_RDONLY), 0, access=mmap.ACCESS_READ))[0])
case('mmap read, flags PROT_READ', lambda: (lambda m: (m[:3], m.close()))(mmap.mmap(new(flags=os.O_RDONLY), 0, mmap.MAP_SHARED, mmap.PROT_READ))[0])
case('mmap default (RW shared), fd RDWR', lambda: (lambda m: (m[:3], m.close()))(mmap.mmap(new(), 0))[0])
case('mmap default, fd RDONLY', lambda: mmap.mmap(new(flags=os.O_RDONLY), 0))
case('mmap write', lambda: (lambda fd: (lambda m: (m.__setitem__(slice(0, 2), b'ZZ'), m.flush(), m.close(), open(B + '/io', 'rb').read()))(mmap.mmap(fd, 10)))(new())[3])
case('mmap copy (private)', lambda: (lambda fd: (lambda m: (m.__setitem__(slice(0, 2), b'ZZ'), m.close(), open(B + '/io', 'rb').read()))(mmap.mmap(fd, 10, access=mmap.ACCESS_COPY)))(new())[2])
case('mmap offset', lambda: (lambda m: (m[:3], m.close()))(mmap.mmap(new(b'x' * 10000), 0, access=mmap.ACCESS_READ, offset=mmap.ALLOCATIONGRANULARITY))[0])
case('mmap length > file', lambda: mmap.mmap(new(), 100, access=mmap.ACCESS_READ))
case('mmap empty file len 0', lambda: mmap.mmap(new(b''), 0, access=mmap.ACCESS_READ))
case('mmap dir fd', lambda: mmap.mmap(os.open(B, 0), 0, access=mmap.ACCESS_READ))
case('mmap anon', lambda: (lambda m: (m.write(b'ab'), m[:2]))(mmap.mmap(-1, 4096))[1])
case('mmap bad fd', lambda: mmap.mmap(999, 10))
case('mmap file then read file', lambda: (lambda fd: (lambda m: (m[2:4], os.read(fd, 3)))(mmap.mmap(fd, 0, access=mmap.ACCESS_READ)))(new()))
