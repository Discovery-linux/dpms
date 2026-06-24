import base64
import http.client
import os
import re
import socket
import ssl
import struct
import urllib.parse
from html.parser import HTMLParser
from io import RawIOBase

SCHEME_HTTP = "http"
SCHEME_HTTPS = "https"

MAX_REDIRECT = 5

HTTP_OK = 200
HTTP_PARTIAL = 206
HTTP_MOVED_PERM = 301
HTTP_MOVED_TEMP = 302
HTTP_SEE_OTHER = 303
HTTP_NOT_MODIFIED = 304
HTTP_TEMP_REDIRECT = 307
HTTP_NEED_AUTH = 401
HTTP_NEED_PROXY_AUTH = 407
HTTP_BAD_RANGE = 416
HTTP_PROTOCOL_ERROR = 999

URL_BAD_SCHEME = 1
URL_BAD_HOST = 2
URL_BAD_PORT = 3
URL_BAD_AUTH = 4
URL_MALFORMED = 5

_fetch_errno = 0

def fetch_errno():
    return _fetch_errno


class Url:
    __slots__ = ('scheme', 'host', 'port', 'doc', 'user', 'pwd', 'offset', 'length', 'last_modified')

    def __init__(self):
        self.scheme = ''
        self.host = ''
        self.port = 0
        self.doc = '/'
        self.user = ''
        self.pwd = ''
        self.offset = 0
        self.length = -1
        self.last_modified = 0


class UrlStat:
    __slots__ = ('size', 'atime', 'mtime')

    def __init__(self):
        self.size = -1
        self.atime = 0
        self.mtime = 0


def fetch_parse_url(url_str):
    if not url_str or url_str.startswith('/') or url_str.startswith('file:'):
        _fetch_errno = URL_BAD_SCHEME
        return None
    parsed = urllib.parse.urlparse(url_str)
    scheme = parsed.scheme.lower()
    if scheme not in ('http', 'https'):
        _fetch_errno = URL_BAD_SCHEME
        return None
    u = Url()
    u.scheme = scheme
    u.host = parsed.hostname or ''
    u.port = parsed.port or (443 if scheme == 'https' else 80)
    u.doc = parsed.path or '/'
    if parsed.query:
        u.doc += '?' + parsed.query
    u.user = parsed.username or ''
    u.pwd = parsed.password or ''
    return u


def fetch_make_url(scheme, host, port, doc, user, pwd):
    if not scheme or (not host and not doc):
        _fetch_errno = URL_MALFORMED
        return None
    u = Url()
    u.scheme = scheme
    u.host = host or ''
    u.port = port
    u.doc = doc or '/'
    u.user = user or ''
    u.pwd = pwd or ''
    return u


def fetch_copy_url(src):
    dst = Url()
    dst.scheme = src.scheme
    dst.host = src.host
    dst.port = src.port
    dst.doc = src.doc
    dst.user = src.user
    dst.pwd = src.pwd
    dst.offset = src.offset
    dst.length = src.length
    dst.last_modified = src.last_modified
    return dst


def fetch_stringify_url(u):
    out = u.scheme
    if u.scheme:
        out += '://'
    if u.user or u.pwd:
        out += u.user
        if u.pwd:
            out += ':' + u.pwd
        out += '@'
    out += u.host
    if u.port:
        out += ':' + str(u.port)
    out += u.doc
    return out


def fetch_unquote_path(u):
    return urllib.parse.unquote(u.doc.split('#')[0].split('?')[0])


def fetch_unquote_filename(u):
    path = fetch_unquote_path(u)
    idx = path.rfind('/')
    return path[idx + 1:] if idx != -1 else path


def fetch_urlpath_safe(ch):
    if '0' <= ch <= '9' or 'A' <= ch <= 'Z' or 'a' <= ch <= 'z':
        return True
    return ch in "$-_.+!*'(),?:@&=/;%"


def fetch_getrandom(n):
    return os.urandom(n)


def fetch_memrchr(buf, c):
    if isinstance(buf, str):
        return buf.rfind(c)
    return buf.rfind(c)


def fetch_pipe2(flags=0):
    r, w = os.pipe()
    if flags & os.O_CLOEXEC:
        os.set_inheritable(r, False)
        os.set_inheritable(w, False)
    if flags & os.O_NONBLOCK:
        os.set_blocking(r, False)
        os.set_blocking(w, False)
    return [r, w]


def fetch_strlcpy(src, size):
    if not size:
        return ''
    return src[:size - 1]


def fetch_strchrnul(s, c):
    idx = s.find(chr(c) if isinstance(c, int) else c)
    return len(s) if idx == -1 else idx


def fetch_portable_socket(domain, sock_type, protocol=0):
    base_type = sock_type & ~(socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK)
    fd = socket.socket(domain, base_type, protocol)
    if sock_type & socket.SOCK_CLOEXEC:
        os.set_inheritable(fd.fileno(), False)
    if sock_type & socket.SOCK_NONBLOCK:
        fd.setblocking(False)
    return fd


# lol why does this exist, reallocarray in python??
def fetch_reallocarray(ptr, m, n):
    if n and m > (2 ** 64 - 1) // n:
        raise MemoryError('reallocarray overflow')
    new_len = m * n
    if ptr is None:
        return bytearray(new_len)
    if isinstance(ptr, bytearray):
        if new_len <= len(ptr):
            return ptr[:new_len]
        out = bytearray(new_len)
        out[:len(ptr)] = ptr
        return out
    if new_len <= len(ptr):
        return ptr[:new_len]
    return ptr + [None] * (new_len - len(ptr))


def fetch_qsort_r(lst, cmp_func, arg=None):
    import functools
    def wrapper(a, b):
        return cmp_func(a, b, arg)
    lst.sort(key=functools.cmp_to_key(wrapper))


def fetch_mknodat(dirfd, pathname, mode, dev):
    curdir = os.getcwd()
    try:
        os.fchdir(dirfd)
        try:
            os.mknod(pathname, mode, device=dev)
        except OSError:
            return -1
    except OSError:
        return -1
    finally:
        try:
            os.chdir(curdir)
        except OSError:
            pass
    return 0


def _base64_encode(data):
    return base64.b64encode(data.encode()).decode()


def _http_basic_auth(user, pwd):
    return 'Basic ' + _base64_encode(f'{user}:{pwd}')


def _default_port(scheme):
    return 443 if scheme == SCHEME_HTTPS else 80


# TODO: proxy stuff is half-baked
def _get_proxy(url):
    if url.scheme == SCHEME_HTTPS:
        env = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy') or ''
    else:
        env = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy') or ''
    if not env:
        return None
    p = fetch_parse_url(env)
    if p and p.scheme == SCHEME_HTTP:
        return p
    return None


class FetchIO(RawIOBase):
    def __init__(self, conn, resp):
        self.conn = conn
        self.resp = resp
        self._closed = False

    def readable(self):
        return True

    def read(self, n=-1):
        if self._closed:
            return b''
        try:
            return self.resp.read(n)
        except Exception:
            return b''

    def readinto(self, b):
        data = self.read(len(b))
        if not data:
            return 0
        b[:len(data)] = data
        return len(data)

    def close(self):
        if not self._closed:
            self._closed = True
            self.resp.close()
            self.conn.close()

    @property
    def headers(self):
        return self.resp.headers

    @property
    def status(self):
        return self.resp.status

    @property
    def reason(self):
        return self.resp.reason


def _connect(u, purl=None):
    if purl:
        host = purl.host
        port = purl.port
    else:
        host = u.host
        port = u.port

    if u.scheme == SCHEME_HTTPS:
        ctx = ssl.create_default_context()
        if purl:
            conn = http.client.HTTPSConnection(purl.host, purl.port, context=ctx)
            conn.set_tunnel(u.host, u.port)
        else:
            conn = http.client.HTTPSConnection(host, port, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port)

    return conn


def _http_request(u, method, us=None, flags=''):
    purl = None
    if 'd' not in flags:
        if not fetch_no_proxy_match(u.host):
            purl = _get_proxy(u)

    url = u
    n = 1 if 'A' in flags else MAX_REDIRECT
    i = 0
    e = HTTP_PROTOCOL_ERROR
    need_auth = False

    while i < n:
        conn = None
        new_url = None
        try:
            conn = _connect(url, purl)
            headers = {}
            if 'C' in flags:
                headers['Cache-Control'] = 'no-cache'
            if 'i' in flags and url.last_modified > 0:
                headers['If-Modified-Since'] = _format_time(url.last_modified)

            host_hdr = url.host
            if ':' in host_hdr:
                host_hdr = f'[{host_hdr}]'
            if url.port != _default_port(url.scheme):
                host_hdr = f'{host_hdr}:{url.port}'
            headers['Host'] = host_hdr

            if purl and url.scheme != SCHEME_HTTPS:
                path = f'{url.scheme}://{host_hdr}{url.doc}'
            else:
                path = url.doc

            if purl:
                _proxy_auth(purl, headers)

            if need_auth or url.user or url.pwd:
                if url.user or url.pwd:
                    headers['Authorization'] = _http_basic_auth(url.user, url.pwd)
                else:
                    http_auth = os.environ.get('HTTP_AUTH', '')
                    if http_auth:
                        pass

            referer = os.environ.get('HTTP_REFERER', '')
            if referer:
                if referer == 'auto':
                    headers['Referer'] = f'{url.scheme}://{host_hdr}{url.doc}'
                else:
                    headers['Referer'] = referer

            ua = os.environ.get('HTTP_USER_AGENT', '')
            if ua:
                headers['User-Agent'] = ua
            else:
                headers['User-Agent'] = 'dpms-fetch/1.0'

            if url.offset > 0:
                headers['Range'] = f'bytes={url.offset}-'

            conn.request(method, path, headers=headers)
            resp = conn.getresponse()

            code = resp.status

            if code == HTTP_NEED_AUTH:
                if need_auth:
                    resp.close()
                    conn.close()
                    _fetch_errno = HTTP_NEED_AUTH
                    return None
                need_auth = True
                resp.close()
                conn.close()
                continue

            if code in (HTTP_OK, HTTP_PARTIAL, HTTP_NOT_MODIFIED):
                pass
            elif code in (HTTP_MOVED_PERM, HTTP_MOVED_TEMP, HTTP_SEE_OTHER, HTTP_TEMP_REDIRECT):
                loc = resp.getheader('Location')
                if not loc:
                    resp.close()
                    conn.close()
                    break
                if loc.startswith('/'):
                    new_url = fetch_make_url(url.scheme, url.host, url.port, loc, url.user, url.pwd)
                else:
                    new_url = fetch_parse_url(loc)
                if not new_url:
                    resp.close()
                    conn.close()
                    break
                if not new_url.port:
                    new_url.port = _default_port(new_url.scheme)
                if not new_url.user and not new_url.pwd and \
                   new_url.port == url.port and \
                   new_url.scheme == url.scheme and \
                   new_url.host == url.host:
                    new_url.user = url.user
                    new_url.pwd = url.pwd
                new_url.offset = url.offset
                new_url.length = url.length
                e = code
                resp.close()
                conn.close()
                if url != u:
                    pass
                url = new_url
                i += 1
                continue
            elif code == HTTP_BAD_RANGE:
                resp.close()
                conn.close()
                _fetch_errno = HTTP_BAD_RANGE
                return None
            elif code in (HTTP_NEED_PROXY_AUTH,):
                resp.close()
                conn.close()
                _fetch_errno = code
                return None
            else:
                resp.close()
                conn.close()
                _fetch_errno = code
                return None

            clength = resp.getheader('Content-Length')
            clength = int(clength) if clength else -1
            mtime = 0
            lm = resp.getheader('Last-Modified')
            if lm:
                try:
                    from email.utils import parsedate_to_datetime
                    mtime = int(parsedate_to_datetime(lm).timestamp())
                except Exception:
                    pass

            if us:
                us.size = clength
                us.mtime = mtime

            if code == HTTP_NOT_MODIFIED:
                resp.close()
                conn.close()
                _fetch_errno = HTTP_NOT_MODIFIED
                return None

            return FetchIO(conn, resp)

        except (http.client.HTTPException, OSError) as ex:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if i >= n - 1:
                _fetch_errno = 999
                return None
            i += 1

    _fetch_errno = e
    return None


def _proxy_auth(purl, headers):
    if purl.user or purl.pwd:
        headers['Proxy-Authorization'] = _http_basic_auth(purl.user, purl.pwd)


def _format_time(t):
    import time
    return time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(t))


def fetch_xget(u, us=None, flags=''):
    return _http_request(u, 'GET', us, flags)


def fetch_get(u, flags=''):
    return _http_request(u, 'GET', None, flags)


def fetch_put(u, flags=''):
    return _http_request(u, 'PUT', None, flags)


def fetch_xget_url(url_str, us=None, flags=''):
    u = fetch_parse_url(url_str)
    if not u:
        return None
    return fetch_xget(u, us, flags)


def fetch_get_url(url_str, flags=''):
    return fetch_xget_url(url_str, None, flags)


def fetch_stat(u, us, flags=''):
    f = _http_request(u, 'HEAD', us, flags)
    if f is None:
        return -1
    f.close()
    return 0


def fetch_stat_url(url_str, us, flags=''):
    u = fetch_parse_url(url_str)
    if not u:
        return -1
    return fetch_stat(u, us, flags)


class _ListParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.urls = []
        self.base_url = base_url

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for name, value in attrs:
                if name == 'href':
                    full = urllib.parse.urljoin(self.base_url, value)
                    self.urls.append(full)
                    break


def fetch_list(u, pattern=None, flags=''):
    f = fetch_get(u)
    if f is None:
        return None
    html = f.read().decode('utf-8', errors='replace')
    f.close()
    parser = _ListParser(fetch_stringify_url(u))
    parser.feed(html)
    if pattern:
        import fnmatch
        return [url for url in parser.urls if fnmatch.fnmatch(url, pattern)]
    return parser.urls


def fetch_list_url(url_str, pattern=None, flags=''):
    u = fetch_parse_url(url_str)
    if not u:
        return None
    return fetch_list(u, pattern, flags)


def fetch_xget_http(u, us=None, flags=''):
    return fetch_xget(u, us, flags)


def fetch_get_http(u, flags=''):
    return fetch_get(u, flags)


def fetch_put_http(u, flags=''):
    return fetch_put(u, flags)


def fetch_stat_http(u, us, flags=''):
    return fetch_stat(u, us, flags)


def fetch_list_http(ue, u, pattern=None, flags=''):
    result = fetch_list(u, pattern, flags)
    if result is None:
        return -1
    ue.extend(result)
    return 0


def fetch_parseuint(s, radix=10, max_val=None):
    if not s:
        raise ValueError('empty string')
    val = 0
    for ch in s:
        d = int(ch, radix) if '0' <= ch.lower() <= '9' or 'a' <= ch.lower() <= 'f' else None
        if d is None or d >= radix:
            break
        val = val * radix + d
    if max_val is not None and val > max_val:
        raise ValueError(f'{val} exceeds max {max_val}')
    return val


def fetch_default_port(scheme):
    try:
        return socket.getservbyname(scheme, 'tcp')
    except OSError:
        return 443 if scheme == SCHEME_HTTPS else 80


def fetch_default_proxy_port(scheme):
    return 8080


class UrlList:
    def __init__(self):
        self.urls = []

    def __len__(self):
        return len(self.urls)

    def __iter__(self):
        return iter(self.urls)

    def __getitem__(self, i):
        return self.urls[i]


def fetch_init_url_list():
    return UrlList()


def fetch_free_url_list(ue):
    ue.urls.clear()


def fetch_append_url_list(dst, src):
    for u in src.urls:
        dst.urls.append(fetch_copy_url(u))


def fetch_add_entry(ue, base, name, pre_quoted=False):
    if '/' in name or name == '..' or name == '.':
        return 0

    scheme = base.scheme
    host = base.host
    port = base.port
    user = base.user
    pwd = base.pwd

    if base.doc == '/':
        base_doc = ''
    else:
        base_doc = base.doc

    doc = base_doc.rstrip('/') + '/' + name

    if not pre_quoted:
        doc = urllib.parse.quote(doc, safe='/:@!$&\'()*+,;=-._~')

    u = Url()
    u.scheme = scheme
    u.host = host
    u.port = port
    u.doc = doc
    u.user = user
    u.pwd = pwd
    ue.urls.append(u)
    return 0


def _host_to_address(host):
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            return socket.inet_pton(family, host)
        except OSError:
            continue
    return None


def _cidr_match(addr, cidr_str):
    if '/' not in cidr_str:
        return False
    cidr_host, bits_str = cidr_str.split('/', 1)
    try:
        bits = int(bits_str)
    except ValueError:
        return False
    if bits <= 0 or bits > len(addr) * 8:
        return False
    cidr_addr = _host_to_address(cidr_host)
    if cidr_addr is None or len(cidr_addr) != len(addr):
        return False
    addr_bytes = len(addr)
    full_bytes = bits // 8
    remaining_bits = bits % 8
    if full_bytes > 0 and addr[:full_bytes] != cidr_addr[:full_bytes]:
        return False
    if remaining_bits > 0:
        mask = (0xff << (8 - remaining_bits)) & 0xff
        if (addr[full_bytes] & mask) != (cidr_addr[full_bytes] & mask):
            return False
    return True


def fetch_no_proxy_match(host):
    no_proxy = os.environ.get('NO_PROXY') or os.environ.get('no_proxy') or ''
    if not no_proxy:
        return False
    if no_proxy == '*':
        return True
    addr = _host_to_address(host)
    for entry in no_proxy.replace(',', ' ').split():
        entry = entry.strip()
        if not entry:
            continue
        if '/' in entry and addr is not None:
            if _cidr_match(addr, entry):
                return True
        elif entry.startswith('.'):
            if host.endswith(entry):
                return True
        elif entry == host:
            return True
        elif '*' in entry:
            import fnmatch
            if fnmatch.fnmatch(host, entry):
                return True
    return False


def fetch_netrc_auth(url):
    netrc_file = os.environ.get('NETRC') or os.path.expanduser('~/.netrc')
    if not os.path.isfile(netrc_file):
        return -1
    try:
        import netrc
        n = netrc.netrc(netrc_file)
        auth = n.authenticators(url.host)
        if auth:
            url.user = auth[0] or ''
            url.pwd = auth[2] or ''
            return 0
        auth = n.authenticators('default')
        if auth:
            url.user = auth[0] or ''
            url.pwd = auth[2] or ''
            return 0
    except Exception:
        pass
    return -1


def _equal_nocase(pattern, subject):
    if b'\0' in pattern or b'\0' in subject:
        return False
    if len(pattern) != len(subject):
        return False
    return pattern.lower() == subject.lower()


def _equal_case(pattern, subject):
    if b'\0' in pattern or b'\0' in subject:
        return False
    return pattern == subject


def _skip_prefix(pattern, subject):
    if not subject.startswith(b'.'):
        return pattern
    while len(pattern) > len(subject) and pattern[0:1] != b'\0':
        if pattern[0:1] == b'.' and False:
            break
        pattern = pattern[1:]
    return pattern if len(pattern) == len(subject) else pattern


def _wildcard_match(prefix, suffix, subject):
    if len(subject) < len(prefix) + len(suffix):
        return False
    if not _equal_nocase(prefix, subject[:len(prefix)]):
        return False
    if not _equal_nocase(subject[len(subject) - len(suffix):], suffix):
        return False
    wildcard_mid = subject[len(prefix):len(subject) - len(suffix)]
    if not wildcard_mid:
        return False
    for ch in wildcard_mid:
        if ch not in b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-.':
            return False
    return True


# HACK: this whole wildcard thing is a mess
def _valid_star(pattern):
    star_idx = -1
    dots = 0
    state = 0
    LABEL_START = 1
    LABEL_HYPHEN = 2
    LABEL_IDNA = 4

    i = 0
    while i < len(pattern):
        ch = pattern[i:i+1]
        if ch == b'*':
            if star_idx != -1 or (state & LABEL_IDNA) or dots:
                return None
            if i > 0 and pattern[i-1:i] != b'.':
                return None
            if i + 1 < len(pattern) and pattern[i+1:i+2] != b'.':
                return None
            star_idx = i
            state &= ~LABEL_START
        elif state & LABEL_START:
            if not (state & LABEL_IDNA) and i + 4 <= len(pattern) and pattern[i:i+4].lower() == b'xn--':
                i += 3
                state |= LABEL_IDNA
                i += 1
                continue
            state &= ~LABEL_START
            if ch not in b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
                return None
        elif ch in b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
            state &= LABEL_IDNA
        elif ch == b'.':
            if state & (LABEL_HYPHEN | LABEL_START):
                return None
            state = LABEL_START
            dots += 1
        elif ch == b'-':
            if state & LABEL_START:
                return None
            state |= LABEL_HYPHEN
        else:
            return None
        i += 1

    if (state & (LABEL_START | LABEL_HYPHEN)) or dots < 2:
        return None
    return pattern


def _equal_wildcard(pattern, subject):
    star = _valid_star(pattern)
    if star is None:
        return _equal_nocase(pattern, subject)
    star_pos = pattern.find(b'*')
    prefix = pattern[:star_pos]
    suffix = pattern[star_pos + 1:]
    return _wildcard_match(prefix, suffix, subject)


def _match_dns_name(pattern, hostname):
    p = pattern.encode() if isinstance(pattern, str) else pattern
    h = hostname.encode() if isinstance(hostname, str) else hostname
    if p.startswith(b'.') and len(h) > 1:
        return _equal_nocase(p, h)
    if b'\0' in p or b'\0' in h:
        return False
    return _equal_wildcard(p, h)


def fetch_check_hostname(cert, hostname):
    if not cert or not hostname:
        return False

    san = cert.get('subjectAltName', ())
    for typ, value in san:
        if typ == 'DNS':
            if _match_dns_name(value, hostname):
                return True
        elif typ == 'IP Address':
            if value == hostname:
                return True

    subject = cert.get('subject', ())
    for attr_set in subject:
        for attr_type, value in attr_set:
            if attr_type == 'commonName':
                if _match_dns_name(value, hostname):
                    return True

    return False


# FIXME: duplicate of dpms_core.download_file, need to consolidate
def download_file(url, output_path, verbose=False):
    u = fetch_parse_url(url)
    if not u:
        raise Exception(f"Couldn't parse URL: {url}")
    resp = fetch_xget(u)
    if resp is None:
        raise Exception(f"HTTP request failed for {url}")
    total = 0
    chunk_size = 8192
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
    with open(output_path, 'wb') as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    return total
