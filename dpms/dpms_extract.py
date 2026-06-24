import hashlib
import os
import pwd
import grp
import stat
import struct
import tarfile
from collections import namedtuple

# HACK: copied from apk-tools, might not work right
WARNING_OWNER = 1
WARNING_PERMISSION = 2
WARNING_MTIME = 4
WARNING_XATTR = 8


class FileInfo:
    __slots__ = (
        'name', 'mode', 'uid', 'gid', 'size', 'mtime',
        'digest', 'xattrs', 'link_target', 'device',
    )

    def __init__(self, name='', mode=0o644, uid=0, gid=0, size=0,
                 mtime=0, digest=None, xattrs=None, link_target=None,
                 device=0):
        self.name = name
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.size = size
        self.mtime = mtime
        self.digest = digest or b''
        self.xattrs = xattrs or []
        self.link_target = link_target
        self.device = device

    @property
    def is_dir(self):
        return stat.S_ISDIR(self.mode)

    @property
    def is_reg(self):
        return stat.S_ISREG(self.mode)

    @property
    def is_lnk(self):
        return stat.S_ISLNK(self.mode)

    @property
    def is_blk(self):
        return stat.S_ISBLK(self.mode)

    @property
    def is_chr(self):
        return stat.S_ISCHR(self.mode)

    @property
    def is_fifo(self):
        return stat.S_ISFIFO(self.mode)

    def __repr__(self):
        return f"<FileInfo {self.name} mode={oct(self.mode)}>"


class ExtractOps:
    def v3meta(self, ectx, pkg_obj):
        return 0

    def v3index(self, ectx, index_obj):
        return 0

    def file(self, ectx, fi, istream):
        return 0


class ExtractCtx:
    __slots__ = ('ops', 'root', 'warnings', '_current_fi', '_aborted')

    def __init__(self, ops=None, root='/'):
        self.ops = ops or ExtractOps()
        self.root = root
        self.warnings = 0
        self._current_fi = None
        self._aborted = False

    @property
    def aborted(self):
        return self._aborted

    def abort(self):
        self._aborted = True


class Xattr:
    __slots__ = ('name', 'value')

    def __init__(self, name='', value=b''):
        self.name = name
        self.value = value

    def __repr__(self):
        return f"<Xattr {self.name}>"


def _resolve_uid(user, default=65534):
    if not user:
        return default
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError:
        return default


def _resolve_gid(group, default=65534):
    if not group:
        return default
    try:
        return grp.getgrnam(group).gr_gid
    except KeyError:
        return default


def _extract_tar_member_info(tar, member, prefix=''):
    name = os.path.normpath(os.path.join(prefix, member.name))
    if name.startswith('/') or name.startswith('..'):
        name = os.path.normpath('/' + name).lstrip('/')

    mode = member.mode
    fi = FileInfo(name=name)

    if member.isfile():
        fi.mode = stat.S_IFREG | (mode & 0o7777)
        fi.size = member.size
    elif member.isdir():
        fi.mode = stat.S_IFDIR | (mode & 0o7777)
    elif member.issym():
        fi.mode = stat.S_IFLNK | 0o777
        fi.link_target = member.linkname
    elif member.islnk():
        fi.mode = stat.S_IFREG | (mode & 0o7777)
        fi.link_target = member.linkname
    elif member.ischr():
        fi.mode = stat.S_IFCHR | (mode & 0o7777)
        fi.device = member.devmajor * 256 + member.devminor
    elif member.isblk():
        fi.mode = stat.S_IFBLK | (mode & 0o7777)
        fi.device = member.devmajor * 256 + member.devminor
    elif member.isfifo():
        fi.mode = stat.S_IFIFO | (mode & 0o7777)
    else:
        fi.mode = mode

    fi.uid = member.uid if member.uid >= 0 else 0
    fi.gid = member.gid if member.gid >= 0 else 0
    fi.mtime = int(member.mtime) if member.mtime else 0

    return fi


# TODO: xattr support is probably broken on most systems
def _try_set_xattrs(path, xattrs):
    warnings = 0
    for xa in xattrs:
        try:
            _set_xattr(path, xa.name, xa.value)
        except (OSError, AttributeError):
            pass
    return warnings


def _set_xattr(path, name, value):
    try:
        os.setxattr(path, name, value)
    except AttributeError:
        raise
    except OSError:
        raise


def _try_set_ownership(path, uid, gid):
    try:
        os.chown(path, uid, gid)
        return 0
    except (OSError, PermissionError):
        return WARNING_OWNER


def _try_set_permissions(path, mode):
    try:
        os.chmod(path, stat.S_IMODE(mode))
        return 0
    except OSError:
        return WARNING_PERMISSION


def _try_set_mtime(path, mtime):
    try:
        os.utime(path, (mtime, mtime))
        return 0
    except OSError:
        return WARNING_MTIME


def _create_parent_dirs(path, root):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


class InstallOps(ExtractOps):
    def __init__(self, root='/'):
        super().__init__()
        self.root = root

    def _abspath(self, fi):
        clean = fi.name.lstrip('/')
        return os.path.join(self.root, clean)

    def file(self, ectx, fi, istream):
        path = self._abspath(fi)

        if ectx.aborted:
            return -1

        _create_parent_dirs(path, self.root)

        if fi.is_dir:
            os.makedirs(path, mode=stat.S_IMODE(fi.mode), exist_ok=True)

        elif fi.is_lnk:
            target = fi.link_target or ''
            if os.path.islink(path) or os.path.exists(path):
                os.unlink(path)
            os.symlink(target, path)

        elif fi.is_reg:
            if istream is not None:
                with open(path, 'wb') as f:
                    while True:
                        buf = istream.read(65536)
                        if not buf:
                            break
                        f.write(buf)
            else:
                        with open(path, 'wb'):
                            pass

            os.chmod(path, stat.S_IMODE(fi.mode))

        elif fi.is_blk or fi.is_chr:
            dev_major = (fi.device >> 8) & 0xFF
            dev_minor = fi.device & 0xFF
            if hasattr(os, 'mknod'):
                os.mknod(path, mode=fi.mode, device=os.makedev(dev_major, dev_minor))

        elif fi.is_fifo:
            if hasattr(os, 'mkfifo'):
                os.mkfifo(path, mode=stat.S_IMODE(fi.mode))

        ectx.warnings |= _try_set_ownership(path, fi.uid, fi.gid)

        if fi.xattrs:
            ectx.warnings |= _try_set_xattrs(path, fi.xattrs)

        ectx.warnings |= _try_set_mtime(path, fi.mtime)

        return 0


class VerifyOps(ExtractOps):
    def v3index(self, ectx, obj):
        return 0

    def v3meta(self, ectx, obj):
        return 0

    def file(self, ectx, fi, istream):
        if istream is not None:
            while istream.read(65536):
                pass
        return 0


def extract_archive(archive_path, ops=None, root='/'):
    ctx = ExtractCtx(ops=ops or InstallOps(root=root), root=root)

    with tarfile.open(archive_path, 'r:*') as tar:
        for member in tar.getmembers():
            if ctx.aborted:
                break
            fi = _extract_tar_member_info(tar, member)
            if fi.is_reg and fi.size > 0:
                fobj = tar.extractfile(member)
                r = ctx.ops.file(ctx, fi, fobj)
                if fobj:
                    fobj.close()
            else:
                r = ctx.ops.file(ctx, fi, None)
            if r < 0:
                ctx.abort()

    return ctx


def verify_archive(archive_path):
    return extract_archive(archive_path, ops=VerifyOps())


def _extract_member_data(tar, member):
    f = tar.extractfile(member)
    if f is None:
        return b''
    data = f.read()
    f.close()
    return data


def warning_str(warnings):
    if not warnings:
        return None
    parts = []
    if warnings & WARNING_OWNER:
        parts.append('owner')
    if warnings & WARNING_PERMISSION:
        parts.append('permission')
    if warnings & WARNING_MTIME:
        parts.append('mtime')
    if warnings & WARNING_XATTR:
        parts.append('xattrs')
    return ' '.join(parts) if parts else 'unknown'


def extract_with_progress(archive_path, root='/', progress_callback=None):
    ops = InstallOps(root=root)
    ctx = ExtractCtx(ops=ops, root=root)

    with tarfile.open(archive_path, 'r:*') as tar:
        members = tar.getmembers()
        total = len(members)
        for i, member in enumerate(members, 1):
            if ctx.aborted:
                break
            fi = _extract_tar_member_info(tar, member)
            if fi.is_reg and fi.size > 0:
                fobj = tar.extractfile(member)
                r = ops.file(ctx, fi, fobj)
                if fobj:
                    fobj.close()
            else:
                r = ops.file(ctx, fi, None)
            if progress_callback:
                progress_callback(i, total, fi.name)
            if r < 0:
                ctx.abort()

    return ctx
