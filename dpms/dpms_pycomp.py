import base64
import itertools
import locale
import queue
import shlex
import types
import urllib.parse
import sys
from io import StringIO
from configparser import ConfigParser

Queue = queue.Queue
basestring = str
filterfalse = itertools.filterfalse
xrange = range
raw_input = input
base64_decodebytes = base64.decodebytes
urlparse = urllib.parse
urllib_quote = urlparse.quote
shlex_quote = shlex.quote
sys_maxsize = sys.maxsize

ModuleType = types.ModuleType
format = locale.format_string
