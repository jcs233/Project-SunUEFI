#!/usr/bin/env python3
"""Unpack the shipped boot-v4 file, not just EDK's intermediate outputs."""
import argparse, hashlib, json, lzma, struct, uuid, zlib
from pathlib import Path

def must(v,s):
    if not v: raise ValueError(s)
def sha(b): return hashlib.sha256(b).hexdigest()
def u32(b,n): return struct.unpack_from('<I',b,n)[0]
def u24(b,n): return int.from_bytes(b[n:n+3],'little')
def guid(s): return uuid.UUID(s).bytes_le

def file(fv,key,kind):
    must(fv[40:44]==b'_FVH' and struct.unpack_from('<Q',fv,32)[0]==len(fv),'FV header')
    p=struct.unpack_from('<H',fv,48)[0]; ext=struct.unpack_from('<H',fv,52)[0]
    if ext: p=max(p,ext+u32(fv,ext+16))
    while (p+7)//8*8+24<=len(fv):
        p=(p+7)//8*8; h=fv[p:p+24]; sz=u24(h,20)
        if h==b'\xff'*24: break
        must(24<=sz<0xffffff and p+sz<=len(fv),'FFS size')
        if h[:16]==guid(key):
            must(h[18]==kind,'FFS type'); return fv[p+24:p+sz]
        p+=sz
    raise ValueError('missing FFS '+key)

def section(b,kind):
    pos=0
    while pos+4<=len(b):
        sz=u24(b,pos); must(4<=sz<=len(b)-pos,'section bounds')
        if b[pos+3]==kind: return b[pos:pos+sz]
        pos=(pos+sz+3)//4*4
    raise ValueError('missing section')

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('kernel_out',type=Path); p.add_argument('stock_base',type=Path); p.add_argument('guard',type=Path); p.add_argument('--image',type=Path); a=p.parse_args(); d=a.kernel_out
    b=(a.image or d/'firmware/Mu-dada-linux-ram.img').read_bytes()
    must(b[:8]==b'ANDROID!' and u32(b,40)==4 and u32(b,20)==1584,'Android boot header')
    gz=zlib.decompressobj(31); raw=gz.decompress(b[4096:4096+u32(b,8)])
    must(gz.eof and gz.unused_data==a.stock_base.read_bytes(),'not paired OTA base DTB')
    shim=a.guard.read_bytes(); must(raw[:len(shim)]==shim and raw[56:60]==b'ARM\x64' and struct.unpack_from('<Q',raw,16)[0]==len(raw),'guard/header mismatch')
    fd=raw[len(shim):]; must(len(fd)==0x300000,'FD was resized')
    s=section(file(fd,'9e21fd93-9c72-4c15-8c4b-e77f1db2d792',11),2)
    must(s[4:20]==guid('ee4e5898-3914-4259-9d6e-dc7bd79403cf'),'not EDK2 LZMA')
    inner=section(lzma.decompress(s[struct.unpack_from('<H',s,20)[0]:],format=lzma.FORMAT_ALONE),0x17)[4:]
    pe=section(file(inner,'772ee312-e97a-45fe-96fa-24ec25aab38e',9),0x10)[4:]
    must(pe==(d/'EFI/BOOT/BOOTAA64.EFI').read_bytes(),'different embedded EFI')
    must((d/'Image').read_bytes() in pe and (d/'dada.dtb').read_bytes() in pe,'GRUB memdisk lacks exact kernel or DTB')
    print(json.dumps({'boot_sha256':sha(b),'boot_bytes':len(b),'guard_bytes':len(shim),'fd_bytes':len(fd),'inner_fv_bytes':len(inner),'efi_bytes':len(pe),'efi_sha256':sha(pe),'stock_base_sha256':sha(gz.unused_data),'guard_sha256':sha(shim),'embedded_kernel_and_board_dtb_exact':True},indent=2))
if __name__=='__main__': main()
