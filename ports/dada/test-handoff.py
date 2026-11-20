#!/usr/bin/env python3
"""Observe actual entry PCs in QEMU without executing Android or the vendor DXEs."""
import argparse
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

BASE, DT, SP, FD = 0xa8000000, 0xb7000000, 0x40900000, 0xa7100000
INITRD = 0xb7800000
REGS = (DT, 0, 0, 0)  # AArch64 boot protocol
PAGE = 4096


def check(ok, message):
    if not ok:
        raise ValueError(message)


class Debugger:
    """Minimal synchronous subset of QEMU's GDB remote protocol on a private socket."""
    def __init__(self, sock):
        self.stream = sock.makefile('rwb', buffering=0)

    def command(self, command):
        data = command.encode()
        self.stream.write(b'$' + data + b'#%02x' % (sum(data) & 255))
        check(self.stream.read(1) == b'+', 'debugger command not acknowledged')
        check(self.stream.read(1) == b'$', 'missing debugger reply')
        reply = bytearray()
        while True:
            byte = self.stream.read(1)
            if byte == b'#':
                break
            check(bool(byte) and len(reply) < 65536, 'truncated/long debugger reply')
            reply.extend(byte)
        check(int(self.stream.read(2), 16) == sum(reply) & 255, 'debugger checksum')
        self.stream.write(b'+')
        return bytes(reply)

    def breakpoint(self, address):
        check(self.command(f'Z1,{address:x},4') == b'OK', 'cannot set instruction breakpoint')

    def run_to_break(self):
        check(self.command('c').startswith((b'T05', b'S05')), 'did not hit breakpoint')
        return bytes.fromhex(self.command('g').decode())


def observe(tmp, image, dt, entry, original_pc, guard_pc, expected, fd, initrd):
    endpoint = tmp/'debug.sock'
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(8)
        proc = subprocess.Popen([
            'qemu-system-aarch64', '-M', 'virt', '-cpu', 'cortex-a76', '-m', '2560M',
            '-S', '-gdb', f'unix:{endpoint},server=on,wait=off', '-nodefaults',
            '-display', 'none', '-serial', 'none', '-monitor', 'none', '-nic', 'none',
            '-device', f'loader,file={entry},addr=0x40200000,force-raw=on,cpu-num=0',
            '-device', f'loader,file={dt},addr={DT:#x},force-raw=on',
            '-device', f'loader,file={initrd},addr={INITRD:#x},force-raw=on',
            '-device', f'loader,file={image},addr={BASE:#x},force-raw=on'], stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 6
            while not endpoint.exists():
                if proc.poll() is not None:
                    raise RuntimeError(proc.stderr.read().decode())
                if time.monotonic() > deadline:
                    raise TimeoutError('QEMU debugger did not start')
                time.sleep(0.025)
            sock.connect(str(endpoint))
            gdb = Debugger(sock)
            for addr in (original_pc, guard_pc):
                gdb.breakpoint(addr)
            regs = gdb.run_to_break()
            pc, = struct.unpack_from('<Q', regs, 32 * 8)
            check(pc == expected, f'expected PC {expected:#x}, observed {pc:#x}')
            check(struct.unpack_from('<4Q', regs) == REGS, 'changed x0..x3 at handoff')
            check(struct.unpack_from('<Q', regs, 31 * 8)[0] == SP, 'changed SP at handoff')
            # The harness masks IRQ+FIQ only. Check that the selector restored DAIF.
            check(struct.unpack_from('<I', regs, 33 * 8)[0] & 0x3c0 == 0xc0, 'changed interrupt masks')
            if pc == guard_pc:
                check(gdb.command(f'z1,{pc:x},4') == b'OK', 'cannot remove breakpoint')
                gdb.breakpoint(FD)
                regs = gdb.run_to_break()
                check(struct.unpack_from('<Q', regs, 32 * 8)[0] == FD, 'guard did not enter FD')
                for offset in (0, len(fd)-64):
                    read = gdb.command(f'm{FD+offset:x},40')
                    check(bytes.fromhex(read.decode()) == fd[offset:offset+64], 'relocated FD mismatch')
                return 'dada-guard -> Mu FD'
            return 'original GKI entry'
        finally:
            proc.kill()
            proc.wait()
            endpoint.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('stock', 'android', 'linux', 'stock-dt', 'selector-json'):
        p.add_argument('--'+flag, required=True, type=Path)
    a = p.parse_args()
    # Derive Android's destination independently from the ORIGINAL boot image.
    with a.stock.open('rb') as f:
        f.seek(PAGE + 4)
        op, = struct.unpack('<I', f.read(4))
    check(op >> 26 == 5 and not (op & (1 << 25)), 'unexpected stock GKI entry')
    stock_pc = BASE + 4 + 4 * (op & 0x3ffffff)
    meta_offset = json.loads(a.selector_json.read_text())['metadata_offset']
    with tempfile.TemporaryDirectory() as temp:
        tmp = Path(temp)
        entry = tmp/'entry.bin'
        src = tmp/'entry.S'
        src.write_text(f'''mov x0, #{DT:#x}
            mov x1, #0
            mov x2, #0
            mov x3, #0
            mov x4, #{SP:#x}
            mov sp, x4
            msr daifset, #3
            msr daifclr, #12
            mov x4, #{BASE:#x}
            br x4\n''')
        subprocess.run(['aarch64-linux-gnu-as', '-o', tmp/'entry.o', src], check=True)
        subprocess.run(['aarch64-linux-gnu-objcopy', '-O', 'binary', tmp/'entry.o', entry], check=True)
        # Only the guest's working copy gets synthetic RAM/bootmode. Never use it on a phone.
        for source, mode, config_mode, live_ram, linux in (
                (a.android, 'normal', 'normal', True, False), (a.linux, 'normal', 'normal', True, True),
                (a.linux, 'recovery', 'normal', True, False), (a.linux, 'poweroff_cg', 'normal', True, False),
                (a.linux, 'normal', 'charger', True, False), (a.linux, 'normal', 'normal', False, False)):
            with source.open('rb') as f:
                header = f.read(PAGE)
                check(header[:8] == b'ANDROID!', 'not an Android BOOT')
                n, = struct.unpack_from('<I', header, 8)
                check(0 < n < 96*1024*1024, 'invalid carrier size')
                k = f.read(n)
                check(len(k) == n, 'truncated kernel')
            wrapped, = struct.unpack_from('<I', k, 4)
            sel = 4 + 4 * (wrapped & 0x3ffffff)
            m = sel + meta_offset
            check(wrapped >> 26 == 5 and k[m:m+16] == b'SUNUEFI-SPLITv1\0', 'selector metadata missing')
            sh, sh_len, fd_len = struct.unpack_from('<QQQ', k, m+48)
            check(not sh % PAGE and fd_len == 0x300000 and sh+sh_len+fd_len <= n, 'wrong guard/FD extent')
            fd = k[sh+sh_len:sh+sh_len+fd_len]
            image, dt = tmp/'kernel.bin', tmp/'fixture.dtb'
            image.write_bytes(k)
            dt.write_bytes(a.stock_dt.read_bytes())
            if live_ram:
                subprocess.run(['fdtput', '-t', 'x', dt, '/memory', 'reg', '0','40000000','0','a0000000'], check=True)
            cmdline = 'mca_log.charge_boot_mode=0 silent_boot.mode=nonsilent mtdoops.boot_mode=0 bootmonitor.bootmode='+mode
            subprocess.run(['fdtput', '-t', 's', dt, '/chosen', 'bootargs', cmdline], check=True)
            # Realistic initrd bounds and a small, flat Android bootconfig trailer.
            config = f'androidboot.force_normal_boot = "0"\nandroidboot.mode = "{config_mode}"\n'.encode()
            ramdisk = bytes(4096) + config + struct.pack('<II', len(config), sum(config)) + b'#BOOTCONFIG\n'
            initrd = tmp/'initrd.bin'
            initrd.write_bytes(ramdisk)
            for prop, addr in [('linux,initrd-start', INITRD), ('linux,initrd-end', INITRD+len(ramdisk))]:
                subprocess.run(['fdtput', '-t', 'x', dt, '/chosen', prop, '0', f'{addr:x}'], check=True)
            result = observe(tmp, image, dt, entry, stock_pc, BASE+sh, BASE+sh if linux else stock_pc, fd, initrd)
            print(f'{source.name}  {mode:12s} config={config_mode} live_ram={live_ram} -> {result}', flush=True)


if __name__ == '__main__':
    main()
