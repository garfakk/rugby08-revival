"""EA BIGF archive reader (kit/model bundles shipped with Rugby 08).

Layout: 'BIGF', u32 LE total size, u32 BE entry count, u32 BE header size,
then per entry {u32 BE offset, u32 BE size, NUL-terminated name}.
"""
import struct


class BigArchive:
    def __init__(self, blob: bytes):
        if blob[:4] != b'BIGF':
            raise ValueError('not a BIGF archive')
        self.blob = blob
        count = struct.unpack_from('>I', blob, 8)[0]
        self.entries: dict[str, tuple[int, int]] = {}
        off = 16
        for _ in range(count):
            start, size = struct.unpack_from('>II', blob, off)
            off += 8
            end = blob.index(b'\0', off)
            name = blob[off:end].decode('latin-1')
            off = end + 1
            self.entries[name] = (start, size)

    @classmethod
    def open(cls, path):
        with open(path, 'rb') as fd:
            return cls(fd.read())

    def __contains__(self, name):
        return name in self.entries

    def read(self, name: str) -> bytes:
        start, size = self.entries[name]
        return self.blob[start:start + size]

    def find(self, suffix: str) -> str | None:
        """First entry name ending with `suffix` (e.g. '.fsh'), or None."""
        for name in self.entries:
            if name.lower().endswith(suffix.lower()):
                return name
        return None


def pack_big(entries, align=16):
    """BIGF archive bytes from [(name, data)], in order, each file `align`-
    byte aligned (the layout of the game's own stadium packs)."""
    head = 16 + sum(8 + len(name.encode('latin-1')) + 1 for name, _ in entries)
    pos = (head + align - 1) // align * align
    directory, body, offsets = b'', b'', []
    for name, data in entries:
        offsets.append(pos + len(body))
        body += data + b'\0' * ((-len(data)) % align)
    for (name, data), off in zip(entries, offsets):
        directory += struct.pack('>II', off, len(data)) + name.encode('latin-1') + b'\0'
    blob = b'\0' * (pos - head)
    total = pos + len(body)
    return b'BIGF' + struct.pack('<I', total) + struct.pack('>II', len(entries), (head + 3) // 4 * 4) \
        + directory + blob + body
