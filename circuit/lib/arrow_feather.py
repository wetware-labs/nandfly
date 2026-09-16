"""Minimal, from-scratch Apache Arrow IPC File ("Feather V2") reader.

Reused verbatim from the FlyMarket project's connectome pipeline
(sim/core/arrow_feather.py), which is itself part of the DOOMFLY lineage
(github.com/nftechie/doomfly, MIT). Copied in here (not imported cross-repo)
so this repo's derivation pipeline is self-contained and independently
reproducible. Only the reader is reused; the GF circuit selection,
binarization, and netlist logic in circuit/extract.py and circuit/binarize.py
are original work for this project.

Why this exists: MaleCNS v1.0's raw connectome files are published as Arrow
Feather V2 files with per-buffer LZ4_FRAME body compression. Rather than add
a pandas/pyarrow dependency, this module hand-decodes just enough of the
Arrow IPC File format (flatbuffers metadata) and the LZ4 frame format to
extract flat, non-nested columns of type Int (any signed/unsigned bit
width), FloatingPoint, Utf8, Bool, and dictionary-encoded Utf8 (categoricals).

This is NOT a general-purpose Arrow reader: nested List/Struct/Union columns
are structurally skipped (their FieldNodes/buffers are consumed so that
sibling columns still decode correctly), but their contents are not
materialized. That is sufficient for the MaleCNS body-annotations,
neurotransmitters, and edge-weight files, whose columns of interest are
all flat.

Field index constants below are taken directly from Apache Arrow's
Schema.fbs / Message.fbs / File.fbs (flatbuffers field declaration order is
load-bearing: vtable slots are addressed by declaration index, not name).

Validated against the real MaleCNS v1.0 files (see task-9 investigation):
decoded body IDs/types/sides for DNp20 and DNpe017 match DOOMFLY's own
published manifest.json exactly, and R1-R6 (3377) / R8p+R8y (330+481=811)
counts match DOOMFLY's retina/visual-dynamics reports.
"""
import struct

import numpy as np

# ---------------------------------------------------------------- flatbuffers


def _u32(buf, pos):
    return struct.unpack_from('<I', buf, pos)[0]


def _i32(buf, pos):
    return struct.unpack_from('<i', buf, pos)[0]


def _u16(buf, pos):
    return struct.unpack_from('<H', buf, pos)[0]


def _i64(buf, pos):
    return struct.unpack_from('<q', buf, pos)[0]


class FBTable:
    """A flatbuffers table view: a buffer plus the absolute position of one table."""

    __slots__ = ('buf', 'pos')

    def __init__(self, buf, pos):
        self.buf = buf
        self.pos = pos

    def _field_offset(self, field_index):
        soffset = _i32(self.buf, self.pos)
        vtable = self.pos - soffset
        vtable_size = _u16(self.buf, vtable)
        slot = 4 + field_index * 2
        if slot >= vtable_size:
            return 0
        voffset = _u16(self.buf, vtable + slot)
        if voffset == 0:
            return 0
        return self.pos + voffset

    def get_scalar(self, field_index, fmt, default=0):
        off = self._field_offset(field_index)
        if off == 0:
            return default
        return struct.unpack_from(fmt, self.buf, off)[0]

    def get_table(self, field_index):
        off = self._field_offset(field_index)
        if off == 0:
            return None
        target = off + _u32(self.buf, off)
        return FBTable(self.buf, target)

    def get_string(self, field_index):
        off = self._field_offset(field_index)
        if off == 0:
            return None
        target = off + _u32(self.buf, off)
        length = _u32(self.buf, target)
        return self.buf[target + 4: target + 4 + length].decode('utf-8')

    def get_table_vector(self, field_index):
        off = self._field_offset(field_index)
        if off == 0:
            return []
        target = off + _u32(self.buf, off)
        count = _u32(self.buf, target)
        out = []
        for i in range(count):
            slot = target + 4 + i * 4
            elem = slot + _u32(self.buf, slot)
            out.append(FBTable(self.buf, elem))
        return out

    def get_struct_vector_raw(self, field_index, struct_size):
        """Vector of inline (non-offset) structs; returns (buf, start, count)."""
        off = self._field_offset(field_index)
        if off == 0:
            return (self.buf, 0, 0)
        target = off + _u32(self.buf, off)
        count = _u32(self.buf, target)
        return (self.buf, target + 4, count)


def root_table(buf):
    return FBTable(buf, _u32(buf, 0))


# --------------------------------------------------------------- LZ4 frame


def _lz4_block_decompress_append(data, out: bytearray):
    i = 0
    n = len(data)
    while i < n:
        token = data[i]
        i += 1
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = data[i]
                i += 1
                lit_len += b
                if b != 255:
                    break
        if lit_len:
            out += data[i:i + lit_len]
            i += lit_len
        if i >= n:
            break
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        match_len = token & 0xF
        if match_len == 15:
            while True:
                b = data[i]
                i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        start = len(out) - offset
        if offset >= match_len:
            out += out[start:start + match_len]
        else:
            for k in range(match_len):
                out.append(out[start + k])


def lz4_frame_decompress(data: bytes) -> bytes:
    if data[:4] != b'\x04\x22\x4d\x18':
        raise ValueError('not an LZ4 frame (bad magic)')
    pos = 4
    flg = data[pos]
    pos += 2  # flg + bd
    block_indep = bool(flg & 0x20)
    block_checksum = bool(flg & 0x10)
    content_size_flag = bool(flg & 0x08)
    content_checksum = bool(flg & 0x04)
    if content_size_flag:
        pos += 8
    if flg & 0x01:
        pos += 4  # dict id
    pos += 1  # header checksum byte
    out = bytearray()
    while True:
        block_size_field = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if block_size_field == 0:
            break
        uncompressed_flag = bool(block_size_field & 0x80000000)
        block_size = block_size_field & 0x7FFFFFFF
        block_data = data[pos:pos + block_size]
        pos += block_size
        if uncompressed_flag:
            out += block_data
        elif block_indep:
            tmp = bytearray()
            _lz4_block_decompress_append(block_data, tmp)
            out += tmp
        else:
            _lz4_block_decompress_append(block_data, out)
        if block_checksum:
            pos += 4
    if content_checksum:
        pos += 4
    return bytes(out)


def _decompress_buffer(raw: bytes) -> bytes:
    """Arrow BodyCompression/BUFFER layout: 8-byte LE uncompressed-length
    prefix (-1 sentinel means the following bytes are stored uncompressed).

    The declared length is not just documentation: we verify the actual
    decompressed size matches it, so silent truncation/corruption in the
    hand-rolled LZ4 decoder (or a malformed/truncated file) raises instead
    of quietly handing back short or garbage data to the caller."""
    if len(raw) == 0:
        return raw
    uncompressed_len = struct.unpack_from('<q', raw, 0)[0]
    body = raw[8:]
    if uncompressed_len == -1:
        return body
    if len(body) == 0:
        if uncompressed_len != 0:
            raise ValueError(
                f'Arrow buffer declared uncompressed_len={uncompressed_len} '
                f'but compressed body is empty'
            )
        return b''
    out = lz4_frame_decompress(body)
    if len(out) != uncompressed_len:
        raise ValueError(
            f'LZ4-decompressed buffer length mismatch: declared '
            f'{uncompressed_len}, got {len(out)}'
        )
    return out


# ----------------------------------------------------------- Arrow IPC File

F_NAME, F_NULLABLE, F_TYPE_TYPE, F_TYPE, F_DICTIONARY, F_CHILDREN, F_CUSTOM_META = range(7)
SCH_ENDIAN, SCH_FIELDS, SCH_CUSTOM_META, SCH_FEATURES = range(4)
FOOTER_VERSION, FOOTER_SCHEMA, FOOTER_DICTS, FOOTER_RECORDBATCHES, FOOTER_CUSTOM_META = range(5)
MSG_VERSION, MSG_HEADER_TYPE, MSG_HEADER, MSG_BODYLEN, MSG_CUSTOM_META = range(5)
RB_LENGTH, RB_NODES, RB_BUFFERS, RB_COMPRESSION, RB_VARIADIC = range(5)
DB_ID, DB_DATA, DB_ISDELTA = range(3)
DICTENC_ID, DICTENC_INDEXTYPE, DICTENC_ISORDERED, DICTENC_KIND = range(4)
INT_BITWIDTH, INT_SIGNED = range(2)
FLOAT_PRECISION = 0

MESSAGE_HEADER_DICTIONARY_BATCH = 2
MESSAGE_HEADER_RECORD_BATCH = 3

# union Type (1-based, per Schema.fbs declaration order)
(T_NULL, T_INT, T_FLOAT, T_BINARY, T_UTF8, T_BOOL, T_DECIMAL, T_DATE, T_TIME, T_TIMESTAMP,
 T_INTERVAL, T_LIST, T_STRUCT, T_UNION, T_FIXEDBINARY, T_FIXEDLIST, T_MAP, T_DURATION,
 T_LARGEBINARY, T_LARGEUTF8, T_LARGELIST) = range(1, 22)

_FIXED2BUF_TYPES = {T_DECIMAL, T_DATE, T_TIME, T_TIMESTAMP, T_INTERVAL, T_DURATION, T_FIXEDBINARY}

_BLOCK_STRUCT_SIZE = 24  # offset:i64, metaDataLength:i32, pad:i32, bodyLength:i64
_BUFFER_STRUCT_SIZE = 16  # offset:i64, length:i64
_FIELDNODE_STRUCT_SIZE = 16  # length:i64, null_count:i64


def _read_block(buf, base, i):
    off = _i64(buf, base + i * _BLOCK_STRUCT_SIZE)
    meta_len = struct.unpack_from('<i', buf, base + i * _BLOCK_STRUCT_SIZE + 8)[0]
    body_len = _i64(buf, base + i * _BLOCK_STRUCT_SIZE + 16)
    return off, meta_len, body_len


def _parse_message_at(buf, offset):
    pos = offset
    marker = struct.unpack_from('<I', buf, pos)[0]
    if marker == 0xFFFFFFFF:
        pos += 4
    meta_size = struct.unpack_from('<i', buf, pos)[0]
    pos += 4
    msg = root_table(buf[pos:pos + meta_size])
    header_type = msg.get_scalar(MSG_HEADER_TYPE, '<B', 0)
    header = msg.get_table(MSG_HEADER)
    body_start = pos + meta_size
    return header_type, header, body_start


def _field_layout(ft, top_level_name=None):
    """Pre-order flatten of one schema Field (including nested children)."""
    name = ft.get_string(F_NAME)
    type_type = ft.get_scalar(F_TYPE_TYPE, '<B', 0)
    type_table = ft.get_table(F_TYPE)
    dictionary = ft.get_table(F_DICTIONARY)
    children = ft.get_table_vector(F_CHILDREN)
    top = top_level_name if top_level_name is not None else name

    if dictionary is not None:
        idx_type = dictionary.get_table(DICTENC_INDEXTYPE)
        bw = idx_type.get_scalar(INT_BITWIDTH, '<i', 32) if idx_type else 32
        signed = bool(idx_type.get_scalar(INT_SIGNED, '<B', 1)) if idx_type else True
        dict_id = dictionary.get_scalar(DICTENC_ID, '<q', 0)
        return [{'name': top, 'kind': 'dict_index', 'n_buffers': 2,
                 'bitwidth': bw, 'signed': signed, 'dict_id': dict_id}]
    if type_type in (T_UTF8, T_LARGEUTF8):
        return [{'name': top, 'kind': 'utf8', 'n_buffers': 3,
                 'offset_bytes': 8 if type_type == T_LARGEUTF8 else 4}]
    if type_type in (T_BINARY, T_LARGEBINARY):
        return [{'name': top, 'kind': 'skip', 'n_buffers': 3}]
    if type_type == T_BOOL:
        return [{'name': top, 'kind': 'bool', 'n_buffers': 2}]
    if type_type == T_INT:
        bw = type_table.get_scalar(INT_BITWIDTH, '<i', 32)
        signed = bool(type_table.get_scalar(INT_SIGNED, '<B', 1))
        return [{'name': top, 'kind': 'int', 'n_buffers': 2, 'bitwidth': bw, 'signed': signed}]
    if type_type == T_FLOAT:
        prec = type_table.get_scalar(FLOAT_PRECISION, '<h', 2) if type_table else 2
        return [{'name': top, 'kind': 'float', 'n_buffers': 2, 'precision': prec}]
    if type_type in _FIXED2BUF_TYPES:
        return [{'name': top, 'kind': 'skip', 'n_buffers': 2}]
    if type_type in (T_LIST, T_LARGELIST):
        sub = []
        for c in children:
            sub += _field_layout(c, top)
        return [{'name': top, 'kind': 'skip', 'n_buffers': 2}] + sub
    if type_type == T_FIXEDLIST:
        sub = []
        for c in children:
            sub += _field_layout(c, top)
        return [{'name': top, 'kind': 'skip', 'n_buffers': 1}] + sub
    if type_type in (T_STRUCT, T_MAP, T_UNION):
        sub = []
        for c in children:
            sub += _field_layout(c, top)
        return [{'name': top, 'kind': 'skip', 'n_buffers': 1}] + sub
    if type_type == T_NULL:
        return [{'name': top, 'kind': 'null', 'n_buffers': 0}]
    raise NotImplementedError(f'unsupported Arrow type_type={type_type} for field {top!r}')


def _read_record_batch_columns(buf, rb_table, body_start, layout, want_names):
    nodes_buf, nodes_start, n_nodes = rb_table.get_struct_vector_raw(RB_NODES, _FIELDNODE_STRUCT_SIZE)
    bufs_buf, bufs_start, n_bufs = rb_table.get_struct_vector_raw(RB_BUFFERS, _BUFFER_STRUCT_SIZE)
    compression = rb_table.get_table(RB_COMPRESSION)

    def node_length(i):
        return _i64(nodes_buf, nodes_start + i * _FIELDNODE_STRUCT_SIZE)

    def get_buffer_raw(i):
        off = _i64(bufs_buf, bufs_start + i * _BUFFER_STRUCT_SIZE)
        length = _i64(bufs_buf, bufs_start + i * _BUFFER_STRUCT_SIZE + 8)
        raw = buf[body_start + off: body_start + off + length]
        if compression is not None and length > 0:
            return _decompress_buffer(raw)
        return raw

    buf_idx = 0
    node_idx = 0
    results = {}
    for spec in layout:
        length = node_length(node_idx)
        node_idx += 1
        n = spec['n_buffers']
        wanted = want_names is None or spec['name'] in want_names
        if spec['kind'] in ('skip', 'null') or not wanted:
            buf_idx += n
            continue
        raws = [get_buffer_raw(buf_idx + k) for k in range(n)]
        buf_idx += n
        entry = dict(spec)
        entry['length'] = length
        entry['validity'] = raws[0]
        if spec['kind'] == 'utf8':
            entry['offsets'] = raws[1]
            entry['data'] = raws[2]
        else:
            entry['data'] = raws[1]
        results[spec['name']] = entry
    return results


def _np_dtype_for_int(bitwidth, signed):
    m = {8: 'i1', 16: 'i2', 32: 'i4', 64: 'i8'}
    dt = m[bitwidth]
    if not signed:
        dt = 'u' + dt[1:]
    return np.dtype('<' + dt)


def _validity_mask(col):
    validity = col.get('validity')
    n = col['length']
    if not validity:
        return None  # all valid; caller treats None as "no mask needed"
    raw = np.frombuffer(validity, dtype=np.uint8)
    bits = np.unpackbits(raw, bitorder='little')[:n]
    return bits.astype(bool)


def _to_numpy(col):
    n = col['length']
    if col['kind'] in ('int', 'dict_index'):
        dt = _np_dtype_for_int(col['bitwidth'], col['signed'])
        return np.frombuffer(col['data'], dtype=dt, count=n).copy()
    if col['kind'] == 'float':
        dt = np.float32 if col['precision'] == 1 else np.float64
        return np.frombuffer(col['data'], dtype=dt, count=n).copy()
    if col['kind'] == 'utf8':
        off_dt = '<i8' if col.get('offset_bytes') == 8 else '<i4'
        offsets = np.frombuffer(col['offsets'], dtype=off_dt, count=n + 1)
        data = col['data']
        if n > 0:
            if offsets[0] != 0:
                raise ValueError(f'utf8 offsets buffer must start at 0, got {offsets[0]}')
            # The data buffer may legitimately be *longer* than offsets[-1]
            # (Arrow pads buffers to an alignment boundary), but it must
            # never be shorter -- that would mean truncated/corrupt string
            # data that np.frombuffer/slicing would otherwise silently
            # accept (or wrap around into the next buffer).
            if offsets[-1] > len(data):
                raise ValueError(
                    f'utf8 data buffer truncated: offsets imply at least '
                    f'{offsets[-1]} bytes, data buffer only has {len(data)}'
                )
        out = np.empty(n, dtype=object)
        for i in range(n):
            out[i] = data[offsets[i]:offsets[i + 1]].decode('utf-8')
        return out
    if col['kind'] == 'bool':
        raw = np.frombuffer(col['data'], dtype=np.uint8)
        bits = np.unpackbits(raw, bitorder='little')[:n]
        return bits.astype(bool)
    raise NotImplementedError(col['kind'])


class _FeatherFile:
    """Parsed footer/schema/dictionaries of an Arrow IPC File, ready to
    decode individual record batches (used for streaming large files)."""

    def __init__(self, buf):
        assert buf[:8] == b'ARROW1\x00\x00', 'not an Arrow IPC file (bad leading magic)'
        assert buf[-6:] == b'ARROW1', 'not an Arrow IPC file (bad trailing magic)'
        self.buf = buf
        footer_len = struct.unpack_from('<i', buf, len(buf) - 10)[0]
        footer_start = len(buf) - 10 - footer_len
        footer = root_table(buf[footer_start:footer_start + footer_len])
        schema = footer.get_table(FOOTER_SCHEMA)
        field_tables = schema.get_table_vector(SCH_FIELDS)
        self.top_names = [ft.get_string(F_NAME) for ft in field_tables]
        self.layout = []
        for ft in field_tables:
            self.layout += _field_layout(ft)

        dict_buf, dict_start, n_dicts = footer.get_struct_vector_raw(FOOTER_DICTS, _BLOCK_STRUCT_SIZE)
        self.rb_buf, self.rb_start, self.n_rbs = footer.get_struct_vector_raw(
            FOOTER_RECORDBATCHES, _BLOCK_STRUCT_SIZE)

        self.dictionaries = {}
        for i in range(n_dicts):
            off, _meta_len, _body_len = _read_block(dict_buf, dict_start, i)
            header_type, header, body_start = _parse_message_at(buf, off)
            assert header_type == MESSAGE_HEADER_DICTIONARY_BATCH
            dict_id = header.get_scalar(DB_ID, '<q', 0)
            rb = header.get_table(DB_DATA)
            dummy_layout = [{'name': '__dict__', 'kind': 'utf8', 'n_buffers': 3, 'offset_bytes': 4}]
            cols = _read_record_batch_columns(buf, rb, body_start, dummy_layout, None)
            self.dictionaries[dict_id] = _to_numpy(cols['__dict__'])

    def _decode_batch(self, rb_i, want_names):
        off, _meta_len, _body_len = _read_block(self.rb_buf, self.rb_start, rb_i)
        header_type, header, body_start = _parse_message_at(self.buf, off)
        assert header_type == MESSAGE_HEADER_RECORD_BATCH
        cols = _read_record_batch_columns(self.buf, header, body_start, self.layout, want_names)
        out = {}
        for name, col in cols.items():
            if col['kind'] == 'dict_index':
                idx = _to_numpy(col)
                dict_values = self.dictionaries[col['dict_id']]
                valid = _validity_mask(col)
                result = np.empty(len(idx), dtype=object)
                safe_idx = idx if valid is None else np.where(valid, idx, 0)
                result[:] = dict_values[safe_idx]
                if valid is not None:
                    result[~valid] = None
                out[name] = result
            else:
                arr = _to_numpy(col)
                if col['kind'] != 'utf8':
                    valid = _validity_mask(col)
                    if valid is not None and not valid.all():
                        arr = arr.astype(object)
                        arr[~valid] = None
                out[name] = arr
        return out

    def iter_batches(self, want_names=None):
        for rb_i in range(self.n_rbs):
            yield self._decode_batch(rb_i, want_names)

    def read_all(self, want_names=None):
        chunks = {name: [] for name in self.top_names if want_names is None or name in want_names}
        for batch in self.iter_batches(want_names):
            for name, arr in batch.items():
                chunks[name].append(arr)
        return {name: (np.concatenate(pieces) if len(pieces) > 1 else pieces[0])
                for name, pieces in chunks.items() if pieces}


def open_feather(path):
    with open(path, 'rb') as f:
        buf = f.read()
    return _FeatherFile(buf)


def read_feather(path, want=None):
    """Read an entire feather file into a dict of {column_name: np.ndarray}.
    `want` optionally restricts which top-level columns are materialized."""
    return open_feather(path).read_all(want)


def iter_feather_batches(path, want=None):
    """Stream a feather file's record batches without materializing the
    whole table at once (used for the large edges file)."""
    return open_feather(path).iter_batches(want)
