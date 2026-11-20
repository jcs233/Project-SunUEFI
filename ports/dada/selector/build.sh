#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-2-Clause
set -euo pipefail
[[ $# == 2 ]] || { echo 'usage: build.sh FORK_ROOT OUTPUT_DIR' >&2; exit 2; }
src=$(cd -- "$(dirname -- "$0")" && pwd -P)
root=$(cd -- "$src/../../.." && pwd -P)
fork=$(cd -- "$1" && pwd -P)
req=$fork/uefi/handoff/bootselect
mkdir -p -- "$2"; out=$(cd -- "$2" && pwd -P)
tmp=$(mktemp -d -- "$out/.selector.XXXXXXXX"); trap 'rm -rf -- "$tmp"' EXIT
fail() { echo "selector: $*" >&2; exit 1; }
# Pin the actual reused sources, not a branch name; never invoke Git (partial
# clones can otherwise fetch missing objects). Allow checkout CRLF line ends.
python3 - "$req" <<'PY'
import hashlib, pathlib, sys
for ext, expected in [('c','29a23d9085abdc0a0f2ce7a421da14deed84b91dc38280afc69e94131267e62b'),
                      ('h','d428dd523c6328be0f7887f382f0dacbb21989edf5312a4f487684d0274fdfb5')]:
    p = pathlib.Path(sys.argv[1], 'BootRequest.'+ext)
    if not p.is_file() or hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
        sys.exit(f'missing or different c5928587 input: {p}')
PY
if [[ -z ${RAM_ROOT:-} ]]; then
    for d in "$root/ports/dada/ram" "$root" "$fork/ports/dada/ram"; do
        if [[ -f $d/firmware/guard/check.c ]]; then RAM_ROOT=$d; break; fi
    done
fi
[[ -f ${RAM_ROOT:-}/firmware/guard/check.c ]] || fail 'set RAM_ROOT to the dada tree containing firmware/guard'
guard=$(cd -- "$RAM_ROOT/firmware/guard" && pwd -P)
fdt=${LIBFDT_DIR:-}
if [[ -z $fdt && -n ${FW_SRC:-} ]]; then fdt=$FW_SRC/Mu_Basecore/MdePkg/Library/BaseFdtLib/libfdt/libfdt; fi
if [[ -z $fdt ]]; then
    for a in "$RAM_ROOT/.cache/libfdt.tar.gz" "$root/.cache/libfdt.tar.gz"; do
        [[ -f $a ]] || continue
        hash=$(sha256sum -- "$a"); [[ ${hash%% *} == 1193910f475fde07f3cd4fe1c1a353d69b8cedb574967134838fcdc8208d224e ]] || fail 'unexpected libfdt archive'
        tar -xzf "$a" -C "$tmp" --strip-components=1 --wildcards '*/libfdt/*'
        fdt=$tmp/libfdt; break
    done
fi
[[ -f $fdt/fdt_check.c ]] || fail 'set LIBFDT_DIR to the unpacked libfdt C source directory'
cross=${CROSS_COMPILE:-aarch64-linux-gnu-}
flags=(-Os -std=gnu11 -Wall -Wextra -Werror -ffreestanding -fno-builtin -fno-stack-protector
       -fno-pic -fno-pie -mcmodel=tiny -march=armv8-a -mgeneral-regs-only -mstrict-align
       -fno-jump-tables -ffunction-sections -fdata-sections -fno-asynchronous-unwind-tables
       -I"$req" -I"$fdt" -I"$guard")
objects=()
for f in "$src/entry.S" "$src/selector.c" "$src/mode.c" "$req/BootRequest.c" "$guard/string.c" \
         "$fdt"/{fdt,fdt_ro,fdt_addresses,fdt_check}.c; do
    obj=$tmp/$(basename "${f%.*}").o
    "${cross}gcc" "${flags[@]}" -c "$f" -o "$obj"; objects+=("$obj")
done
"${cross}ld" --gc-sections --build-id=none -T "$src/selector.ld" "${objects[@]}" -o "$tmp/selector.elf"
"${cross}objcopy" -O binary "$tmp/selector.elf" "$tmp/selector.bin"
"${cross}nm" -n "$tmp/selector.elf" > "$tmp/symbols"
python3 - "$tmp" <<'PY'
import json, pathlib, sys
d = pathlib.Path(sys.argv[1]); raw = (d/'selector.bin').read_bytes()
sym = {s[2]:int(s[0],16) for line in (d/'symbols').read_text().splitlines() if len(s:=line.split()) == 3}
m, n = sym['metadata'], sym['stack_top']
if not (sym['selector']==0 and n%4096==0 and 8192<n<65536 and 4<=len(raw)<=n-16384 and
        len(raw)%4==m%16==0 and raw[m:m+128]==bytes(128)):
    sys.exit('invalid selector file or ABI')
(d/'selector.json').write_text(json.dumps(dict(memory_bytes=n, metadata_offset=m))+'\n')
PY
mv -- "$tmp/selector.bin" "$tmp/selector.json" "$out/"
