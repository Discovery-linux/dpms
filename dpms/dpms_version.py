import re

UNKNOWN = 0
EQUAL = 1
LESS = 2
GREATER = 3
FUZZY = 4
CONFLICT = 5


# FIXME: this doesnt handle all RPM version formats
def _split_version(ver):
    parts = re.split(r'[._+%-]', ver)
    result = []
    for p in parts:
        if p.startswith('r') and p[1:].isdigit():
            result.append(('release', int(p[1:])))
        elif p.isdigit():
            result.append(('num', int(p)))
        else:
            letters = []
            nums = []
            for ch in p:
                if ch.isdigit():
                    nums.append(ch)
                    if letters:
                        result.append(('str', ''.join(letters)))
                        letters = []
                else:
                    letters.append(ch)
                    if nums:
                        result.append(('num', int(''.join(nums))))
                        nums = []
            if letters:
                result.append(('str', ''.join(letters)))
            if nums:
                result.append(('num', int(''.join(nums))))
    return result


def validate(ver):
    return bool(ver) and isinstance(ver, str)


def compare(a, b):
    pa = _split_version(a)
    pb = _split_version(b)
    for (ta, va), (tb, vb) in zip(pa, pb):
        if ta != tb:
            order = ('num', 'str', 'release')
            return LESS if order.index(ta) < order.index(tb) else GREATER
        if va != vb:
            return LESS if va < vb else GREATER
    if len(pa) != len(pb):
        return LESS if len(pa) < len(pb) else GREATER
    return EQUAL


def match(a, op, b):
    cmp = compare(a, b)
    if op == LESS:
        return cmp == LESS
    if op == EQUAL:
        return cmp == EQUAL
    if op == GREATER:
        return cmp == GREATER
    if op == FUZZY:
        return cmp in (LESS, EQUAL, GREATER)
    if op == CONFLICT:
        return False
    return False
