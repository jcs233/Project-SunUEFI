#!/usr/bin/env python3
"""Single read-only GPT disk, AAVMF -> FAT32 ESP -> Linux -> ext4 by PARTUUID.
VM fixture only. All disk and firmware-variable writes target a fresh temp directory.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2
KERNEL = ROOT / 'out/tests/rootfs-virt/Image'
ROOTFS = ROOT / 'out/rootfs/dada-busybox.ext4'
LOG = ROOT / 'out/tests/efi-gpt-rootfs.log'
drive_test = runpy.run_path(str(ROOT / 'scripts/smoke-rootfs.py'))['drive_test']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    if not KERNEL.is_file() or not ROOTFS.is_file() or ROOTFS.stat().st_size != 64*MIB:
        raise ValueError('First build the QEMU kernel and the 64 MiB development ext4 image')
    root_hash = digest(ROOTFS)
    with tempfile.TemporaryDirectory(prefix='dada-qemu-gpt-') as tmp:
        d = Path(tmp); disk = d / 'test.raw'; esp = d / 'esp.raw'
        # Synthetic positions, not a Xiaomi disk map. A small guard partition makes
        # the root nontrivial to identify; no Android image or user data is present.
        with disk.open('xb') as f: f.truncate(592*MIB)
        with esp.open('xb') as f: f.truncate(512*MIB)
        uid = str(uuid.uuid4())
        spec = (f'label: gpt\nsize=4MiB, type=L, name="fixture_guard"\n'
                f'size=512MiB, type=U, name="sunuefi_esp"\n'
                f'size=64MiB, type=L, name="sunuefi_root", uuid={uid}\n')
        run('sfdisk', '--no-reread', '--no-tell-kernel', disk, input=spec, text=True, stdout=subprocess.DEVNULL)
        table = json.loads(subprocess.check_output(['sfdisk','--json',disk]))['partitiontable']
        parts = table['partitions']; sector = table['sectorsize']
        if ([p['name'] for p in parts] != ['fixture_guard','sunuefi_esp','sunuefi_root'] or
            parts[1]['type'].lower() != 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b' or
            parts[2]['uuid'].lower() != uid or parts[1]['size']*sector != esp.stat().st_size or
            parts[2]['size']*sector != ROOTFS.stat().st_size):
            raise ValueError('Unexpected VM geometry')
        hw = ['qemu-system-aarch64','-machine','virt,gic-version=3,acpi=off','-cpu','cortex-a76',
              '-m','1024','-smp','1','-device','virtio-rng-pci','-nic','none','-display','none',
              '-monitor','none','-serial','stdio','-no-reboot']
        run(*hw,'-machine',f'dumpdtb={d}/virt.dtb',stdout=subprocess.DEVNULL)
        cfg = d / 'grub.cfg'; cfg.write_text(
            'search --no-floppy --label --set=root SUNUEFI_ESP\n'
            'devicetree /EFI/dada/virt.dtb\n'
            f'linux /EFI/dada/Image console=ttyAMA0 acpi=off root=PARTUUID={uid} '
            'rootfstype=ext4 rootflags=noload ro rootwait=15 init=/sbin/init panic=5\nboot\n')
        mods = 'normal linux fdt part_gpt fat search search_label memdisk tar boot'
        run(os.getenv('GRUB_MKSTANDALONE','grub-mkstandalone'),'-O','arm64-efi','-d',
            os.getenv('GRUB_MODULES','/usr/lib/grub/arm64-efi'),'--locales=','--fonts=','--themes=',
            '--install-modules='+mods,'--modules='+mods,'-o',d/'BOOTAA64.EFI',f'boot/grub/grub.cfg={cfg}')
        run('mformat','-i',esp,'-F','-v','SUNUEFI_ESP','::')
        run('mmd','-i',esp,'::/EFI','::/EFI/BOOT','::/EFI/dada')
        run('mcopy','-i',esp,d/'BOOTAA64.EFI','::/EFI/BOOT/BOOTAA64.EFI')
        run('mcopy','-i',esp,KERNEL,'::/EFI/dada/Image'); run('mcopy','-i',esp,d/'virt.dtb','::/EFI/dada/virt.dtb')
        with disk.open('r+b') as out:
            out.seek(parts[0]['start']*sector); out.write(b'Not an Android or installable disk.\n')
            for part, source in zip(parts[1:], (esp, ROOTFS)):
                out.seek(part['start']*sector)
                with source.open('rb') as src: shutil.copyfileobj(src, out, 4*MIB)
        verify = subprocess.check_output(['sgdisk','-v',disk],text=True)
        if 'No problems found.' not in verify: raise RuntimeError(verify)
        before = digest(disk); shutil.copyfile('/usr/share/AAVMF/AAVMF_VARS.fd', d/'vars.fd')
        drives = ['-drive','if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd',
                  '-drive',f'if=pflash,format=raw,file={d}/vars.fd','-drive',f'if=none,id=onlydisk,format=raw,readonly=on,file={disk}',
                  '-device','virtio-blk-device,drive=onlydisk,bootindex=1']
        with LOG.open('wb') as log, subprocess.Popen(hw+drives,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as proc:
            try: drive_test(proc, log, expected_partname='sunuefi_root')
            finally:
                if proc.poll() is None: proc.terminate()
                try: proc.wait(5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        if digest(disk) != before or digest(ROOTFS) != root_hash: raise RuntimeError('read-only image changed')
        (LOG.with_suffix('.json')).write_text(json.dumps(dict(test='QEMU only',gpt_verified=True,
            guest_mounted_partition='sunuefi_root',disk_readonly=True,root_partuuid=uid,
            virtual_logical_sector_bytes=sector,unchanged_disk_sha256=before,rootfs_sha256=root_hash,
            kernel_sha256=digest(KERNEL)),indent=2)+'\n')
    print('PASS: same GPT disk: FAT32 ESP -> 7.4-rc3 -> sunuefi_root ext4 ro by PARTUUID -> interactive shell; hashes unchanged.')


if __name__ == '__main__': main()
