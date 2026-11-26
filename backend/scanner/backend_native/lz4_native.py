"""Optional system liblz4 fast path; bounded, no package install, safe fallback.

liblz4 accepts zero match offsets that our wire decoder rejects. Validate the
compressed structure without constructing output before returning native data.
Nonstandard blocks rejected by liblz4 go through the original Python decoder.
"""
import ctypes
import ctypes.util
import re


try:
    _library = ctypes.CDLL(ctypes.util.find_library('lz4') or 'liblz4.so.1')
    _decode = _library.LZ4_decompress_safe
    _decode.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)
    _decode.restype = ctypes.c_int
except (OSError, AttributeError):
    _decode = None

_extension_end = re.compile(b'[^\xff]')


def _valid_structure(src, expected):
    """Preserve original offset/length acceptance with no per-byte output work."""
    pos = size = 0
    end = len(src)
    while pos < end:
        token = src[pos]
        pos += 1
        literal = token >> 4
        if literal == 15:
            stop = _extension_end.search(src, pos)
            if stop is None:
                return False
            at = stop.start()
            literal += (at - pos) * 255 + src[at]
            pos = at + 1
        pos += literal
        size += literal
        if pos == end:
            return size == expected
        if pos + 2 > end:
            return False
        offset = src[pos] | (src[pos + 1] << 8)
        if not 0 < offset <= size:
            return False
        pos += 2
        match = (token & 15) + 4
        if match == 19:
            stop = _extension_end.search(src, pos)
            if stop is None:
                return False
            at = stop.start()
            match += (at - pos) * 255 + src[at]
            pos = at + 1
        size += match
        if size > expected:
            return False
    return size == expected


def decompress(src, max_output):
    """Return decoded bytes, or None to use the reference-compatible fallback."""
    if _decode is None or not src or not isinstance(max_output, int) or not 0 < max_output <= 0x1000000:
        return None
    if len(src) > 0x7fffffff:
        return None
    capacity = min(max_output, max(4096, len(src) * 4))
    while True:
        output = ctypes.create_string_buffer(capacity)
        size = _decode(src, output, len(src), capacity)
        if size >= 0:
            if _valid_structure(src, size):
                return output.raw[:size]
            return None
        if capacity == max_output:
            return None
        capacity = min(max_output, capacity * 4)
