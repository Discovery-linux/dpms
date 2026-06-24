import fnmatch
import gzip
import hashlib
import json
import os
import re
import tarfile
import time
from collections import defaultdict

from rich import print as rprint
from rich.table import Table
from rich.console import Console

from . import dpms_logging

log = dpms_logging.setup_logger("dpms-ftparchive")

ARCHIVE_RE = re.compile(
    r'(.+?)-([0-9][\w.]*)(?:-(\w+))?\.dp(?:-rc\d+)?\.tar\.xz$',
    re.IGNORECASE,
)

ARCHIVE_RE_LEGACY = re.compile(
    r'(.+?)-([0-9][\w.]*)\.(?:tar\.(?:gz|xz|bz2)|dpm|tgz|tbz2|txz)$',
    re.IGNORECASE,
)

HASH_FLAGS = {
    'MD5': 1,
    'SHA1': 2,
    'SHA256': 4,
    'SHA512': 8,
}


def _human_size(size):
    for unit in ['', 'K', 'M', 'G']:
        if size < 1024:
            return f"{size:.1f}{unit}B"
        size /= 1024
    return f"{size:.1f}TB"


def _checksums(path):
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
            sha512.update(chunk)
    s = os.path.getsize(path)
    return {'MD5': md5.hexdigest(), 'SHA1': sha1.hexdigest(),
            'SHA256': sha256.hexdigest(), 'SHA512': sha512.hexdigest(), 'Size': s}


def _hash_data(data, hash_type):
    h = hashlib.new(hash_type.lower().replace('sum', ''))
    h.update(data.encode() if isinstance(data, str) else data)
    return h.hexdigest()


def delete_all_but_most_recent(directory, keep_files):
    if not os.path.isdir(directory):
        return
    entries = [(os.path.getmtime(os.path.join(directory, f)),
                os.path.join(directory, f))
               for f in os.listdir(directory)
               if os.path.isfile(os.path.join(directory, f))]
    entries.sort(key=lambda x: x[0])
    for _, path in entries[:-keep_files]:
        os.remove(path)


def gen_by_hash_filename(output_file, hash_type, hash_value):
    by_hash = f"/by-hash/{hash_type}/{hash_value}"
    idx = output_file.rfind('/')
    if idx == -1:
        return by_hash
    return output_file[:idx] + by_hash


def _parse_package_from_archive(path):
    basename = os.path.basename(path)
    m = ARCHIVE_RE.match(basename)
    if m:
        arch = m.group(3) or 'x86_64'
        return {'Package': m.group(1), 'Version': m.group(2),
                'Architecture': arch, 'Filename': basename,
                'Size': str(os.path.getsize(path))}
    m = ARCHIVE_RE_LEGACY.match(basename)
    if m:
        return {'Package': m.group(1), 'Version': m.group(2),
                'Architecture': 'x86_64', 'Filename': basename,
                'Size': str(os.path.getsize(path))}
    return None


def _extract_control_from_archive(path):
    meta = {}
    try:
        with tarfile.open(path, 'r:*') as tar:
            for member in tar.getmembers():
                bn = os.path.basename(member.name)
                if bn in ('control', 'PKGINFO', 'metadata.xml', 'package.json'):
                    f = tar.extractfile(member)
                    if f:
                        raw = f.read()
                        if bn.endswith('.json'):
                            meta.update(json.loads(raw))
                        else:
                            for line in raw.decode('utf-8', errors='replace').splitlines():
                                if ':' in line:
                                    k, v = line.split(':', 1)
                                    meta[k.strip()] = v.strip()
                    break
    except Exception as e:
        log.debug(f"extract control from {path}: {e}")
    return meta


def _installed_size(path):
    total = 0
    try:
        with tarfile.open(path, 'r:*') as tar:
            for m in tar.getmembers():
                if m.isfile():
                    total += m.size
    except Exception:
        pass
    return str(total // 1024) if total else '0'


class DscExtract:
    def __init__(self):
        self.data = ''
        self.length = 0
        self.is_clear_signed = False

    def take_dsc(self, new_data):
        if not new_data:
            self.data = '\n\n'
            self.length = 0
            return True
        self.data = new_data + '\n\n'
        self.length = len(new_data)
        return True

    def read(self, filepath):
        self.data = ''
        self.length = 0
        self.is_clear_signed = False
        try:
            with open(filepath, 'rb') as f:
                raw = f.read()
        except OSError:
            return False
        text = raw.decode('utf-8', errors='replace')
        if text.startswith('-----BEGIN PGP SIGNED MESSAGE-----'):
            self.is_clear_signed = True
            cleaned = []
            found = False
            for line in text.splitlines(True):
                if line.startswith('-----BEGIN PGP SIGNATURE-----'):
                    break
                if found:
                    cleaned.append(line)
                if line.startswith('-----BEGIN PGP SIGNED MESSAGE-----'):
                    found = True
            text = ''.join(cleaned)
            stripped = []
            for line in text.splitlines(True):
                if line.startswith('- '):
                    stripped.append(line[2:])
                else:
                    stripped.append(line)
            text = ''.join(stripped)
        self.data = text + '\n\n'
        self.length = len(text)
        return True


class OverrideItem:
    def __init__(self):
        self.priority = ''
        self.old_maint = ''
        self.new_maint = ''
        self.field_override = {}

    def swap_maint(self, orig):
        if not self.new_maint and self.old_maint:
            return self.old_maint, False
        if not self.new_maint:
            return '', False
        if self.old_maint == '*':
            return self.new_maint, False
        for part in self.old_maint.split(' // '):
            if part.strip().lower() == orig.strip().lower():
                return self.new_maint, False
        return '', True


class Override:
    def __init__(self):
        self.mapping = {}

    def read_override(self, filepath, source=False):
        if not filepath:
            return True
        try:
            with open(filepath) as f:
                for line in f:
                    if '#' in line:
                        line = line[:line.index('#')]
                    line = line.strip()
                    if not line:
                        continue
                    fields = line.split()
                    if source:
                        if len(fields) < 2:
                            continue
                        itm = OverrideItem()
                        itm.field_override['Section'] = fields[1]
                        self.mapping[fields[0]] = itm
                    else:
                        if len(fields) < 3:
                            continue
                        itm = OverrideItem()
                        itm.priority = fields[1]
                        itm.field_override['Section'] = fields[2]
                        parts = line.split(None, 3)
                        if len(parts) >= 4:
                            rest = parts[3]
                            if rest.startswith('=> '):
                                rest = rest[3:]
                            mp = rest.split(' => ', 1)
                            if len(mp) == 2:
                                itm.old_maint = mp[0].strip()
                                itm.new_maint = mp[1].strip()
                            else:
                                itm.old_maint = '*'
                                itm.new_maint = rest.strip()
                        self.mapping[fields[0]] = itm
        except OSError:
            return False
        return True

    def read_extra_override(self, filepath):
        if not filepath:
            return True
        try:
            with open(filepath) as f:
                for line in f:
                    if '#' in line:
                        line = line[:line.index('#')]
                    line = line.strip()
                    if not line:
                        continue
                    fields = line.split(None, 2)
                    if len(fields) < 3:
                        continue
                    pkg, field, value = fields
                    if pkg not in self.mapping:
                        self.mapping[pkg] = OverrideItem()
                    self.mapping[pkg].field_override[field] = value
        except OSError:
            return False
        return True

    def get_item(self, package, architecture=''):
        base = self.mapping.get(package)
        arch_key = f'{package}/{architecture}'
        arch_sp = self.mapping.get(arch_key)
        if base is None and arch_sp is None:
            return None
        result = OverrideItem()
        if base is not None:
            result.priority = base.priority
            result.old_maint = base.old_maint
            result.new_maint = base.new_maint
            result.field_override = dict(base.field_override)
        if arch_sp is not None:
            if arch_sp.priority:
                result.priority = arch_sp.priority
            if arch_sp.old_maint:
                result.old_maint = arch_sp.old_maint
            if arch_sp.new_maint:
                result.new_maint = arch_sp.new_maint
            for k, v in arch_sp.field_override.items():
                result.field_override[k] = v
        return result


class _FtwScanner:
    def __init__(self, output=None, arch='', include_arch_all=True):
        self.arch = arch
        self.include_arch_all = include_arch_all
        self.patterns = []
        self.dir_strip = ''
        self.path_prefix = ''
        self.internal_prefix = ''
        self.de_link_limit = 0
        self.de_link_bytes = 0
        self.no_link_act = False
        self.do_hashes = ~0
        self.output = output
        self.packages_count = 0
        self.misses = 0
        self.bytes_total = 0

    def add_pattern(self, pattern):
        self.patterns.append(pattern)

    def add_patterns(self, patterns):
        self.patterns.extend(patterns)

    def clear_patterns(self):
        self.patterns = []

    def set_exts(self, exts):
        self.clear_patterns()
        for ext in exts.split():
            self.add_pattern(f'*{ext}')
            if self.arch:
                self.add_pattern(f'*_{self.arch}{ext}')
                self.add_pattern(f'*-{self.arch}{ext}')
                if self.include_arch_all and self.arch != 'all':
                    self.add_pattern(f'*_all{ext}')
                    self.add_pattern(f'*-all{ext}')

    def _matches(self, filename):
        base = os.path.basename(filename)
        return any(fnmatch.fnmatch(base, p) for p in self.patterns)

    def _delink(self, filename, original_path, file_size):
        if not self.internal_prefix:
            return filename
        if not filename.startswith(self.internal_prefix):
            if self.de_link_limit and self.de_link_bytes // 1024 < self.de_link_limit:
                self.de_link_bytes += file_size
            return original_path
        return filename

    def _strip_dir(self, filename):
        if self.dir_strip and filename.startswith(self.dir_strip):
            return filename[len(self.dir_strip):]
        if self.dir_strip and self.dir_strip.startswith('/'):
            ds = self.dir_strip.lstrip('/')
            if filename.startswith(ds):
                return filename[len(ds):]
        return filename

    def _apply_prefix(self, filename):
        if self.path_prefix:
            return os.path.join(self.path_prefix, filename.lstrip('/'))
        return filename

    def do_package(self, filepath):
        raise NotImplementedError

    def recursive_scan(self, directory):
        if not self.internal_prefix:
            self.internal_prefix = os.path.abspath(directory)
        files_to_process = []
        for root, dirs, files in os.walk(directory):
            for f in sorted(files):
                fp = os.path.join(root, f)
                if self._matches(fp):
                    files_to_process.append(fp)
        files_to_process.sort()
        for fp in files_to_process:
            self.do_package(fp)
        return True

    def load_file_list(self, directory, filepath):
        if not self.internal_prefix:
            self.internal_prefix = os.path.abspath(directory)
        with open(filepath) as f:
            for line in f:
                fn = line.strip()
                if not fn:
                    continue
                if fn[0] != '/':
                    if directory and directory[-1] != '/':
                        fn = f"{directory}/{fn}"
                    else:
                        fn = f"{directory}{fn}"
                if self._matches(fn):
                    self.do_package(fn)
        return True


class PackagesWriter(_FtwScanner):
    def __init__(self, output=None, trans_writer=None, db='',
                 overrides='', ext_overrides='',
                 arch='', include_arch_all=True):
        super().__init__(output, arch, include_arch_all)
        self.set_exts('.dp.tar.xz .tar.xz .dpm')
        self.db_path = db
        self.de_link_limit = 0
        self.no_override = False
        self.long_description = True
        self.contents_enabled = True
        self.trans_writer = trans_writer
        self.over = Override()
        if overrides:
            if not self.over.read_override(overrides):
                self.no_override = True
        else:
            self.no_override = True
        if ext_overrides:
            self.over.read_extra_override(ext_overrides)

    def do_package(self, filepath):
        meta = _parse_package_from_archive(filepath)
        if not meta:
            log.debug(f"skipping {filepath}")
            return
        ctrl = _extract_control_from_archive(filepath)
        pkg = {**ctrl, **meta}
        ck = _checksums(filepath)
        pkg['MD5sum'] = ck['MD5']
        pkg['SHA1'] = ck['SHA1']
        pkg['SHA256'] = ck['SHA256']
        pkg['SHA512'] = ck['SHA512']
        pkg['Size'] = str(ck['Size'])
        pkg['Installed-Size'] = _installed_size(filepath)
        filename = self._strip_dir(filepath)
        filename = self._delink(filename, filepath, ck['Size'])
        pkg['Filename'] = self._apply_prefix(filename)
        package_name = pkg.get('Package', '')
        arch_val = self.arch or pkg.get('Architecture', '')
        over_item = self.over.get_item(package_name, arch_val)
        if over_item:
            pkg['Priority'] = over_item.priority or pkg.get('Priority', '')
            for k, v in over_item.field_override.items():
                if k not in ('Priority',) or not over_item.priority:
                    pkg[k] = v
            if over_item.old_maint or over_item.new_maint:
                orig_maint = pkg.get('Maintainer', '')
                new_maint, failed = over_item.swap_maint(orig_maint)
                if not failed and new_maint:
                    pkg['Maintainer'] = new_maint
        if not self.long_description and 'Description' in pkg:
            desc = pkg['Description']
            short_desc = desc.split('\n')[0] if '\n' in desc else desc
            desc_md5 = hashlib.md5(desc.encode()).hexdigest()
            pkg['Description-md5'] = desc_md5
            pkg['Description'] = short_desc
            if self.trans_writer:
                self.trans_writer.do_package(package_name, desc, desc_md5)
        pkg.pop('Status', None)
        if not self.contents_enabled:
            pkg.pop('Contents', None)
        self.packages_count += 1
        self._write_record(pkg)

    def _write_record(self, pkg):
        if self.output is None:
            return
        for k in ('Package', 'Version', 'Architecture', 'Filename',
                   'Size', 'Installed-Size', 'MD5sum', 'SHA1', 'SHA256', 'SHA512',
                   'Priority', 'Section', 'Maintainer', 'Description',
                   'Description-md5', 'Homepage', 'License',
                   'Depends', 'Provides', 'Conflicts', 'Replaces',
                   'Suggests', 'Recommends', 'Enhances', 'Breaks',
                   'Source', 'Essential', 'Origin', 'Bugs'):
            v = pkg.get(k)
            if v is not None and v != '':
                self.output.write(f"{k}: {v}\n")
        self.output.write("\n")


class TranslationWriter:
    def __init__(self, filepath='', compress_str='. gzip', perms=0o644):
        self.filepath = filepath
        self.compress_str = compress_str
        self.perms = perms
        self.included = set()
        self.buf = []

    def do_package(self, pkg, desc, md5):
        if not self.filepath:
            return True
        key = f"{pkg}:{md5}"
        if key in self.included:
            return True
        self.buf.append(f"Package: {pkg}\nDescription-md5: {md5}\nDescription-en: {desc}\n")
        self.included.add(key)
        return True

    def write(self):
        if not self.buf:
            return
        data = ''.join(self.buf)
        with open(self.filepath, 'w') as f:
            f.write(data)
        if 'gzip' in self.compress_str:
            with gzip.open(self.filepath + '.gz', 'wt') as f:
                f.write(data)


class SourcesWriter(_FtwScanner):
    PRIORITY_ORDER = {
        'required': 1, 'important': 2, 'standard': 3,
        'optional': 4, 'extra': 5,
    }

    def __init__(self, output=None, db='', b_overrides='',
                 s_overrides='', ext_overrides=''):
        super().__init__(output)
        self.add_pattern('*.dsc')
        self.db_path = db
        self.de_link_limit = 0
        self.no_override = False
        self.b_over = Override()
        self.s_over = Override()
        if b_overrides:
            if not self.b_over.read_override(b_overrides):
                self.no_override = True
        else:
            self.no_override = True
        if ext_overrides:
            self.s_over.read_extra_override(ext_overrides)
        if s_overrides and os.path.isfile(s_overrides):
            self.s_over.read_override(s_overrides, source=True)

    def do_package(self, filepath):
        dsc = DscExtract()
        if not dsc.read(filepath):
            return
        tags = self._parse_tags(dsc.data)
        if not tags:
            return
        source = tags.get('Source', os.path.basename(filepath))
        package = source
        binary = tags.get('Binary', '')
        best_prio = ''
        best_prio_v = 99
        over_item = None
        if binary:
            for bin_pkg in (b.strip() for b in binary.split(',') if b.strip()):
                itm = self.b_over.get_item(bin_pkg)
                if itm is None:
                    continue
                pv = self.PRIORITY_ORDER.get(itm.priority.lower(), 99)
                if pv < best_prio_v or not best_prio:
                    best_prio_v = pv
                    best_prio = itm.priority
                if over_item is None:
                    over_item = itm
        if over_item is None:
            over_item = OverrideItem()
        s_itm = self.s_over.get_item(package)
        if s_itm is None:
            s_itm = self.b_over.get_item(package)
        if s_itm is None:
            s_itm = over_item
        st = os.stat(filepath)
        stripped = os.path.basename(filepath)
        ck = _checksums(filepath)
        files_line = self._format_dsc_files(ck, st.st_size, stripped)
        sha1_line = self._format_checksum_field(ck, 'SHA1', st.st_size, stripped)
        sha256_line = self._format_checksum_field(ck, 'SHA256', st.st_size, stripped)
        sha512_line = self._format_checksum_field(ck, 'SHA512', st.st_size, stripped)
        filename = self._strip_dir(filepath)
        new_filename = self._apply_prefix(filename)
        directory = os.path.dirname(new_filename)
        changes = {}
        changes['Package'] = package
        if files_line:
            changes['Files'] = files_line
        if sha1_line:
            changes['Checksums-Sha1'] = sha1_line
        if sha256_line:
            changes['Checksums-Sha256'] = sha256_line
        if sha512_line:
            changes['Checksums-Sha512'] = sha512_line
        if directory and directory not in ('', '.', './'):
            changes['Directory'] = directory.rstrip('/')
        if best_prio:
            changes['Priority'] = best_prio
        changes.pop('Source', None)
        changes.pop('Status', None)
        maint_failed = False
        if over_item.old_maint or over_item.new_maint:
            orig_maint = tags.get('Maintainer', '')
            new_maint, maint_failed = over_item.swap_maint(orig_maint)
            if not maint_failed and new_maint:
                changes['Maintainer'] = new_maint
        for k, v in s_itm.field_override.items():
            changes[k] = v
        for k, v in changes.items():
            if k in tags:
                tags[k] = v
        self._write_record(tags)
        self.packages_count += 1

    def _parse_tags(self, data):
        tags = {}
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            if ':' in line:
                k, v = line.split(':', 1)
                tags[k.strip()] = v.strip()
        return tags

    def _format_dsc_files(self, ck, size, filename):
        if not ck:
            return ''
        return f"\n {ck['MD5']} {size} {filename}"

    def _format_checksum_field(self, ck, algo, size, filename):
        if not ck or algo not in ck:
            return ''
        return f"\n {ck[algo]} {size} {filename}"

    def _write_record(self, tags):
        if self.output is None:
            return
        order = ['Package', 'Version', 'Source', 'Binary', 'Architecture',
                 'Priority', 'Section', 'Maintainer', 'Description',
                 'Homepage', 'Directory', 'Files',
                 'Checksums-Sha1', 'Checksums-Sha256', 'Checksums-Sha512',
                 'Origin', 'Bugs', 'Standards-Version', 'Format',
                 'Build-Depends', 'Build-Depends-Indep',
                 'Build-Conflicts', 'Build-Conflicts-Indep',
                 'Uploaders', 'Vcs-Browser', 'Vcs-Git',
                 'Vcs-Svn', 'Vcs-Hg', 'Vcs-Darcs',
                 'Testsuite', 'Testsuite-Triggers']
        seen = set()
        for k in order:
            v = tags.get(k)
            if v is not None and v != '':
                self.output.write(f"{k}: {v}\n")
                seen.add(k)
        for k, v in tags.items():
            if k not in seen and v is not None and v != '':
                self.output.write(f"{k}: {v}\n")
        self.output.write("\n")


class ContentsWriter(_FtwScanner):
    def __init__(self, output=None, db='', arch='', include_arch_all=True):
        super().__init__(output, arch, include_arch_all)
        self.set_exts('.dp.tar.xz .tar.xz .dpm')
        self.db_path = db
        self.file_map = defaultdict(list)
        self.prefix = ''

    def do_package(self, filepath, package=''):
        meta = _parse_package_from_archive(filepath)
        if not meta and not package:
            return
        pkg_name = package or meta['Package']
        try:
            with tarfile.open(filepath, 'r:*') as tar:
                for m in tar.getmembers():
                    self.file_map[m.name].append(pkg_name)
        except Exception as e:
            log.debug(f"contents read {filepath}: {e}")

    def read_from_pkgs(self, pkg_file, pkg_compress='. gzip'):
        path = pkg_file
        if pkg_compress and '.gz' in pkg_compress and not pkg_file.endswith('.gz'):
            path = pkg_file + '.gz'
        pkgs = self._read_rfc822(path)
        for pkg in pkgs:
            fname = os.path.join(self.prefix, pkg.get('Filename', ''))
            section = pkg.get('Section', '')
            pkg_name = pkg.get('Package', '')
            tag = f"{section}/{pkg_name}" if section else pkg_name
            self.do_package(fname, tag)

    def _read_rfc822(self, path):
        records = []
        try:
            f = gzip.open(path, 'rt') if path.endswith('.gz') else open(path)
            current = {}
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    if current:
                        records.append(current)
                        current = {}
                    continue
                if ':' in line:
                    k, v = line.split(':', 1)
                    current[k.strip()] = v.strip()
            if current:
                records.append(current)
            f.close()
        except Exception:
            pass
        return records

    def finish(self):
        if self.output is None:
            return
        for path in sorted(self.file_map):
            pkgs = ','.join(sorted(set(self.file_map[path])))
            self.output.write(f"{path} {pkgs}\n")


class ReleaseWriter(_FtwScanner):
    def __init__(self, output=None, db=''):
        super().__init__(output)
        self.add_patterns([
            'Packages', 'Packages.*',
            'Translation-*',
            'Sources', 'Sources.*',
            'Release',
            'Contents-*',
            'Index', 'Index.*',
            'icons-*.tar', 'icons-*.tar.*',
            'Components-*.yml', 'Components-*.yml.*',
            'md5sum.txt',
        ])
        self.check_sums = {}
        self.do_hashes = ~0
        self.dir_strip_val = ''

    def do_package(self, filepath):
        filename = self._strip_dir(filepath)
        while filename.startswith('/'):
            filename = filename[1:]
        filename = self._apply_prefix(filename)
        size = os.path.getsize(filepath)
        ck = _checksums(filepath)
        self.check_sums[filename] = {
            'size': size,
            'hashes': ck,
        }
        return True

    def finish(self):
        if self.output is None:
            return
        FLAG_MAP = {'MD5Sum': 'MD5', 'SHA1': 'SHA1', 'SHA256': 'SHA256', 'SHA512': 'SHA512'}
        for algo in ('MD5Sum', 'SHA1', 'SHA256', 'SHA512'):
            flag_key = FLAG_MAP[algo]
            if not (self.do_hashes & HASH_FLAGS.get(flag_key, 0)):
                continue
            self.output.write(f"{algo}:\n")
            for fname in sorted(self.check_sums):
                cs = self.check_sums[fname]
                if cs['size'] == 0:
                    continue
                h = cs['hashes'].get(flag_key, '')
                if not h:
                    continue
                self.output.write(f" {h} {cs['size']:16} {fname}\n")


def _write_rfc822(records, path, compress=True, by_hash=False):
    lines = []
    for rec in records:
        for k, v in rec.items():
            if v is not None and v != '':
                lines.append(f"{k}: {v}")
        lines.append('')
    data = '\n'.join(lines)

    paths = [path]
    if by_hash:
        sha256 = hashlib.sha256(data.encode()).hexdigest()
        paths.append(gen_by_hash_filename(path, 'SHA256', sha256))

    for p in paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
            f.write(data)

    if compress:
        gzdata = gzip.compress(data.encode())
        gzpaths = [path + '.gz']
        if by_hash:
            sha256 = hashlib.sha256(gzdata).hexdigest()
            gzpaths.append(gen_by_hash_filename(path + '.gz', 'SHA256', sha256))
        for p in gzpaths:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(gzdata)


def _scan_packages(binary_path, path_prefix=''):
    packages = []
    binary_path = os.path.abspath(binary_path)
    for root, dirs, files in os.walk(binary_path):
        for f in sorted(files):
            if not (f.endswith('.dp.tar.xz') or f.endswith('.tar.xz')
                    or f.endswith('.dpm')):
                continue
            ap = os.path.join(root, f)
            meta = _parse_package_from_archive(ap)
            if not meta:
                log.debug(f"skipping unrecognized archive: {f}")
                continue
            ctrl = _extract_control_from_archive(ap)
            pkg = {**ctrl, **meta}
            rel = os.path.relpath(ap, binary_path)
            pkg['Filename'] = os.path.join(path_prefix, rel) if path_prefix else rel
            ck = _checksums(ap)
            pkg['MD5sum'] = ck['MD5']
            pkg['SHA1'] = ck['SHA1']
            pkg['SHA256'] = ck['SHA256']
            pkg['SHA512'] = ck['SHA512']
            pkg['Size'] = str(ck['Size'])
            pkg['Installed-Size'] = _installed_size(ap)
            packages.append(pkg)
            log.debug(f"found: {pkg['Package']} {pkg['Version']} ({pkg['Architecture']})")
    return packages


def gen_packages(binary_path, output_path=None, path_prefix='', compress=True):
    if output_path is None:
        output_path = os.path.join(os.path.dirname(binary_path.rstrip('/')), 'Packages')
    rprint(f"[bold]scanning {binary_path} for packages...[/bold]")
    pkgs = _scan_packages(binary_path, path_prefix=path_prefix)
    if not pkgs:
        rprint("[yellow]no packages found[/yellow]")
        return True
    _write_rfc822(pkgs, output_path, compress=compress)
    rprint(f"[green]done[/green] — [bold]{len(pkgs)}[/bold] packages")
    return True


def gen_sources(binary_path, output_path=None, path_prefix='', compress=True):
    if output_path is None:
        output_path = os.path.join(os.path.dirname(binary_path.rstrip('/')), 'Sources')
    rprint(f"[bold]scanning {binary_path} for source packages...[/bold]")
    pkgs = _scan_packages(binary_path, path_prefix=path_prefix)
    srcs = [p for p in pkgs if p.get('Architecture') == 'source'
            or p.get('Package', '').endswith('-src')]
    if not srcs:
        srcs = pkgs
    if not srcs:
        rprint("[yellow]no source packages found[/yellow]")
        return True
    _write_rfc822(srcs, output_path, compress=compress)
    rprint(f"[green]done[/green] — [bold]{len(srcs)}[/bold] sources")
    return True


def gen_contents(binary_path, packages, output_path=None, compress=True):
    if output_path is None:
        d = os.path.dirname(binary_path.rstrip('/'))
        output_path = os.path.join(d, 'Contents')
    rprint(f"[bold]generating Contents index...[/bold]")
    cw = ContentsWriter()
    for pkg in packages:
        ap = pkg.get('_archive_path') or os.path.join(binary_path, pkg.get('Filename', ''))
        if os.path.exists(ap):
            cw.do_package(ap, pkg.get('Package', ''))
    cw.finish()
    lines = []
    for path in sorted(cw.file_map):
        lines.append(f"{path} {','.join(sorted(set(cw.file_map[path])))}")
    data = '\n'.join(lines) + '\n' if lines else ''
    with open(output_path, 'w') as f:
        f.write(data)
    log.info(f"wrote {len(lines)} entries to {output_path}")
    if compress:
        with gzip.open(output_path + '.gz', 'wt', encoding='utf-8') as f:
            f.write(data)
    rprint(f"[green]done[/green] — [bold]{len(lines)}[/bold] file entries")
    return True


def gen_release(directory, output_path=None, label=None,
                suite=None, codename=None, origin=None):
    if output_path is None:
        output_path = os.path.join(directory, 'Release')
    rprint(f"[bold]generating Release for {directory}...[/bold]")
    now = time.strftime('%a, %d %b %Y %H:%M:%S UTC', time.gmtime())
    lines = []
    if label:
        lines.append(f"Label: {label}")
    if suite:
        lines.append(f"Suite: {suite}")
    if codename:
        lines.append(f"Codename: {codename}")
    if origin:
        lines.append(f"Origin: {origin}")
    lines.append(f"Date: {now}")
    rw = ReleaseWriter()
    rw.dir_strip = directory
    index_patterns = ['Packages', 'Packages.gz', 'Packages.xz',
                      'Sources', 'Sources.gz', 'Sources.xz',
                      'Contents', 'Contents.gz',
                      'Translation-en', 'Translation-en.gz',
                      'Release', 'InRelease']
    for f in sorted(os.listdir(directory)):
        for p in index_patterns:
            if f == p or f.startswith(p + '-'):
                path = os.path.join(directory, f)
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    rw.do_package(path)
    FLAG_MAP = {'MD5Sum': 'MD5', 'SHA1': 'SHA1', 'SHA256': 'SHA256', 'SHA512': 'SHA512'}
    for algo in ('MD5Sum', 'SHA1', 'SHA256', 'SHA512'):
        flag_key = FLAG_MAP[algo]
        has_any = any(
            rw.check_sums[fname]['hashes'].get(flag_key, '')
            for fname in rw.check_sums
            if rw.check_sums[fname]['size'] > 0
            and fname not in ('Release', 'InRelease')
        )
        if not has_any:
            continue
        lines.append('')
        lines.append(f"{algo}:")
        for fname in sorted(rw.check_sums):
            cs = rw.check_sums[fname]
            if cs['size'] == 0 or fname in ('Release', 'InRelease'):
                continue
            h = cs['hashes'].get(flag_key, '')
            if h:
                lines.append(f" {h} {cs['size']:16} {fname}")
    data = '\n'.join(lines) + '\n'
    with open(output_path, 'w') as f:
        f.write(data)
    rprint(f"[green]done[/green] — Release written to [bold]{output_path}[/bold]")
    return True


def gen_repo(binary_path, output_dir=None, path_prefix='', compress=True,
             suite=None, codename=None, origin=None, label=None):
    if output_dir is None:
        output_dir = os.path.dirname(binary_path.rstrip('/'))
    os.makedirs(output_dir, exist_ok=True)
    rprint(f"[bold]generating repository in {output_dir}...[/bold]")
    packages = _scan_packages(binary_path, path_prefix=path_prefix)
    if not packages:
        rprint("[yellow]no packages found[/yellow]")
        return True
    pkg_path = os.path.join(output_dir, 'Packages')
    src_path = os.path.join(output_dir, 'Sources')
    _write_rfc822(packages, pkg_path, compress=compress)
    srcs = [p for p in packages if p.get('Architecture') == 'source'
            or p.get('Package', '').endswith('-src')]
    _write_rfc822(srcs or packages, src_path, compress=compress)
    for pkg in packages:
        ap = os.path.join(binary_path, pkg['Filename'])
        if os.path.exists(ap):
            pkg['_archive_path'] = ap
    gen_contents(binary_path, packages, output_path=os.path.join(output_dir, 'Contents'),
                 compress=compress)
    gen_release(output_dir, label=label, suite=suite,
                codename=codename, origin=origin)
    rprint(f"[green]repository generated in {output_dir}[/green]")
    return True


def gen_generate(config_path, groups=None):
    rprint(f"[bold]reading config: {config_path}...[/bold]")
    with open(config_path) as f:
        cfg = json.load(f) if config_path.endswith('.json') else _parse_conf(f.read())
    archive_dir = cfg.get('ArchiveDir', '.')
    output_dir = cfg.get('OutputDir', archive_dir)
    suite = cfg.get('Suite', '')
    codename = cfg.get('Codename', '')
    origin = cfg.get('Origin', 'dpms')
    label = cfg.get('Label', 'DPMS Repository')
    compress = cfg.get('Compress', True)
    tree = cfg.get('Tree', [])
    if not tree:
        tree = [{'Directory': '.', 'Architectures': ['x86_64'],
                 'Packages': 'Packages', 'Sources': 'Sources',
                 'Contents': 'Contents'}]
    for entry in tree:
        bd = os.path.join(archive_dir, entry.get('Directory', '.'))
        if not os.path.isdir(bd):
            rprint(f"[yellow]skipping {bd}: not a directory[/yellow]")
            continue
        for arch in entry.get('Architectures', ['x86_64']):
            tag = f"{entry.get('Directory', '.')}/{arch}"
            if groups and not any(g in tag for g in groups):
                continue
            rprint(f"[bold]processing {tag}...[/bold]")
            pkgs = _scan_packages(bd)
            if entry.get('Packages'):
                pp = os.path.join(output_dir, entry['Packages'])
                os.makedirs(os.path.dirname(pp), exist_ok=True)
                _write_rfc822(pkgs, pp, compress=compress)
            if entry.get('Sources'):
                sp = os.path.join(output_dir, entry['Sources'])
                os.makedirs(os.path.dirname(sp), exist_ok=True)
                srcs = [p for p in pkgs if p.get('Architecture') == 'source'
                        or p.get('Package', '').endswith('-src')]
                _write_rfc822(srcs or pkgs, sp, compress=compress)
            if entry.get('Contents'):
                cp = os.path.join(output_dir, entry['Contents'])
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                for p in pkgs:
                    ap = os.path.join(bd, p['Filename'])
                    if os.path.exists(ap):
                        p['_archive_path'] = ap
                gen_contents(bd, pkgs, output_path=cp, compress=compress)
    gen_release(output_dir, label=label, suite=suite,
                codename=codename, origin=origin)
    rprint(f"[green]generate complete[/green]")
    return True


def _parse_conf(text):
    cfg = {'Tree': []}
    current_tree = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.lower().startswith('tree '):
            parts = line.split(None, 1)
            cfg['Tree'].append({'Directory': parts[1] if len(parts) > 1 else '.'})
            current_tree = cfg['Tree'][-1]
        elif '=' in line and '::' not in line:
            k, v = line.split('=', 1)
            cfg[k.strip()] = v.strip()
        elif current_tree is not None and ':' in line:
            k, v = line.split(':', 1)
            k = k.strip().lower()
            v = v.strip()
            if k == 'packages':
                current_tree['Packages'] = v
            elif k == 'sources':
                current_tree['Sources'] = v
            elif k == 'contents':
                current_tree['Contents'] = v
            elif k == 'architectures':
                current_tree['Architectures'] = v.split()
            elif k == 'directory':
                current_tree['Directory'] = v
    return cfg


def gen_clean(cache_dir):
    if not os.path.isdir(cache_dir):
        rprint(f"[yellow]{cache_dir} does not exist[/yellow]")
        return True
    count = 0
    for f in os.listdir(cache_dir):
        if f.endswith('.db') or f.endswith('.cache'):
            os.remove(os.path.join(cache_dir, f))
            count += 1
    rprint(f"[green]cleaned {count} cache files from {cache_dir}[/green]")
    return True
