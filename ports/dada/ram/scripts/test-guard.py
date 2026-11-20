#!/usr/bin/env python3
"""Exercise the actual arm64 shim on virt (synthetic map + inert mock FD only)."""
import argparse, ctypes, shutil, struct, subprocess as sp, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def run(*args, **kw): return sp.run(args, check=True, **kw)
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('shim',type=Path); p.add_argument('stock',type=Path); a=p.parse_args()
    shim=a.shim.read_bytes(); assert len(shim)+0x300000 == struct.unpack_from('<Q',shim,16)[0]
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp); dt=t/'fixture.dtb'; shutil.copyfile(a.stock,dt)
        run('cc','-shared','-fPIC','-o',t/'check.so',ROOT/'firmware/guard/check.c','-lfdt')
        lib=ctypes.CDLL(str(t/'check.so')); check=lib.dada_check
        check.argtypes=[ctypes.c_void_p]+[ctypes.c_uint64]*3; lib.dada_can_reset.argtypes=[ctypes.c_void_p]
        def do(expect, image=0xa8000000, fdtaddr=0x41000000):
            raw=ctypes.create_string_buffer(dt.read_bytes()); code=check(raw,image,image+len(shim)+0x300000,fdtaddr)
            if code!=expect: raise ValueError(f'expected check {expect}, got {code}')
        def put(node,prop,*cells): run('fdtput','-t','x',dt,node,prop,*[format(x,'x') for x in cells])
        do(8) # unmodified OTA DT has no usable DRAM map
        assert lib.dada_can_reset(ctypes.create_string_buffer(dt.read_bytes()))==1
        put('/memory','reg',0,0xa7000000,0,0x01000000,0,0xb90c0000,0,0x1bd63000)
        do(0); do(3,0xa7000000); do(3,fdtaddr=0xb90c0000); do(3,fdtaddr=0xa8000000)
        good=dt.read_bytes()
        put('/reserved-memory/hwfence-shmem','reg',0,0xd4e22000,0,0x1000); do(12)
        dt.write_bytes(good); put('/reserved-memory/splash_region','reg',0,0xfc801000,0,0x1000); do(13)
        dt.write_bytes(good)
        def asm(name,code):
            s=t/(name+'.S'); s.write_text(code); o=t/(name+'.o'); b=t/(name+'.bin')
            run('aarch64-linux-gnu-as','-o',o,s); run('aarch64-linux-gnu-objcopy','-O','binary',o,b); return b
        # QEMU enters through a 2-instruction trampoline exactly as if ABL supplied x0.
        trampoline=asm('entry','mov x0,#0x41000000\nmov x1,#0xa8000000\nbr x1\n')
        mock=asm('mock','mov x2,#0xa7400000\nldur w3,[x2,#-4]\ncmp w3,#197\nb.ne 1f\nadr x1,msg\nmov w0,#4\nhlt #0xf000\n1: b 1b\nmsg: .asciz "DADA_GUARD_COPIED_WHOLE_FD\\n"\n')
        fd=bytearray(0x300000); data=mock.read_bytes(); fd[:len(data)]=data; struct.pack_into('<I',fd,len(fd)-4,197)
        pkg=t/'mock-image'; pkg.write_bytes(shim+fd)
        args=['qemu-system-aarch64','-M','virt','-cpu','cortex-a76','-m','2560M','-nodefaults','-display','none','-serial','none','-monitor','none','-nic','none','-semihosting-config','enable=on,target=native', '-device',f'loader,file={trampoline},addr=0x40200000,force-raw=on,cpu-num=0','-device',f'loader,file={dt},addr=0x41000000,force-raw=on','-device',f'loader,file={pkg},addr=0xa8000000,force-raw=on']
        proc=sp.Popen(args,stderr=sp.PIPE)
        try: _,text=proc.communicate(timeout=4)
        except sp.TimeoutExpired: proc.kill(); _,text=proc.communicate()
        if b'DADA_GUARD_COPIED_WHOLE_FD' not in text: raise ValueError(repr(text))
        print('PASS: OTA placeholder refused; synthetic map, exact-boundary, collision, splash, conduit cases and actual AArch64 copy/jump verified. Not a phone test.')
if __name__=='__main__': main()
