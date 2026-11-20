#!/usr/bin/env bash
# Standalone diagnostics for already enumerated EFI media. Host files only.
set -euo pipefail
: "${FW_SRC:?pinned dada Mu checkout}"
root=$(cd "$(dirname "$0")/.." && pwd); inc="$FW_SRC/Mu_Basecore/MdePkg/Include"
out="$root/out/tests/gpt-probe"; mkdir -p "$out"
tmp=$(mktemp -d); trap 'rm -f "$tmp/probe.obj"; rmdir "$tmp"' EXIT
clang --target=aarch64-pc-windows-msvc -ffreestanding -fno-stack-protector -fno-builtin -fshort-wchar -mstrict-align -Os -Wall -Wextra -Werror -I"$inc" -I"$inc/AArch64" -c "$root/firmware/gpt-probe/main.c" -o "$tmp/probe.obj"
lld-link /subsystem:efi_application /nodefaultlib /entry:efi_main /machine:arm64 /timestamp:0 /out:"$out/GptProbe.efi" "$tmp/probe.obj"
(cd "$out" && sha256sum GptProbe.efi > SHA256SUMS)
