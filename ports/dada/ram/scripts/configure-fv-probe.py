"""Configure a dedicated, disposable uefi-dada tree. No device or network access."""
from pathlib import Path
import argparse
import re
import shutil
import struct


def replace(path, old, new):
    s = path.read_text()
    if new in s and (old not in s or new.startswith(old)): return
    if s.count(old) != 1: raise ValueError(f'unexpected source in {path}: {old[:55]}')
    path.write_text(s.replace(old, new))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tree', type=Path); p.add_argument('efi', type=Path)
    a = p.parse_args(); tree = a.tree; board = tree/'Platforms/Xiaomi/dadaPkg'
    lib = tree/'Silicon/Qualcomm/QcomPkg/Library/PlatformBootManagerLib'
    b = a.efi.read_bytes(); pe, = struct.unpack_from('<I', b, 60)
    if b[:2] != b'MZ' or b[pe:pe+6] != b'PE\0\0\x64\xaa': raise ValueError('not ARM64 PE')
    shutil.copyfile(a.efi, board/'DadaRam.efi')
    raw = '''  FILE APPLICATION = 772ee312-e97a-45fe-96fa-24ec25aab38e {
    SECTION PE32 = Platforms/Xiaomi/dadaPkg/DadaRam.efi
    SECTION UI = "DadaRamProbe"
  }'''
    replace(board/'dada.fdf','  INF SiliciumPkg/Drivers/RamManagerDxe/RamManagerDxe.inf',raw)
    # No late promotion of RAM gaps to EfiConventionalMemory. No onboard UFS/SD
    # or USB mass-storage driver in the FV or its DXE apriori list.
    for name in ('DXE.inc', 'APRIORI.inc'):
        f = board/'Include'/name; s = f.read_text()
        for module in ('UFSDxe','SdccDxe','UsbMassStorageDxe'):
            line = re.compile(r'^  INF [^\n]+/'+module+r'\.inf$', re.M)
            marker = '  # RAM-only: omitted ' + module
            if marker not in s:
                s, n = line.subn(marker, s)
                if n != 1: raise ValueError(f'unexpected {module} in {f}')
        f.write_text(s)
    f = lib/'PlatformBootManager.c'; s = f.read_text()
    start = 'EFI_DEVICE_PATH_PROTOCOL**\nEFIAPI\nDeviceBootManagerAfterConsole ('
    end = 'EFI_DEVICE_PATH_PROTOCOL**\nEFIAPI\nDeviceBootManagerOnDemandConInConnect ('
    if 'mDadaRamApp' not in s:
        assert s.count(start) == s.count(end) == 1
        headers = ['BaseLib','DxeServicesLib','MemoryAllocationLib','UefiLib','UefiRuntimeServicesTableLib']
        snippet = (Path(__file__).resolve().parents[1]/'firmware/fv-after-console.c.inc').read_text()
        f.write_text(''.join(f'#include <Library/{h}.h>\n' for h in headers)+s[:s.index(start)]+snippet+'\n'+s[s.index(end):])
    replace(lib/'PlatformBootManagerLib.inf','  RfsProtectionLib','  RfsProtectionLib\n  BaseLib\n  DxeServicesLib\n  MemoryAllocationLib\n  UefiLib\n  UefiRuntimeServicesTableLib')

if __name__ == '__main__': main()
