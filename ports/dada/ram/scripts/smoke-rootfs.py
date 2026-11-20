#!/usr/bin/env python3
"""AAVMF -> GRUB -> 7.4-rc3 -> readonly ext4 /sbin/init + local shell. No physical devices."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time


def drive_test(proc, log, expected_partname=None):
    sel = selectors.DefaultSelector(); sel.register(proc.stdout, selectors.EVENT_READ)
    seen = b''; phase = 0; deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            if not sel.select(1):
                if proc.poll() is not None: break
                continue
            data = os.read(proc.stdout.fileno(), 16384)
            if not data: break
            log.write(data); log.flush(); seen = (seen + data)[-131072:]
            if phase == 0 and b'press Enter to activate this console' in seen:
                proc.stdin.write(b'\n'); proc.stdin.flush(); phase = 1
            if phase == 1 and b'/ # ' in seen:
                proc.stdin.write(b'echo ROOTFS_SHELL_$(readlink /proc/1/exe)_$(tr "\\000" " " </proc/1/cmdline | cut -d" " -f2)_$(id -u)\n'); proc.stdin.flush(); phase = 2
            if phase == 2 and re.search(rb'(?:^|[\r\n])ROOTFS_SHELL_/bin/busybox_init_0[\r\n]', seen):
                if not re.search(rb'DADA_ROOTFS kernel=7\.4\.0-rc3 efi=yes root_type=ext4 options=ro(?:,|\s)',seen):
                    raise RuntimeError('guest shell present, but wrong kernel/EFI/root mount')
                if expected_partname is None: return
                # Read the kernel's actual mounted root device, not just the requested cmdline.
                cmd = b"mm=$(awk '$5==\"/\" {print $3; exit}' /proc/self/mountinfo); p=$(readlink -f /sys/dev/block/$mm); "
                cmd += b"echo ROOTVOL_$(grep '^PARTNAME=' \"$p/uevent\")_DISKRO_$(cat \"$p/../ro\")\n"
                proc.stdin.write(cmd); proc.stdin.flush(); phase = 3
            if phase == 3 and re.search(rb'(?:^|[\r\n])ROOTVOL_PARTNAME=' + re.escape(expected_partname.encode()) + rb'_DISKRO_1[\r\n]', seen):
                return
        raise RuntimeError('guest did not confirm EFI, ext4 and interactive PID-1 shell test; see log')
    finally:
        sel.close()


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('kernel', type=Path); p.add_argument('ext4', type=Path); p.add_argument('log', type=Path); a=p.parse_args()
    if not a.kernel.is_file() or not a.ext4.is_file(): raise ValueError('regular images required')
    digest = hashlib.sha256(a.ext4.read_bytes()).digest()
    mk=os.getenv('GRUB_MKSTANDALONE','grub-mkstandalone'); mods=os.getenv('GRUB_MODULES','/usr/lib/grub/arm64-efi')
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp); boot=t/'esp/EFI/BOOT'; boot.mkdir(parents=True)
        hw=['qemu-system-aarch64','-machine','virt,gic-version=3,acpi=off','-cpu','cortex-a76','-smp','1','-m','1024','-device','virtio-rng-pci','-nic','none','-display','none','-monitor','none','-serial','stdio','-no-reboot']
        subprocess.run(hw+['-machine',f'dumpdtb={t}/virt.dtb'],check=True,stdout=subprocess.DEVNULL)
        (t/'grub.cfg').write_text('devicetree (memdisk)/virt.dtb\nlinux (memdisk)/Image console=ttyAMA0 acpi=off root=/dev/vda rootfstype=ext4 rootflags=noload ro rootwait=15 init=/sbin/init panic=5\nboot\n')
        subprocess.run([mk,'-O','arm64-efi','-d',mods,'--locales=','--fonts=','--themes=','--install-modules=normal linux fdt memdisk tar boot','--modules=normal linux fdt memdisk tar','-o',boot/'BOOTAA64.EFI',f'boot/grub/grub.cfg={t}/grub.cfg',f'Image={a.kernel}',f'virt.dtb={t}/virt.dtb'],check=True)
        shutil.copyfile('/usr/share/AAVMF/AAVMF_VARS.fd', t/'vars.fd')
        # Only the root disk has a virtio-MMIO transport. Linux was built without virtio-pci;
        # AAVMF uses a separate PCI disk for its ESP. /dev/vda is VM-specific, not a phone name.
        disks=['-drive','if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd','-drive',f'if=pflash,format=raw,file={t}/vars.fd','-drive',f'if=none,format=raw,id=esp,file=fat:rw:{t}/esp','-device','virtio-blk-pci,drive=esp,bootindex=1','-drive',f'if=none,id=rootfs,format=raw,readonly=on,file={a.ext4.resolve()}','-device','virtio-blk-device,drive=rootfs']
        with a.log.open('wb') as log, subprocess.Popen(hw+disks,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as proc:
            try: drive_test(proc,log)
            finally:
                if proc.poll() is None: proc.terminate()
                try: proc.wait(5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
    if hashlib.sha256(a.ext4.read_bytes()).digest()!=digest: raise RuntimeError('rootfs image changed')
    print('PASS: EFI -> 7.4-rc3 -> ext4 ro -> /sbin/init -> interactive local shell; filesystem hash unchanged.')

if __name__=='__main__': main()
