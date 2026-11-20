#!/usr/bin/env bash
# Standalone GRUB: stage to a local directory only, never mount or touch an ESP.
set -euo pipefail
: "${KERNEL_OUT:?directory containing Image, dada.dtb and SHA256SUMS}"
cd "$KERNEL_OUT"
sha256sum -c SHA256SUMS
test "$(fdtget dada.dtb / compatible)" = 'xiaomi,dada qcom,sm8750'
mk=${GRUB_MKSTANDALONE:-grub-mkstandalone}; mods=${GRUB_MODULES:-/usr/lib/grub/arm64-efi}
tmp=$(mktemp -d); trap 'rm -f "$tmp/grub.cfg" "$tmp/BOOTAA64.EFI"; rmdir "$tmp"' EXIT
cat >"$tmp/grub.cfg" <<'GRUB'
# Pass the board tree BEFORE EFI-stub entry. Both files live in GRUB's memdisk.
if devicetree (memdisk)/dada.dtb; then
    if linux (memdisk)/Image acpi=off rdinit=/init maxcpus=1 console=tty0 clk_ignore_unused pd_ignore_unused regulator_ignore_unused panic=10; then
        boot
    fi
fi
echo 'dada RAM probe could not start. No installation was attempted.'
GRUB
"$mk" -O arm64-efi -d "$mods" --locales='' --fonts='' --themes='' --install-modules='normal linux fdt memdisk tar echo boot test' --modules='normal linux fdt memdisk tar' -o "$tmp/BOOTAA64.EFI" "boot/grub/grub.cfg=$tmp/grub.cfg" "Image=$PWD/Image" "dada.dtb=$PWD/dada.dtb"
mkdir -p EFI/BOOT; cp "$tmp/BOOTAA64.EFI" EFI/BOOT/BOOTAA64.EFI
sha256sum EFI/BOOT/BOOTAA64.EFI >efi.sha256
