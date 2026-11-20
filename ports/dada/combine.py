#!/usr/bin/env python3
"""Build two dada SPLITv1/RSTRv1 host files. No device, slot or installation mode.

Inputs are a trusted local selector build and a trusted host build of the
c5928587 repacker (with its sibling manifest.json). Never run as root. The
reference RAM probe is accepted by digest; a different build needs an exact
probe digest from a separately reviewed build, *as well as* the family checks.
Do not compute an approval digest from an unknown download. A matching build
manifest is a consistency check, not authentication of an untrusted compiler.
"""
import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[2]
PAGE = 4096
MIB = 1024 * 1024
FD_SIZE = 3 * MIB
STOCK_SIZE = 96 * MIB
STOCK_SHA = '7935a651b43945b020bd02744489e1f1f7eeff032bb6c245b70fd31b0c1e2a2f'
REFERENCE_PROBE = '6190a6829c98e28ee9b0f0f0d7169e4a96417af6c646af3ac9f0af5592a6a40a'
GUARD_SHA = '1f19f9b72ba94794b448c6a0f6df994f5bdd6f9507760bcdd1d9fdda7d203a62'
OTA_BASE_SHA = 'fa0062ce8e6dd5c3154b627d48a44f140e0fa8af492a76d2bb52e6a57ecb12fa'
BOARD_SHA = 'd4a5d96c4295ed7596a35411102639e31dfd9c96330a8b6abad31e2423039ad4'
CONFIG_NORMALIZED_SHA = '783e3209fb197514d6b113b71a259578894c2486b4be1201bd790b0e73a0362d'
AUDITOR_SHA_LF = 'ec9505c2ef84efcd0b1262b3f5ee1d5c1b00e5fca03c09db3b9b6dc9a3cd7774'
REPACK_COMMIT = 'c59285870c7438a7d9668cbe8f49596939fe6668'
BUILDER_SHA = '9d390bed44c11129aa862ed2e4d106f63d26021b116a2c8851a918a39adb64f1'
# Hash of the pinned builder manifest's complete sources object (canonical JSON).
SOURCES_SHA = 'c01bd63b2f3a0069eda6f7952a21765bd378455120447b39f8d8df9f2ac90c0b'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def info(data):
    return {'bytes': len(data), 'sha256': sha(data)}


def load(path, limit):
    """Reject links, special files (including FIFOs), empty and oversized inputs."""
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= limit,
            f'{path}: expected a nonempty regular file <= {limit} bytes')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags | getattr(os, 'O_BINARY', 0)), 'rb') as f:
        require(os.path.samestat(st, os.fstat(f.fileno())), f'{path}: input changed')
        data = f.read(st.st_size + 1)
    require(len(data) == st.st_size, f'{path}: input changed size')
    return data


def matches(obj, **expected):
    require(isinstance(obj, dict), 'expected a JSON object')
    for key, value in expected.items():
        require(type(obj.get(key)) is type(value) and obj[key] == value,
                f'{key}: expected {value!r}, got {obj.get(key)!r}')


def check_repacker(path):
    m = json.loads(load(path.with_name('manifest.json'), MIB))
    matches(m, arch='host', builder_sha256=BUILDER_SHA)
    sources = json.dumps(m['sources'], sort_keys=True, separators=(',', ':')).encode()
    require(sha(sources) == SOURCES_SHA, 'wrong repacker source manifest (need c5928587)')
    binary = info(load(path, 16 * MIB))
    matches(m['executable'], file=path.name, **binary)
    return {'commit': REPACK_COMMIT, 'sources_sha256': SOURCES_SHA, **binary}


def prepare_probe(args, work):
    d = args.kernel_out or args.ram_root / 'out/7.4.0-rc3-tiny'
    probe = load(args.probe or d / 'firmware/Mu-dada-linux-ram.img', 16 * MIB)
    probe_sha = sha(probe)
    require(probe_sha == (args.rebuilt_probe_sha256 or REFERENCE_PROBE),
            'probe SHA mismatch: use the reference or a separately reviewed rebuild')
    require(probe[:8] == b'ANDROID!' and struct.unpack_from('<I', probe, 20)[0] == 1584
            and struct.unpack_from('<I', probe, 40)[0] == 4, 'expected a boot-v4 RAM probe')
    n, = struct.unpack_from('<I', probe, 8)
    require(0 < n <= len(probe) - PAGE, 'invalid RAM probe kernel extent')
    gz = zlib.decompressobj(31)
    raw = gz.decompress(probe[PAGE:PAGE+n], FD_SIZE + MIB + 1)
    require(gz.eof and FD_SIZE < len(raw) <= FD_SIZE + MIB, 'invalid guard+FD gzip stream')
    guard, fd, base = raw[:-FD_SIZE], raw[-FD_SIZE:], gz.unused_data
    require(sha(guard) == GUARD_SHA and sha(base) == OTA_BASE_SHA, 'wrong guard or OTA base DTB')

    # The full .config embeds the build directory; it is not a cross-host pin.
    # Normalize only the tiny initramfs list path, not any Kconfig options.
    config = load(d / 'kernel.config', MIB).replace(b'\r\n', b'\n')
    normalized, count = re.subn(rb'(?m)^CONFIG_INITRAMFS_SOURCE="[^"\n]+/build-7\.4\.0-rc3-tiny/initramfs\.list"$',
                                b'CONFIG_INITRAMFS_SOURCE="<tiny>"', config)
    require(count == 1 and sha(normalized) == CONFIG_NORMALIZED_SHA, 'not the reviewed tiny kernel config')
    tree = load(d / 'dada.dtb', MIB)
    kernel = load(d / 'Image', 16 * MIB)
    efi = load(d / 'EFI/BOOT/BOOTAA64.EFI', 16 * MIB)
    require(sha(tree) == BOARD_SHA and kernel[56:60] == b'ARMd' and
            b'Linux version 7.4.0-rc3 ' in kernel and b'DADA_RAM_PROBE' in kernel,
            'wrong dada board DT or tiny RAM-probe kernel')

    # Audit snapshots of precisely the bytes used below, not yesterday's JSON
    # or an intermediate FD. Both DTs are build inputs, never a live device DT.
    auditor = load(args.ram_root / 'scripts/audit-fv-probe.py', MIB).replace(b'\r\n', b'\n')
    require(sha(auditor) == AUDITOR_SHA_LF, 'unreviewed audit-fv-probe.py')
    (work / 'EFI/BOOT').mkdir(parents=True)
    for name, data in [('audit.py', auditor), ('probe.img', probe), ('base.dtb', base),
                       ('guard.bin', guard), ('fd.bin', fd), ('Image', kernel),
                       ('dada.dtb', tree), ('EFI/BOOT/BOOTAA64.EFI', efi)]:
        (work / name).write_bytes(data)
    audit = json.loads(subprocess.check_output([sys.executable, '-I', '-B', 'audit.py', '.',
                                                'base.dtb', 'guard.bin', '--image', 'probe.img'], cwd=work))
    matches(audit, boot_sha256=probe_sha, boot_bytes=len(probe), guard_sha256=GUARD_SHA,
            guard_bytes=len(guard), fd_bytes=FD_SIZE, stock_base_sha256=OTA_BASE_SHA,
            embedded_kernel_and_board_dtb_exact=True, efi_sha256=sha(efi), efi_bytes=len(efi))
    # The FV audit established exact equality with the GUID-selected embedded PE.
    app = struct.pack('<16sIIQ32s', b'SUNUEFI-APPv1', 1, 64, len(efi), hashlib.sha256(efi).digest()) + efi
    (work / 'app.bin').write_bytes(app)
    return {'kind': 'reference' if probe_sha == REFERENCE_PROBE else 'reviewed-rebuild',
            'audit': audit, 'auditor_sha256_lf': AUDITOR_SHA_LF, 'fd': info(fd),
            'kernel': info(kernel), 'board_dtb': info(tree), 'config_normalized_sha256': sha(normalized),
            'app': info(app), 'next_generation_hex': sha(app)[:32]}


def prepare_selector(directory, work):
    data = load(directory / 'selector.bin', 65536)
    manifest = load(directory / 'selector.json', 65536)
    m = json.loads(manifest)
    memory = m.get('memory_bytes', m.get('selector_memory_bytes'))
    offset = m['metadata_offset']
    for key in ('memory_bytes', 'selector_memory_bytes'):
        if key in m:
            matches(m, **{key: memory})
    require(type(memory) is int and 8192 < memory < 65536 and memory % PAGE == 0,
            'selector memory must place the guard on a 4 KiB boundary')
    require(type(offset) is int and offset % 16 == 0 and 4 <= offset <= len(data)-128
            and any(data[:offset])
            and data[offset:offset+128] == bytes(128) and len(data) % 4 == 0
            and len(data) <= memory, 'invalid selector metadata slot or size')
    for key, value in [('selector_bytes', len(data)), ('selector_sha256', sha(data)),
                       ('sha256', sha(data)), ('file_bytes', len(data))]:
        if key in m:
            matches(m, **{key: value})
    (work / 'selector.bin').write_bytes(data)
    return {**info(data), 'json_sha256': sha(manifest), 'memory_bytes': memory, 'metadata_offset': offset}


def native(tool, action, source, *opts):
    # Always select the ordinary-file interface, including for request/preview.
    command = [tool, action, '--input', source, *opts]
    result = json.loads(subprocess.check_output([str(x) for x in command]))
    matches(result, device_operation_performed=False)
    return result


def check_layout(path, span, selector, probe):
    sel = align_page(span) + 2 * PAGE
    with path.open('rb') as f:
        f.seek(PAGE + sel + selector['metadata_offset'])
        meta = f.read(128)
    magic, version, size, actual_sel, actual_span = struct.unpack_from('<16sIIQQ', meta)
    shim, shim_size, fd_size, app, app_size, total = struct.unpack_from('<6Q', meta, 48)
    require((magic.rstrip(b'\0'), version, size, actual_sel, actual_span) ==
            (b'SUNUEFI-SPLITv1', 1, 128, sel, span), 'wrong SPLITv1 metadata')
    require(shim == sel + selector['memory_bytes'] and shim % PAGE == 0 and
            shim_size == probe['audit']['guard_bytes'] and fd_size == FD_SIZE and
            app == (shim + shim_size + fd_size + 15) // 16 * 16 and app_size == probe['app']['bytes']
            and meta[96:].hex() == probe['app']['sha256'], 'wrong shim/FD/APP layout or generation')
    return {'kernel_relative_selector': sel, 'kernel_relative_shim': shim, 'kernel_relative_app': app,
            'kernel_bytes': total}


def align_page(n):
    return (n + PAGE - 1) // PAGE * PAGE


def generated_boot_hash(image):
    """Only the exact add_avb() producer layout, not a generic AVB editor."""
    require(len(image) == STOCK_SIZE, 'wrong generated carrier size')
    magic, major, minor, covered, vb, size, reserved = struct.unpack_from('>4sIIQQQ28s', image, len(image)-64)
    require((magic, major, minor, reserved) == (b'AVBf', 1, 0, bytes(28)), 'unexpected generated footer')
    kernel, ramdisk = struct.unpack_from('<II', image, 8)
    signature, = struct.unpack_from('<I', image, 1580)
    require(covered == PAGE + sum(map(align_page, (kernel, ramdisk, signature))) and
            vb == align_page(covered) and 256 + 168 <= size <= 65536 and
            vb + align_page(size) <= len(image) - PAGE, 'unexpected generated AVB extents')
    v = image[vb:vb+size]
    desc_len, rollback = struct.unpack_from('>QQ', v, 104)
    aux = (desc_len + 63) // 64 * 64
    require(168 <= desc_len and 256 + aux == size, 'unexpected generated descriptor range')

    # Whitelist the complete c5928587 header: algorithm NONE, empty auth/key
    # regions, descriptors at aux+0, and the producer's 28-byte release marker.
    header = bytearray(256)
    struct.pack_into('>4sIIQQI', header, 0, b'AVB0', 1, 0, 0, aux, 0)
    struct.pack_into('>QQ', header, 104, desc_len, rollback)
    header[128:156] = b'piano-boot-repack file-mode 1'[:28]
    require(v[:256] == header and not any(v[256+desc_len:]), 'not generated unsigned AVB NONE')

    # First descriptor is the *only* hash: boot, unsalted SHA-256, 32 bytes,
    # no flags or trailing data. Later descriptors are copied stock properties.
    prefix = struct.pack('>QQQ32sIIII60x4s', 2, 152, covered, b'sha256', 4, 0, 32, 0, b'boot')
    require(v[256:256+len(prefix)] == prefix, 'unexpected boot hash name, salt, flags or length')
    at, end = 256 + 168, 256 + desc_len
    while at < end:
        require(at + 16 <= end, 'short property descriptor')
        tag, n = struct.unpack_from('>QQ', v, at)
        require(tag == 0 and n >= 18 and n % 8 == 0 and at + 16 + n <= end,
                'non-property or truncated trailing descriptor')
        at += 16 + n
    return covered, vb, size, vb + 256 + len(prefix)


def next_record(generation, sequence, target):
    record = bytearray(struct.pack('<16sIIQII16s8x', b'SUNUEFI-NEXTv1', 1, 64, sequence,
                                   target, 0, bytes.fromhex(generation)))
    struct.pack_into('<I', record, 36, zlib.crc32(record))
    return record


def repair_generated_pair(default, linux, span, generation, packed_sha, request_sha):
    """Only called on this transaction's private, just-produced file pair."""
    next_at = PAGE + align_page(span)  # native first update replaces record 0
    with default.open('rb') as af, linux.open('r+b') as bf:
        with mmap.mmap(af.fileno(), 0, access=mmap.ACCESS_READ) as a, \
                mmap.mmap(bf.fileno(), 0, access=mmap.ACCESS_READ) as b:
            require(len(a) == len(b) == STOCK_SIZE and sha(a) == packed_sha and sha(b) == request_sha,
                    'images do not match this repack/request transaction')
            covered, vb, size, digest_at = generated_boot_hash(a)
            require(next_at + 2 * PAGE <= covered and
                    a[next_at:next_at+64] == next_record(generation, 0, 0) and
                    b[next_at:next_at+64] == next_record(generation, 1, 2), 'unexpected first NEXT record')
            # This includes the other NEXT page, every payload, padding, full
            # vbmeta (including its digest and any salt) and the partition footer.
            for start, end in ((0, next_at), (next_at + 64, len(a))):
                for at in range(start, end, MIB):
                    stop = min(at + MIB, end)
                    require(a[at:stop] == b[at:stop], 'request modified bytes outside one NEXT record')
            old = hashlib.sha256(memoryview(a)[:covered]).digest()
            new = hashlib.sha256(memoryview(b)[:covered]).digest()
            require(a[digest_at:digest_at+32] == old and old != new, 'incorrect default boot digest')
            # Predict the final *whole-file* SHA before the single 32-byte write.
            final_sha = hashlib.sha256(memoryview(b)[:digest_at])
            final_sha.update(new)
            final_sha.update(memoryview(b)[digest_at+len(new):])
        bf.seek(digest_at)
        require(bf.write(new) == len(new), 'short boot digest write')
    return {'algorithm': 'NONE', 'boot_hash_algorithm': 'sha256', 'salt_bytes': 0,
            'covered_offset': 0, 'covered_bytes': covered, 'vbmeta_offset': vb, 'vbmeta_bytes': size,
            'digest_file_offset': digest_at, 'next_record_file_offset': next_at,
            'request_only_next_record_changed': True, 'native_request_file_sha256': request_sha,
            'default_descriptor_digest': old.hex(), 'linux_descriptor_digest': new.hex(),
            'expected_rehashed_file_sha256': final_sha.hexdigest()}


def compare_restored(stock, restored):
    with stock.open('rb') as a, restored.open('rb') as b:
        while True:
            chunk = a.read(MIB)
            require(chunk == b.read(MIB), 'restored file differs from the complete stock input')
            if not chunk:
                break


def build(args, work, release):
    tool = args.repacker.absolute()
    provenance = check_repacker(tool)
    probe = prepare_probe(args, work)
    selector = prepare_selector(args.selector_dir, work)
    stock = work / 'stock.img'
    source = load(args.stock or args.ram_root / 'out/stock/OS4.0.4.0.XOCCNXM/boot.img', STOCK_SIZE)
    require(len(source) == STOCK_SIZE and sha(source) == STOCK_SHA, 'not the verified dada OTA stock BOOT')
    stock.write_bytes(source)
    del source
    original = native(tool, 'probe', stock)
    matches(original, status='FILE_PROBED', header_version=4, wrapped=False, source_sha256=STOCK_SHA,
            avb_hash_matches=True, boot_source_confirm_required=False, boot_bytes=STOCK_SIZE)
    default = release / 'combined-stock.img'
    linux = release / 'combined-linux.img'
    packed = native(tool, 'repack', stock, '--output', default, '--selector', work / 'selector.bin',
                    '--selector-memory-bytes', selector['memory_bytes'], '--selector-metadata-offset',
                    selector['metadata_offset'], '--shim', work / 'guard.bin', '--fd', work / 'fd.bin',
                    '--app', work / 'app.bin')
    matches(packed, status='FILE_REPACKED_NOT_DEVICE_VERIFIED', source_sha256=STOCK_SHA)
    request = native(tool, 'request', default, '--target', 'linux', '--output', linux)
    matches(request, status='FILE_REQUEST_SAVED', target=2, sequence=1, crc_valid=True)

    avb = repair_generated_pair(default, linux, original['image_span'], probe['next_generation_hex'],
                                packed['output_sha256'], request['file_sha256'])
    results = {}
    for path, target, seq in [(default, 0, 0), (linux, 2, 1)]:
        with path.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        expected_sha = avb['expected_rehashed_file_sha256'] if target else packed['output_sha256']
        require(digest == expected_sha, 'final file differs from the verified byte ranges')
        wrapped = native(tool, 'probe', path)
        matches(wrapped, status='FILE_PROBED', wrapped=True, source_sha256=digest, boot_bytes=STOCK_SIZE,
                avb_present=True, avb_hash_present=True, avb_hash_matches=True)
        layout = check_layout(path, original['image_span'], selector, probe)
        preview = native(tool, 'request', path, '--target', 'linux' if target else 'android', '--preview')
        matches(preview, status='FILE_REQUEST_PREVIEW', target=target, sequence=seq, crc_valid=True,
                persistent=True, file_sha256=digest)
        restored = work / 'restored.img'
        back = native(tool, 'restore', path, '--output', restored)
        matches(back, status='FILE_RESTORED_BYTE_EQUAL', boot_bytes=STOCK_SIZE, output_sha256=STOCK_SHA)
        compare_restored(stock, restored)
        restored.unlink()
        results[path.name] = {'sha256': digest, 'bytes': STOCK_SIZE, 'layout': layout,
                              'next_target': target, 'next_sequence': seq, 'next_crc_valid': True,
                              'avb_hash_matches': wrapped['avb_hash_matches'],
                              'restore_catalog_bytes': back['restore_catalog_bytes'],
                              'restored_sha256': STOCK_SHA, 'full_input_byte_equal': True}
    return {'schema_version': 1, 'status': 'HOST_FILES_VERIFIED', 'device_operation_performed': False,
            'combined_device_boot_verified': False, 'oem_signed': False, 'repacker': provenance,
            'stock': {'sha256': STOCK_SHA, 'bytes': STOCK_SIZE, 'avb_hash_matches': True},
            'probe': probe, 'selector': selector, 'unsigned_avb': avb, 'outputs': results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    bundled = Path(__file__).resolve().parent / 'ram'
    p.add_argument('--ram-root', type=Path,
                   default=bundled if (bundled / 'scripts/audit-fv-probe.py').is_file() else ROOT,
                   help='RAM workspace; default: adjacent ram/ in the fork, otherwise repository root')
    p.add_argument('--stock', type=Path, help='verified full OTA boot.img (default: under --ram-root)')
    p.add_argument('--kernel-out', type=Path, help='tiny build directory (default: out/7.4.0-rc3-tiny under --ram-root)')
    p.add_argument('--probe', type=Path, help='boot-v4 RAM probe (default: firmware/Mu-dada-linux-ram.img under kernel-out)')
    p.add_argument('--rebuilt-probe-sha256', help='independently approved complete probe digest for a trusted rebuild')
    p.add_argument('--repacker', type=Path, required=True, help='trusted host piano-boot-repack, alongside its build manifest.json')
    p.add_argument('--selector-dir', type=Path, required=True, help='trusted dada selector.bin and generated selector.json')
    p.add_argument('--out', type=Path, required=True, help='NEW local directory, with an existing parent; never overwrite')
    args = p.parse_args()
    dest = args.out.absolute()
    try:
        require(not os.path.lexists(dest), f'output already exists: {dest}')
        with tempfile.TemporaryDirectory(dir=dest.parent, prefix='.dada-incomplete-') as tmp:
            work = Path(tmp)
            release = work / 'verified'
            release.mkdir()
            evidence = build(args, work, release)
            report = json.dumps(evidence, indent=2, sort_keys=True) + '\n'
            (release / 'evidence.json').write_text(report, encoding='utf-8')
            require(not os.path.lexists(dest), 'output appeared during build')
            release.rename(dest)  # one same-filesystem commit, including the report
    except (OSError, ValueError, KeyError, TypeError, struct.error, zlib.error, subprocess.CalledProcessError) as exc:
        p.exit(1, f'combine: {exc}\n')
    print(report, end='')


if __name__ == '__main__':
    main()
