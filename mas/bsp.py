"""Reads what a map (.bsp) uses from outside itself: materials, models and sounds.

Covers the textures on its brushes, its sky, the models of its props and entities, sprites,
overlays and ambient sounds - and lists what the map packs inside itself.
Not covered: textures a model names inside its own .mdl.
"""

import io
import lzma
import re
import struct
import zipfile

LUMP_ENTITIES = 0
LUMP_GAME = 35
LUMP_PAKFILE = 40
LUMP_TEXDATA_STRINGS = 43
SPRP = int.from_bytes(b"sprp", "big")
SKY_SIDES = ("bk", "dn", "ft", "lf", "rt", "up")


def _lzma(data):
    """Valve's LZMA lump: 'LZMA', real size, packed size, 5 property bytes, then the stream."""
    if data[:4] != b"LZMA" or len(data) < 17:
        return data
    size, _packed = struct.unpack_from("<II", data, 4)
    props = data[12:17]
    pb, rest = divmod(props[0], 45)
    lp, lc = divmod(rest, 9)
    dict_size = int.from_bytes(props[1:5], "little")
    dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_LZMA1, "dict_size": dict_size, "lc": lc, "lp": lp, "pb": pb}])
    return dec.decompress(data[17:], max_length=size)


class Bsp:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.raw = f.read()
        if self.raw[:4] != b"VBSP":
            raise ValueError(f"{path}: not a Source map")
        self.version = struct.unpack_from("<i", self.raw, 4)[0]
        lumps = [struct.unpack_from("<iiii", self.raw, 8 + 16 * i) for i in range(64)]
        # Left 4 Dead 2 style maps put the lump version first.
        if self._fits(lumps, 0, 1) < self._fits(lumps, 1, 2):
            lumps = [(o, n, v, c) for v, o, n, c in lumps]
        self.lumps = lumps

    def _fits(self, lumps, oi, ni):
        size = len(self.raw)
        return sum(1 for l in lumps if l[ni] > 0 and 1032 <= l[oi] <= size and l[oi] + l[ni] <= size)

    def lump(self, i):
        ofs, length, _, _ = self.lumps[i]
        return _lzma(self.raw[ofs:ofs + length])

    def packed(self):
        """Lowercase paths of the files packed inside the map."""
        data = self.lump(LUMP_PAKFILE)
        if not data:
            return set()
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return {n.replace("\\", "/").lower() for n in z.namelist()}
        except zipfile.BadZipFile:
            return set()

    def brush_materials(self):
        data = self.lump(LUMP_TEXDATA_STRINGS)
        return {s.decode("latin-1").lower().replace("\\", "/") for s in data.split(b"\0") if s}

    def static_props(self):
        data = self.lump(LUMP_GAME)
        if len(data) < 4:
            return set()
        count = struct.unpack_from("<i", data, 0)[0]
        entries = [struct.unpack_from("<iHHii", data, 4 + 16 * i) for i in range(count)]
        blob = None
        for i, (gid, flags, _ver, gofs, glen) in enumerate(entries):
            if gid != SPRP:
                continue
            if flags & 1:
                # Compressed: its length is up to the next entry's offset (glen is unpacked size).
                end = entries[i + 1][3] if i + 1 < count else gofs + glen
                blob = _lzma(self.raw[gofs:end])
            else:
                blob = self.raw[gofs:gofs + glen]
        if not blob or len(blob) < 4:
            return set()
        n = struct.unpack_from("<i", blob, 0)[0]
        names = set()
        for i in range(n):
            name = blob[4 + 128 * i:4 + 128 * (i + 1)].split(b"\0", 1)[0]
            if name:
                names.add(name.decode("latin-1").lower().replace("\\", "/"))
        return names

    def entities(self):
        text = self.lump(LUMP_ENTITIES).decode("latin-1", "replace")
        for block in re.findall(r"\{([^{}]*)\}", text):
            yield dict((k.lower(), v) for k, v in re.findall(r'"([^"]*)"\s+"([^"]*)"', block))


def _mat(name):
    name = name.lower().replace("\\", "/").lstrip("/")
    if name.startswith("materials/"):
        name = name[len("materials/"):]
    if name.endswith(".vmt"):
        name = name[:-4]
    return f"materials/{name}.vmt"


def references(path):
    """(paths the map uses, paths it packs). Paths are lowercase, game-relative."""
    bsp = Bsp(path)
    used = {_mat(m) for m in bsp.brush_materials()}
    used |= {m for m in bsp.static_props() if m.endswith(".mdl")}
    for ent in bsp.entities():
        for key, val in ent.items():
            v = val.lower().replace("\\", "/")
            if v.endswith(".mdl"):
                used.add(v)
            elif v.endswith((".vmt", ".spr")) or key in ("material", "detailmaterial", "texture"):
                if v and not v.startswith("*"):
                    used.add(_mat(v[:-4] if v.endswith(".spr") else v))
            elif v.endswith((".wav", ".mp3")):
                used.add("sound/" + v.lstrip("#*@)(^<>!?}$").lstrip("/"))
        if ent.get("classname") == "worldspawn" and ent.get("skyname"):
            sky = ent["skyname"].lower()
            used |= {f"materials/skybox/{sky}{side}.vmt" for side in SKY_SIDES}
    return used, bsp.packed()
