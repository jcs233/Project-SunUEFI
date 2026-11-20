"""Fail if Mu may allocate conventional/boot/runtime RAM over fixed stock reservations.
Does not verify bootloader fixups, dynamic reservations or proprietary DXE behavior.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path


def cells(dtb, path, prop):
    r = subprocess.run(['fdtget', '-tx', dtb, path, prop], capture_output=True, text=True)
    if r.returncode:
        if 'FDT_ERR_NOTFOUND' in r.stderr: return []
        raise ValueError(r.stderr)
    return [int(x, 16) for x in r.stdout.split()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dtb'); ap.add_argument('map', type=Path); ap.add_argument('report', type=Path)
    a = ap.parse_args(); path = '/reserved-memory'
    if cells(a.dtb,path,'#address-cells') != [2] or cells(a.dtb,path,'#size-cells') != [2]: raise ValueError('expected 64-bit reg tuples')
    children = subprocess.check_output(['fdtget','-l',a.dtb,path],text=True).splitlines()
    fixed = []; dynamic = []
    for name in children:
        nums = cells(a.dtb,path+'/'+name,'reg')
        if len(nums)%4: raise ValueError('invalid reg on '+name)
        if not nums or not any((nums[i+2] or nums[i+3]) for i in range(0,len(nums),4)): dynamic.append(name)
        for i in range(0,len(nums),4):
            base, size = (nums[i]<<32)+nums[i+1], (nums[i+2]<<32)+nums[i+3]
            if size: fixed.append((name,base,base+size))
    alloc = []; conflicts = []; explicit = {}
    for m in re.finditer(r'\{\s*"([^"]+)",\s*(0x[\dA-Fa-f]+),\s*(0x[\dA-Fa-f]+),\s*(\w+),\s*(\w+),\s*\w+,\s*(\w+),',a.map.read_text()):
        name, base, size, hob, res, kind = m.groups(); base = int(base,16); size = int(size,16)
        if hob == 'AddMem' and kind == 'Reserv': explicit[name] = (base,base+size)
        if not (hob=='AddMem' and res=='SYS_MEM' and kind!='Reserv'): continue
        alloc.append(name)
        for node, start, end in fixed:
            if max(base,start)<min(base+size,end): conflicts.append({'allocatable':name,'stock':node,'start':hex(max(base,start)),'end_exclusive':hex(min(base+size,end))})
    if 'DXE_Heap' not in alloc or 'UEFI_FD' not in alloc or not fixed: raise ValueError('invalid input')
    required = {'XBL_Ramdump':'xbl_ramdump_region@b8000000','HW_Fence':'hwfence-shmem'}
    coverage = {k: any(name==n and k in explicit and explicit[k][0]<=start and explicit[k][1]>=end for name,start,end in fixed) for k,n in required.items()}
    report = {'fixed_ranges':len(fixed),'writable_regions':alloc,'conflicts':conflicts,'explicit_reservations':coverage,'dynamic_or_zero_length':dynamic}
    a.report.write_text(json.dumps(report,indent=2)+'\n'); print(f'{len(conflicts)} overlap(s); explicit coverage: {coverage}')
    return int(bool(conflicts) or not all(coverage.values()))

if __name__ == '__main__': raise SystemExit(main())
