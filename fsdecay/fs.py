#!/usr/bin/env python

from collections import defaultdict
from errno import ENOENT
from stat import S_IFDIR, S_IFLNK, S_IFREG
from sys import argv, exit
from time import time

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn


def with_ttl(f):
    def check_ttl(*args, **kwargs):
        cls = args[0]
        path = args[1]
        if cls.is_expired(path):
            cls.rmdir(path)
            raise FuseOSError(ENOENT)
        else:
            return f(*args, **kwargs)
    return check_ttl


class Memory(LoggingMixIn, Operations):
    def __init__(self, default_ttl=30):
        self.files = {}
        self.data = defaultdict(str)
        self.fd = 0
        now = time()
        self.files['/'] = dict(
            st_mode=(S_IFDIR | 0755), st_ctime=now,
            st_mtime=now, st_atime=now, st_nlink=2
        )
        self.default_ttl = default_ttl

    def check_ttl(self, path):
        try:
            ctime = self.files[path]['st_ctime']
            ttl = self.files[path]['ttl']
        except KeyError:
            return False
        if ctime + ttl < time():
            print "{0} is expired".format(path)
            return True
        else:
            return False

    def is_expired(self, path):
        for sub_path in [p for p in self.files.keys() if p.startswith(path)]:
            if self.check_ttl(sub_path):
                self.files.pop(sub_path)
        if self.check_ttl(path):
            return True
        else:
            return False

    @with_ttl
    def chmod(self, path, mode):
        self.files[path]['st_mode'] &= 0770000
        self.files[path]['st_mode'] |= mode
        return 0

    @with_ttl
    def chown(self, path, uid, gid):
        self.files[path]['st_uid'] = uid
        self.files[path]['st_gid'] = gid

    @with_ttl
    def create(self, path, mode, fi=None):
        now = time()
        self.files[path] = dict(
            st_mode=(S_IFREG | mode), st_nlink=1,
            st_size=0, st_ctime=now, st_mtime=now, st_atime=now,
            ttl=self.default_ttl
        )
        self.fd += 1
        return self.fd

    @with_ttl
    def getattr(self, path, fh=None):
        if path not in self.files:
            raise FuseOSError(ENOENT)
        st = self.files[path]
        return st

    @with_ttl
    def getxattr(self, path, name, position=0):
        try:
            attrs = self.files[path].get('attrs', {})
        except KeyError:
            raise FuseOSError(ENOENT)
        try:
            return attrs[name]
        except KeyError:
            return ''

    @with_ttl
    def listxattr(self, path):
        attrs = self.files[path].get('attrs', {})
        return attrs.keys()

    @with_ttl
    def mkdir(self, path, mode):
        self.files[path] = dict(
            st_mode=(S_IFDIR | mode), st_nlink=2,
            st_size=0, st_ctime=time(), st_mtime=time(), st_atime=time(),
            ttl=self.default_ttl
        )
        self.files['/']['st_nlink'] += 1

    @with_ttl
    def open(self, path, flags):
        self.fd += 1
        return self.fd

    @with_ttl
    def read(self, path, size, offset, fh):
        return self.data[path][offset:offset + size]

    def _filter_readdir(self, x, path):
        offset = 1 if path != "/" else 0
        return x != path and x.startswith(path) and x.count("/") <= path.count("/") + offset

    @with_ttl
    def readdir(self, path, fh):
        offset = 1 if len(path) == 1 else len(path) + 1
        items_in_dir = ['.', '..'] + [x[offset:] for x in self.files if self._filter_readdir(x, path)]
        return items_in_dir

    @with_ttl
    def readlink(self, path):
        return self.data[path]

    @with_ttl
    def removexattr(self, path, name):
        attrs = self.files[path].get('attrs', {})
        try:
            del attrs[name]
        except KeyError:
            pass

    def rename(self, old, new):
        self.files[new] = self.files.pop(old)

    @with_ttl
    def rmdir(self, path):
        self.files.pop(path)
        self.files['/']['st_nlink'] -= 1

    @with_ttl
    def setxattr(self, path, name, value, options, position=0):
        try:
            attrs = self.files[path].setdefault('attrs', {})
        except KeyError:
            raise FuseOSError(ENOENT)
        attrs[name] = value

    @with_ttl
    def statfs(self, path):
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def symlink(self, target, source):
        self.files[target] = dict(
            st_mode=(S_IFLNK | 0777), st_nlink=1,
            st_size=len(source)
        )
        self.data[target] = source

    @with_ttl
    def truncate(self, path, length, fh=None):
        self.data[path] = self.data[path][:length]
        self.files[path]['st_size'] = length

    @with_ttl
    def unlink(self, path):
        self.files.pop(path)

    @with_ttl
    def utimens(self, path, times=None):
        now = time()
        atime, mtime = times if times else (now, now)
        self.files[path]['st_atime'] = atime
        self.files[path]['st_mtime'] = mtime

    @with_ttl
    def write(self, path, data, offset, fh):
        self.data[path] = self.data[path][:offset] + data
        self.files[path]['st_size'] = len(self.data[path])
        return len(data)


if __name__ == "__main__":
    if len(argv) != 2:
        print 'usage: %s <mountpoint>' % argv[0]
        exit(1)
    fuse = FUSE(Memory(), argv[1], foreground=True)
