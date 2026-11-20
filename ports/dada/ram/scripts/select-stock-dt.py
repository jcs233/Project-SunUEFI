"""Materialize just the two original Android DT inputs selected by this boot."""
import argparse
import json
import struct
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('stock', type=Path); ap.add_argument('inventory', type=Path); ap.add_argument('out', type=Path)
a = ap.parse_args(); a.out.mkdir(parents=True, exist_ok=True)
d = json.loads(a.inventory.read_text(encoding='utf-8-sig'))
if d['ro.boot.product.hardware.sku'] != 'dada' or d['ro.board.platform'] != 'sun':
    raise ValueError('wrong board')
base_id, overlay_id = (int(d['ro.boot.' + k + '_idx']) for k in ('dtb', 'dtbo'))
v = (a.stock / 'vendor_boot.img').read_bytes()
assert v[:8] == b'VNDRBOOT' and struct.unpack_from('<I', v, 8)[0] == 4
page = struct.unpack_from('<I', v, 12)[0]
header, span = struct.unpack_from('<II', v, 2096)
align = lambda x: (x + page - 1) // page * page
start = align(header) + align(struct.unpack_from('<I', v, 24)[0]); end = start + span; trees = []
while start < end:
    magic, length = struct.unpack_from('>II', v, start)
    if magic != 0xd00dfeed or length < 40 or start + length > end: raise ValueError('bad vendor DTB')
    trees.append(v[start:start+length]); start += length
b = (a.stock / 'dtbo.img').read_bytes(); magic, total, _, size, count, table = struct.unpack_from('>6I', b)
if magic != 0xd7b7ab1e or total > len(b) or not (0 <= base_id < len(trees) and 0 <= overlay_id < count): raise ValueError('invalid tree index')
length, off = struct.unpack_from('>II', b, table + overlay_id * size)
if off + length > total: raise ValueError('invalid overlay size')
(a.out / 'stock-base.dtb').write_bytes(trees[base_id]); (a.out / 'stock-overlay.dtbo').write_bytes(b[off:off+length])
