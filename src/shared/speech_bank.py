"""
shared/speech_bank.py — read and rebuild the game's speech archives,
Audio/dat_eng.big (the clips) and Audio/hdr_eng.big (one small header per
clip), to add new commentary name clips.

Both are BIGF archives with the same entries in the same order, named
"<id:04d>_<Name>.dat" / ".hdr" for the name clips. A name clip's header
(24 bytes, little-endian):

    b4 04  id:u16  01 02 00 00  dat_size/256-1:u16  00 00 00 00  01 00
    ceil(used_bytes/256):u16  70 70 03 00 00 00

where used_bytes is the SCHl stream up to and including SCEl, and dat_size
is the entry size (the stream padded with zeros to a multiple of 256).

    read_big(path)                    -> [(name, bytes), ...]
    write_big(path, entries)
    name_header(cid, dat)             -> the .hdr bytes for an SCHl clip
    padded_dat(schl)                  -> the clip padded like the stock ones
    add_clips(dat_entries, hdr_entries, clips)  # clips: [(cid, name, schl)]
"""
import re
import struct

_CLIP = re.compile(r"(\d{4})_(.+)\.(dat|hdr)$", re.IGNORECASE)


def read_big(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"BIGF":
        raise ValueError(f"{path}: not a BIGF archive")
    count = struct.unpack_from(">I", data, 8)[0]
    pos = 16
    out = []
    for _ in range(count):
        offset, size = struct.unpack_from(">II", data, pos)
        end = data.index(b"\0", pos + 8)
        out.append((data[pos + 8:end].decode("latin-1"), data[offset:offset + size]))
        pos = end + 1
    return out


def write_big(path, entries, align=128, marker=True):
    """A BIGF archive of `entries` [(name, bytes)], laid out like the stock
    speech archives: table, 8 bytes ("L234" + zeros in hdr_eng.big, zeros in
    dat_eng.big, whose header size field then counts 3 of them), entries on
    `align`. Rebuilding a stock archive gives it back byte for byte."""
    table_end = 16 + sum(8 + len(n.encode("latin-1")) + 1 for n, _ in entries)
    pos = table_end + 8
    offsets = []
    for _, blob in entries:
        pos += -pos % align
        offsets.append(pos)
        pos += len(blob)
    total = pos
    with open(path, "wb") as f:
        f.write(b"BIGF" + struct.pack("<I", total) + struct.pack(">II", len(entries), table_end + (8 if marker else 3)))
        for (name, blob), off in zip(entries, offsets):
            f.write(struct.pack(">II", off, len(blob)) + name.encode("latin-1") + b"\0")
        f.write((b"L234" if marker else b"\0" * 4) + b"\0" * 4)
        for (name, blob), off in zip(entries, offsets):
            f.write(b"\0" * (off - f.tell()))
            f.write(blob)


def schl_used(schl):
    """Bytes of the SCHl stream up to and including SCEl."""
    pos = 0
    while pos + 8 <= len(schl):
        tag = schl[pos:pos + 4]
        size = struct.unpack_from("<I", schl, pos + 4)[0]
        if size < 8:
            break
        pos += size
        if tag == b"SCEl":
            return pos
    raise ValueError("SCHl stream has no SCEl")


def padded_dat(schl):
    used = schl_used(schl)
    data = schl[:used]
    return data + b"\0" * (-len(data) % 256)


def name_header(cid, dat):
    used = schl_used(dat)
    return (b"\xb4\x04" + struct.pack("<H", cid) + b"\x01\x02\x00\x00"
            + struct.pack("<H", len(dat) // 256 - 1) + b"\0\0\0\0\x01\x00"
            + struct.pack("<H", (used + 255) // 256) + b"\x70\x70\x03\x00\x00\x00")


def clip_ids(entries):
    """{id: name} of the name clips among `entries`."""
    out = {}
    for name, _ in entries:
        m = _CLIP.match(name)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def add_clips(dat_entries, hdr_entries, clips):
    """New lists with `clips` [(cid, name, schl)] appended (ids must be new)."""
    taken = clip_ids(dat_entries)
    dat_entries, hdr_entries = list(dat_entries), list(hdr_entries)
    for cid, name, schl in clips:
        if cid in taken or not 0 < cid < 0x10000:
            raise ValueError(f"commentary id {cid} is already used or out of range")
        base = f"{cid:04d}_{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'Name'}"
        dat = padded_dat(schl)
        dat_entries.append((base + ".dat", dat))
        hdr_entries.append((base + ".hdr", name_header(cid, dat)))
    return dat_entries, hdr_entries
