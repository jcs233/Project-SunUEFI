#!/usr/bin/env bash
# Build the small pre-SEC gate against the same pinned libfdt as Mu.
set -euo pipefail
src=$(cd "$(dirname "$0")/../firmware/guard" && pwd)
fdt=$FW_SRC/Mu_Basecore/MdePkg/Library/BaseFdtLib/libfdt/libfdt
o=$FW_SRC/Build/dada-guard; mkdir -p "$o"; cd "$o"
gcc=${CROSS_COMPILE:-aarch64-linux-gnu-}gcc
for f in "$src"/entry.S "$src"/check.c "$src"/string.c "$fdt"/{fdt,fdt_ro,fdt_addresses,fdt_check}.c; do
  "$gcc" -Os -I"$fdt" -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie -march=armv8-a -mgeneral-regs-only -mstrict-align -fno-jump-tables -ffunction-sections -fdata-sections -c "$f" -o "$(basename "${f%.*}").o"
done
"${CROSS_COMPILE:-aarch64-linux-gnu-}ld" -nostdlib --gc-sections -T "$src/shim.ld" entry.o check.o string.o fdt.o fdt_ro.o fdt_addresses.o fdt_check.o -o shim.elf
"${CROSS_COMPILE:-aarch64-linux-gnu-}objcopy" -O binary shim.elf shim.bin
