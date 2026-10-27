"""Reads the index of a Valve VPK pack (versions 1 and 2).

A pack is either one file, or a small *_dir.vpk index plus numbered parts (*_000.vpk, ...).
"""

import hashlib
import struct
from dataclasses import dataclass

SIGNATURE = 0x55AA1234
IN_DIR = 0x7FFF  # archive index meaning "the data sits in the _dir file, after the index"


@dataclass(frozen=True)
class Entry:
    path: str          # lowercase, forward slashes, e.g. "materials/brick/wall01.vtf"
    crc: int
    preload: bytes     # bytes stored inside the index itself
    archive: int       # part number, or IN_DIR
    offset: int
    length: int        # bytes in the part (not counting preload)

    @property
    def size(self):
        return len(self.preload) + self.length


@dataclass
class Index:
    version: int
    tree_size: int
    header_size: int
    entries: list

    @property
    def data_start(self):
        """Where IN_DIR data begins in the _dir (or single) file."""
        return self.header_size + self.tree_size


def _cstr(buf, pos):
    end = buf.index(b"\0", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def parse(data):
    """Parse the index from the start of a VPK file's bytes."""
    sig, version, tree_size = struct.unpack_from("<III", data, 0)
    if sig != SIGNATURE:
        raise ValueError("not a VPK file")
    if version == 1:
        header_size = 12
    elif version == 2:
        header_size = 28
    else:
        raise ValueError(f"unsupported VPK version {version}")

    entries = []
    pos = header_size
    end = header_size + tree_size
    while pos < end:
        ext, pos = _cstr(data, pos)
        if not ext:
            break
        while True:
            folder, pos = _cstr(data, pos)
            if not folder:
                break
            while True:
                name, pos = _cstr(data, pos)
                if not name:
                    break
                crc, preload_len, archive, offset, length, term = struct.unpack_from("<IHHIIH", data, pos)
                pos += 18
                if term != 0xFFFF:
                    raise ValueError("corrupt VPK index")
                preload = bytes(data[pos:pos + preload_len])
                pos += preload_len
                path = name if folder == " " else f"{folder}/{name}"
                if ext != " ":
                    path = f"{path}.{ext}"
                entries.append(Entry(path.lower().replace("\\", "/"), crc, preload, archive, offset, length))
    return Index(version, tree_size, header_size, entries)


def read(path):
    """Read a VPK index from a file on disk (reads only the header and index)."""
    with open(path, "rb") as f:
        head = f.read(12)
        sig, version, tree_size = struct.unpack("<III", head)
        if sig != SIGNATURE:
            raise ValueError(f"{path}: not a VPK file")
        header_size = 28 if version == 2 else 12
        f.seek(0)
        return parse(f.read(header_size + tree_size))


def chunk_name(dir_name, archive):
    """'pak01_dir.vpk', 3 -> 'pak01_003.vpk'."""
    return f"{dir_name[:-len('_dir.vpk')]}_{archive:03d}.vpk"


# --- Writing -------------------------------------------------------------------------------
# We write single-file version 2 packs, like Momentum's own custom/pocmanvpk.vpk: header,
# index, then every file's data, then three MD5 sums (the index; the empty archive-sum
# section; everything before this last sum).

HEADER_V2 = struct.Struct("<7I")
SUMS_SIZE = 48


@dataclass(frozen=True)
class OutFile:
    path: str
    crc: int
    size: int
    offset: int    # within the data section


def index_bytes(files):
    """The index (directory tree) for files stored in the pack itself."""
    groups = {}
    for f in files:
        folder, _, base = f.path.rpartition("/")
        name, dot, ext = base.rpartition(".")
        if not dot:
            name, ext = base, ""
        groups.setdefault(ext or " ", {}).setdefault(folder or " ", []).append((name, f))
    out = bytearray()
    for ext in sorted(groups):
        out += ext.encode() + b"\0"
        for folder in sorted(groups[ext]):
            out += folder.encode() + b"\0"
            for name, f in sorted(groups[ext][folder], key=lambda nf: nf[0]):
                out += name.encode() + b"\0"
                out += struct.pack("<IHHIIH", f.crc, 0, IN_DIR, f.offset, f.size, 0xFFFF)
            out += b"\0"
        out += b"\0"
    out += b"\0"
    return bytes(out)


def create(path, files):
    """Start a pack: write its header and index, and reserve room for the data.
    Returns where the data section begins."""
    tree = index_bytes(files)
    data_size = max((f.offset + f.size for f in files), default=0)
    with open(path, "wb") as f:
        f.write(HEADER_V2.pack(SIGNATURE, 2, len(tree), data_size, 0, SUMS_SIZE, 0))
        f.write(tree)
        f.truncate(HEADER_V2.size + len(tree) + data_size + SUMS_SIZE)
    return HEADER_V2.size + len(tree)


def finish(path):
    """Write the three MD5 sums once all data is in."""
    with open(path, "r+b") as f:
        _, _, tree_size, data_size, _, _, _ = HEADER_V2.unpack(f.read(HEADER_V2.size))
        tree = f.read(tree_size)
        sums = hashlib.md5(tree).digest() + hashlib.md5(b"").digest()
        whole = hashlib.md5()
        f.seek(0)
        left = HEADER_V2.size + tree_size + data_size
        while left:
            block = f.read(min(left, 8 << 20))
            whole.update(block)
            left -= len(block)
        whole.update(sums)
        f.write(sums + whole.digest())
