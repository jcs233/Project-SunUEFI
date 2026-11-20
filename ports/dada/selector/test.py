#!/usr/bin/env python3
"""Host units, no firmware execution. Usage: python3 test.py FORK_ROOT"""
import ctypes as C
import os
from pathlib import Path
import struct
import subprocess as sp
import sys
import tempfile
import unittest
import zlib

SRC = Path(__file__).resolve().parent
FORK = Path(sys.argv.pop(1)).resolve()
GUARD = next(p/'firmware/guard' for p in ([Path(os.environ['RAM_ROOT'])] if 'RAM_ROOT' in os.environ else
             [SRC.parent/'ram', SRC.parents[2], FORK/'ports/dada/ram']) if (p/'firmware/guard/check.c').is_file())
REQ = FORK/'uefi/handoff/bootselect'
NORMAL = 'bootmonitor.bootmode=normal'
DT, BASE, END, SH = 0xb7000000, 0xa8000000, 0xab000000, 0xaa400000


def trailer(text):
    return b'opaque ramdisk' + text + struct.pack('<II', len(text), sum(text)) + b'#BOOTCONFIG\n'


class Selector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.work.cleanup)
        cls.d = Path(cls.work.name)
        so = cls.d/'policy.so'
        sp.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-O2', '-o', so,
                '-I', GUARD, '-I', REQ, SRC/'selector.c', SRC/'mode.c', REQ/'BootRequest.c', '-lfdt'], check=True)
        cls.lib = C.CDLL(str(so))
        cls.lib.dada_environment.argtypes = [C.c_void_p] + [C.c_uint64]*5
        cls.lib.PianoBootRequestSelect.argtypes = [C.c_void_p, C.c_void_p]
        cls.lib.dada_bootconfig.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(C.c_int)]
        cls.lib.dada_fields.argtypes = [C.c_void_p, C.c_size_t, C.c_int, C.POINTER(C.c_int)]

    def test_mode_priority(self):
        def normal(args):
            raw, n = args.encode(), C.c_int()
            return bool(self.lib.dada_fields(raw, len(raw), 0, C.byref(n)) and n.value == 1)
        self.assertTrue(normal(NORMAL+' mca_log.charge_boot_mode=0 silent_boot.mode=nonsilent mtdoops.boot_mode=0'))
        self.assertTrue(normal(NORMAL+' androidboot.force_normal_boot=1 androidboot.mode=normal'))
        self.assertFalse(normal('androidboot.mode=normal sunuefi.boot=linux'))
        for veto in [NORMAL, 'bootmonitor.bootmode=recovery', 'bootmonitor.bootmode=poweroff_cg',
                     'bootmonitor.bootmode=unknown', 'androidboot.mode=charger', 'androidboot.force_normal_boot=0',
                     'mca_log.charge_boot_mode=01', 'mca_log.charge_boot_mode', 'androidboot.bootreason=reboot,recovery']:
            for args in [NORMAL+' '+veto, veto+' '+NORMAL]:
                with self.subTest(args=args): self.assertFalse(normal(args))
        for mode in ['recovery', 'poweroff_cg', 'unknown']:
            self.assertFalse(normal('androidboot.mode=normal bootmonitor.bootmode='+mode))

    def test_bootconfig(self):
        def okay(data):
            return bool(self.lib.dada_bootconfig(data, len(data), C.byref(C.c_int(1))))
        good = trailer(b'androidboot.force_normal_boot = "1"\nvendor.charger_log = "recovery stats"\n\0')
        self.assertTrue(okay(good+b'\0\0'))
        bad_sum = bytearray(good); bad_sum[-16] ^= 1
        for bad in [bytes(bad_sum), good[:-1], b'no bootconfig', trailer(b'androidboot.mode = "charger"\n'),
                    trailer(b'bootmonitor.bootmode=poweroff_cg\n'), trailer(b'mca_log.charge_boot_mode=x'),
                    trailer(b'androidboot { mode = normal }'), trailer(b'bootmonitor.bootmode=normal')]:
            with self.subTest(bad=bad[-45:]): self.assertFalse(okay(bad))

    def test_live_ranges(self):
        rd = C.create_string_buffer(trailer(b'androidboot.hardware=qcom\n'))
        lo, hi = C.addressof(rd), C.addressof(rd)+len(rd.raw)-1
        def cells(x): return f'{x>>32:#x} {x&0xffffffff:#x}'
        def check(expected, rdprops='', bank='0 0x40000000 0 0xa0000000', extra='', dtaddr=DT, base=BASE,
                  end=END, chosen='', reserve='', extra_reg=''):
            tree = f'''/dts-v1/; {reserve} / {{ compatible="qcom,sun"; #address-cells=<2>; #size-cells=<2>;
            chosen {{ bootargs="{NORMAL}"; {rdprops} {chosen} }};
            memory {{ device_type="memory"; reg=<{bank} {extra_reg}>; }};
            reserved-memory {{ #address-cells=<2>; #size-cells=<2>; ranges;
                splash_region {{ reg=<0 0xfc800000 0 0x02b00000>; }}; {extra} }}; }};'''
            raw = sp.run(['dtc','-q','-q','-I','dts','-O','dtb'],input=tree.encode(),stdout=sp.PIPE,check=True).stdout
            self.assertEqual(self.lib.dada_environment(raw,dtaddr,base,end,SH,SH+0x308000), expected)
        def pair(a,b): return f'linux,initrd-start=<{cells(a)}>; linux,initrd-end=<{cells(b)}>;'
        check(1); check(1, pair(lo,hi), extra_reg=cells(lo)+' '+cells(hi-lo))
        check(0, pair(lo,hi))  # not RAM; never read trailer
        for a,b in [(hi,lo),(lo,lo),(BASE,BASE+1),(SH,SH+1),(END-1,END),(DT,DT+1),
                    (0xa7ffffff,BASE),(0xb90c0000,0xb90c0010)]:
            with self.subTest(a=a,b=b): check(0,pair(a,b))
        check(0,'linux,initrd-start=<0 0x41000000>;')
        check(0,dtaddr=SH); check(0,dtaddr=END-8); check(0,dtaddr=DT+1)
        check(0,base=BASE-4096); check(0,end=0xb90c0001)
        check(0,bank='0 0xa7000000 0 0x1000000 0 0xb90c0000 0 0x1bd63000')
        check(0,extra='hole { reg=<0 0xa8100000 0 1>; };'); check(0,reserve='/memreserve/ 0xb7000000 8;')
        check(0,chosen='bootargs-append="androidboot.mode=recovery";')

    def test_chosen_name(self):
        # Use a real binary-property edit; dtc can remove an explicit name
        # property when it synthesizes the same basename during compilation.
        dt = self.d/'name.dtb'
        source = b'''/dts-v1/; / { compatible="qcom,sun"; #address-cells=<2>; #size-cells=<2>;
            chosen { bootargs="bootmonitor.bootmode=normal"; };
            memory { device_type="memory"; reg=<0 0x40000000 0 0xa0000000>; };
            reserved-memory { #address-cells=<2>; #size-cells=<2>; ranges;
                splash_region { reg=<0 0xfc800000 0 0x02b00000>; }; }; };'''
        sp.run(['dtc','-q','-q','-O','dtb','-o',dt], input=source, check=True)
        for name,expected in [('chosen',1),('chosenX',0),('',0)]:
            sp.run(['fdtput','-t','s',dt,'/chosen','name',name],check=True)
            self.assertEqual(self.lib.dada_environment(dt.read_bytes(),DT,BASE,END,SH,SH+0x308000),expected)

    def test_fork_next(self):
        generation = bytes(range(16))
        def page(seq, target, gen=generation, bad=0):
            rec = bytearray(struct.pack('<16sIIQII16s8x',b'SUNUEFI-NEXTv1',1,64,seq,target,0,gen))
            struct.pack_into('<I',rec,36,zlib.crc32(rec)^bad)
            return rec.ljust(4096,b'\0')
        for a,b,target in [(page(0,0),page(1,2),2), (page(2,0),page(1,2),0), (page(1,2),page(1,1),0),
                           (page(0,0),page(9,2,bad=1),0), (page(0,0),page(8,2,bytes(16)),0)]:
            self.assertEqual(self.lib.PianoBootRequestSelect(bytes(a+b),generation),target)


if __name__ == '__main__': unittest.main()
