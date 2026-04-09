import struct
import os

DB_PATH = os.path.expanduser("~/Library/Caches/BrickStore/database-v12")

# chunk header: u32 id, u32 version, u64 size
CHUNK_HDR_SIZE = 16
# chunk footer: u64 size, u32 version, u32 id
CHUNK_FTR_SIZE = 16


def chunkId(s):
    b = s.encode('ascii')
    return (b[0] & 0x7f) | ((b[1] & 0x7f) << 8) | ((b[2] & 0x7f) << 16) | ((b[3] & 0x7f) << 24)


BSDB = chunkId("BSDB")
COL_ = chunkId("COL ")
CAT_ = chunkId("CAT ")
TYPE = chunkId("TYPE")
ITEM = chunkId("ITEM")


class Reader:
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def u8(self):
        v = self.data[self.pos]
        self.pos += 1
        return v

    def i8(self):
        v = struct.unpack_from('<b', self.data, self.pos)[0]
        self.pos += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self):
        v = struct.unpack_from('<Q', self.data, self.pos)[0]
        self.pos += 8
        return v

    def f32(self):
        # QDataStream with default SinglePrecision reads float as 4 bytes,
        # but BrickStore's DB uses DoublePrecision (8 bytes per float)
        v = struct.unpack_from('<d', self.data, self.pos)[0]
        self.pos += 8
        return float(v)

    def raw(self, n):
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def skip(self, n):
        self.pos += n

    # QColor serialization: i8 spec, then always 5x u16 (alpha, c1, c2, c3, pad)
    def qcolor(self):
        spec = self.i8()
        a = self.u16()
        r = self.u16()
        g = self.u16()
        b = self.u16()
        self.u16()  # pad
        if spec == 1:  # Rgb
            return (r >> 8, g >> 8, b >> 8, a >> 8)
        return None

    def pooled_char8(self):
        length = self.u32()
        if length == 0xFFFFFFFF:
            return ""
        if length == 0:
            return ""
        val = self.raw(length)
        # char8_t arrays have appended null during write, but size stored without it
        return val.decode('utf-8', errors='replace')

    def pooled_char16(self):
        byte_count = self.u32()
        if byte_count == 0xFFFFFFFF:
            return ""
        if byte_count == 0:
            return ""
        val = self.raw(byte_count)
        return val.decode('utf-16-le', errors='replace')

    def pooled_u16_array(self):
        count = self.u32()
        if count == 0 or count == 0xFFFFFFFF:
            return []
        vals = struct.unpack_from(f'<{count}H', self.data, self.pos)
        self.pos += count * 2
        return list(vals)

    def pooled_u32_array(self):
        count = self.u32()
        if count == 0 or count == 0xFFFFFFFF:
            return []
        vals = struct.unpack_from(f'<{count}I', self.data, self.pos)
        self.pos += count * 4
        return list(vals)

    def pooled_raw_array(self, elem_size):
        count = self.u32()
        if count == 0 or count == 0xFFFFFFFF:
            self.skip(0)
            return count if count != 0xFFFFFFFF else 0
        self.skip(count * elem_size)
        return count


def readChunkHeader(r):
    cid = r.u32()
    cver = r.u32()
    csize = r.u64()
    return cid, cver, csize


def skipChunk(r, csize):
    r.skip(csize)
    # padding to 16-byte boundary
    if csize % 16:
        r.skip(16 - (csize % 16))
    # footer
    r.skip(CHUNK_FTR_SIZE)


def endChunk(r, data_start, csize):
    end = data_start + csize
    if r.pos != end:
        r.pos = end
    if csize % 16:
        r.skip(16 - (csize % 16))
    r.skip(CHUNK_FTR_SIZE)


def readColors(r, count):
    colors = []
    for _ in range(count):
        cid = r.u32()
        name = r.pooled_char16()
        r.skip(4)  # ldraw_id (i32)
        color_rgba = r.qcolor()
        flags = r.u32()
        r.f32()  # popularity
        r.u16()  # year_from
        r.u16()  # year_to
        # v7+ ldraw extra fields
        r.qcolor()  # ldraw_color
        r.qcolor()  # ldraw_edge
        r.f32()  # luminance
        r.f32()  # particleMinSize
        r.f32()  # particleMaxSize
        r.qcolor()  # particleColor
        r.f32()  # particleFraction
        r.f32()  # particleVFraction
        colors.append({
            "color_id": cid,
            "color_name": name,
            "color_code": f"#{color_rgba[0]:02x}{color_rgba[1]:02x}{color_rgba[2]:02x}" if color_rgba else None,
            "color_type": flags,
        })
    return colors


def readCategories(r, count):
    cats = []
    for _ in range(count):
        cid = r.u32()
        name = r.pooled_char16()
        year_from = r.u8()
        year_to = r.u8()
        year_recency = r.u8()
        has_inventories = r.u8()
        cats.append({
            "category_id": cid,
            "category_name": name,
        })
    return cats


def readItemTypes(r, count):
    types = []
    for _ in range(count):
        type_id = r.i8()
        name = r.pooled_char16()
        flags = r.u8()
        cat_indexes = r.pooled_u16_array()
        types.append({
            "id": chr(type_id) if 32 <= type_id < 127 else str(type_id),
            "name": name,
        })
    return types


def readItems(r, count, item_types, categories):
    items = []
    for i in range(count):
        item_id = r.pooled_char8()
        name = r.pooled_char16()
        item_type_idx = r.u16()
        default_color_idx = r.u16()
        year_from = r.u8()
        year_to = r.u8()
        weight = r.f32()

        # skip appears_in (4 bytes each)
        appears_count = r.pooled_raw_array(4)
        # skip consists_of (8 bytes each)
        consists_count = r.pooled_raw_array(8)
        # skip known color indexes (2 bytes each)
        known_colors = r.pooled_u16_array()
        # category indexes
        cat_indexes = r.pooled_u16_array()
        # skip relationship match ids (2 bytes each)
        rel_matches = r.pooled_u16_array()
        # skip dimensions (8 bytes each)
        dims_count = r.pooled_raw_array(8)
        # skip pccs (8 bytes each)
        pccs_count = r.pooled_raw_array(8)
        # alternate ids (char8_t)
        alt_ids = r.pooled_char8()

        type_char = ""
        if 0 <= item_type_idx < len(item_types):
            type_char = item_types[item_type_idx]["id"]

        cat_id = None
        if cat_indexes:
            idx = cat_indexes[0]
            if 0 <= idx < len(categories):
                cat_id = categories[idx]["category_id"]

        year_released = (year_from + 1900) if year_from else 0
        year_last = (year_to + 1900) if year_to else year_released

        items.append({
            "no": item_id,
            "name": name,
            "type": type_char,
            "category_id": cat_id,
            "weight": round(weight, 2) if weight else None,
            "year_released": year_released if year_released else None,
            "year_last_produced": year_last if year_last else None,
            "is_obsolete": False,  # not stored in DB directly
        })

        if (i + 1) % 50000 == 0:
            print(f"  read {i + 1} / {count} items...")

    return items


def parseDatabase(db_path=DB_PATH):
    print(f"reading {db_path} ...")
    with open(db_path, "rb") as f:
        data = f.read()

    r = Reader(data)
    print(f"database size: {len(data)} bytes")

    # root BSDB chunk
    root_id, root_ver, root_size = readChunkHeader(r)
    assert root_id == BSDB, f"not a BSDB file (got 0x{root_id:08x})"
    print(f"database version: {root_ver}")

    root_data_start = r.pos
    root_end = root_data_start + root_size

    colors_list = []
    categories_list = []
    item_types_list = []
    items_list = []

    while r.pos < root_end:
        cid, cver, csize = readChunkHeader(r)
        chunk_data_start = r.pos

        id_chars = ''.join([
            chr(cid & 0x7f),
            chr((cid >> 8) & 0x7f),
            chr((cid >> 16) & 0x7f),
            chr((cid >> 24) & 0x7f),
        ])

        if cid == COL_:
            count = r.u32()
            print(f"parsing {count} colors...")
            colors_list = readColors(r, count)

        elif cid == CAT_:
            count = r.u32()
            print(f"parsing {count} categories...")
            categories_list = readCategories(r, count)

        elif cid == TYPE:
            count = r.u32()
            print(f"parsing {count} item types...")
            item_types_list = readItemTypes(r, count)

        elif cid == ITEM:
            count = r.u32()
            print(f"parsing {count} items...")
            items_list = readItems(r, count, item_types_list, categories_list)

        else:
            pass  # skip unknown chunks

        endChunk(r, chunk_data_start, csize)

    return {
        "colors": colors_list,
        "categories": categories_list,
        "item_types": item_types_list,
        "items": items_list,
    }


