#!/usr/bin/env python3
"""Boot the ARM64 read-only GPT checker under AAVMF against three synthetic disks."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/tests/gpt-probe'


def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def run(*args, **kw): return subprocess.run(args, check=True, **kw)


def fixture(file, sector, corrupt=False):
    with file.open('xb') as f: f.truncate(32 << 20)
    run('sfdisk','--sector-size',str(sector),'--no-tell-kernel','--no-reread',file, text=True,
        input='label: gpt\nsize=8MiB, type=L, name="userdata"\nsize=4MiB, type=U, name="sunuefi_esp"\nsize=6MiB, type=L, name="sunuefi_root"\n', stdout=subprocess.DEVNULL)
    t=json.loads(subprocess.check_output(['sfdisk','--sector-size',str(sector),'--json',file]))['partitiontable']
    parts=t['partitions']; pos=t['firstlba']; gaps=[]
    for p in parts: gaps.append(p['start']-pos); pos=p['start']+p['size']
    gaps.append(t['lastlba']+1-pos)
    if corrupt:
        # Corrupt only the backup header's CRC field, in a freshly created regular file.
        with file.open('r+b') as f:
            off=file.stat().st_size-sector+16; f.seek(off); val=f.read(1)[0]; f.seek(off); f.write(bytes([val^1]))
    return f'DADA_GPT_OK sector={sector} entries_used=3 userdata=1 esp=1 root=1 max_gap_lbas={max(gaps)} userdata_first={parts[0]["start"]} userdata_last={parts[0]["start"]+parts[0]["size"]-1}'


def main():
    app=OUT/'GptProbe.efi'; assert app.is_file()
    with tempfile.TemporaryDirectory(prefix='dada-read-only-gpt-') as td:
        d=Path(td); esp=d/'efi.raw'
        with esp.open('xb') as f: f.truncate(64<<20)
        run('mformat','-i',esp,'-F','::');run('mmd','-i',esp,'::/EFI','::/EFI/BOOT'); run('mcopy','-i',esp,app,'::/EFI/BOOT/BOOTAA64.EFI')
        disks=[(esp,512)]; want=[]
        for idx,(bs,bad) in enumerate([(512,False),(4096,False),(4096,True)]):
            p=d/f'disk{idx}.raw'; msg=fixture(p,bs,bad); disks.append((p,bs))
            if not bad: want.append(msg)
        before=[sha(p) for p,_ in disks];shutil.copyfile('/usr/share/AAVMF/AAVMF_VARS.fd',d/'vars.fd')
        q=['qemu-system-aarch64','-machine','virt,gic-version=3','-cpu','cortex-a76','-m','512','-nic','none','-display','none','-monitor','none','-serial','stdio','-no-reboot',
           '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd','-drive',f'if=pflash,format=raw,file={d}/vars.fd']
        for i,(p,bs) in enumerate(disks):
            dev=f'virtio-blk-pci,drive=d{i},logical_block_size={bs},physical_block_size={bs}'+(',bootindex=1' if i==0 else '')
            q+=['-drive',f'if=none,id=d{i},format=raw,readonly=on,file={p}','-device',dev]
        with subprocess.Popen(q,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as proc, selectors.DefaultSelector() as sel:
            try:
                sel.register(proc.stdout,selectors.EVENT_READ); buf=b''; stop=time.monotonic()+65
                while time.monotonic()<stop and b'DADA_GPT_DONE verified=2 unverified=2\r\n' not in buf:
                    if sel.select(1):
                        data=os.read(proc.stdout.fileno(),8192)
                        if not data: break
                        buf+=data
                    if proc.poll() is not None: break
            finally:
                if proc.poll() is None: proc.terminate()
                try: proc.wait(5)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
        log=OUT/'qemu.log';log.write_bytes(buf)
        # AAVMF may dispatch the removable app once before connecting the remaining disks.
        buf=buf.rsplit(b'DADA_GPT_BEGIN',1)[-1]
        if (not all(x.encode() in buf for x in want) or buf.count(b'DADA_GPT_OK sector=')!=2 or
            b'DADA_GPT_DONE verified=2 unverified=2' not in buf or buf.count(b'DADA_GPT_UNVERIFIED')!=2):
            raise RuntimeError(f'Expected two matching GPTs; raw FAT boot disk and broken backup must not qualify. See {log}')
        if before!=[sha(p) for p,_ in disks]: raise RuntimeError('Fixture changed')
        print('PASS: AArch64 EFI, 512/4096-byte GPTs agree with sfdisk, corrupt backup and bare FAT rejected; all four disk hashes unchanged.')


if __name__=='__main__': main()
