"""Read a full A/B OTA with the Python standard library. Only writes local files."""
import argparse
import base64
import bz2
import hashlib
import json
import lzma
import struct
import tempfile
import zipfile
from pathlib import Path


def varint(data, start):
    value = 0
    for shift in range(0, 70, 7):
        byte = data[start]
        start += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, start
    raise ValueError('invalid protobuf integer')


def fields(data):
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        wire = tag & 7
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire == 2:
            size, pos = varint(data, pos)
            if size > len(data) - pos:
                raise ValueError('truncated protobuf')
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError(f'unexpected protobuf wire type {wire}')
        yield tag >> 3, value


def props(data):
    return dict(line.split('=', 1) for line in data.decode().splitlines() if line)


def digest_stream(handle):
    return hashlib.file_digest(handle, 'sha256').digest()


def extract_image(stream, partition, base, block, destination):
    entries = list(fields(partition))
    info = dict(fields(dict(entries)[7]))
    size = info[1]
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as out:
        tmp = Path(out.name)
    try:
        with tmp.open('w+b') as out:
            out.truncate(size)
            for tag, record in entries:
                if tag != 8:
                    continue
                items = list(fields(record))
                op = dict(items)
                kind = op[1]
                extents = [dict(fields(v)) for k, v in items if k == 6]
                length = sum(e[2] * block for e in extents)
                if kind in (0, 1, 8):  # REPLACE, REPLACE_BZ, REPLACE_XZ
                    stream.seek(base + op.get(2, 0))
                    raw = stream.read(op[3])
                    if len(raw) != op[3] or (8 in op and hashlib.sha256(raw).digest() != op[8]):
                        raise ValueError('operation data hash or length mismatch')
                    data = {0: lambda b: b, 1: bz2.decompress, 8: lzma.decompress}[kind](raw)
                    if len(data) != length:
                        raise ValueError('extent size mismatch')
                elif kind == 6:  # ZERO
                    data = bytes(length)
                else:
                    raise ValueError(f'unsupported operation {kind} in {destination.name}')
                offset = 0
                for extent in extents:
                    start, count = extent[1] * block, extent[2] * block
                    if start + count > size:
                        raise ValueError('extent outside partition')
                    out.seek(start)
                    out.write(data[offset:offset + count])
                    offset += count
            out.seek(0)
            actual = digest_stream(out)
            if actual != info[2]:
                raise ValueError(f'{destination.name}: partition SHA-256 mismatch')
        tmp.replace(destination)
        return {'bytes': size, 'sha256': actual.hex()}
    finally:
        tmp.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip', type=Path)
    ap.add_argument('out', type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    names = ('boot', 'init_boot', 'vendor_boot', 'vendor_kernel_boot', 'dtbo', 'vbmeta', 'vbmeta_system', 'vbmeta_vendor', 'recovery')
    with zipfile.ZipFile(args.zip) as ota, ota.open('payload.bin') as payload:
        metadata = props(ota.read('META-INF/com/android/metadata'))
        if metadata['pre-device'] != 'dada' or metadata['ota-type'] != 'AB':
            raise ValueError('expected dada A/B package')
        properties = props(ota.read('payload_properties.txt'))
        if ota.getinfo('payload.bin').file_size != int(properties['FILE_SIZE']):
            raise ValueError('payload size mismatch')
        if digest_stream(payload) != base64.b64decode(properties['FILE_HASH']):
            raise ValueError('whole payload SHA-256 mismatch')
        payload.seek(0)
        header = payload.read(24)
        magic, major, length, siglen = struct.unpack('>4sQQI', header)
        if magic != b'CrAU' or major != 2 or length + 24 != int(properties['METADATA_SIZE']):
            raise ValueError('unexpected OTA metadata header')
        manifest = payload.read(length)
        if hashlib.sha256(header + manifest).digest() != base64.b64decode(properties['METADATA_HASH']):
            raise ValueError('metadata SHA-256 mismatch')
        parts = list(fields(manifest))
        block = dict(parts).get(3, 4096)
        images = {dict(fields(v))[1].decode(): v for k, v in parts if k == 13}
        result = {'build': metadata['post-build'], 'security_patch': metadata['post-security-patch-level'], 'payload_sha256': base64.b64decode(properties['FILE_HASH']).hex(), 'available': list(images), 'images': {}}
        for name in names:
            if name in images:
                result['images'][name] = extract_image(payload, images[name], 24 + length + siglen, block, args.out / f'{name}.img')
        (args.out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
        print(result['build'], list(result['images']))


if __name__ == '__main__':
    main()
