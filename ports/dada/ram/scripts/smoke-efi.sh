#!/usr/bin/env bash
# Exercise the real EFI stub + embedded initramfs on virt; never boot the phone DTB on QEMU.
set -euo pipefail
: "${IMAGE:?absolute kernel Image}" "${LOG:?absolute output log}"
mk=${GRUB_MKSTANDALONE:-grub-mkstandalone}; mods=${GRUB_MODULES:-/usr/lib/grub/arm64-efi}
tmp=$(mktemp -d); trap 'rm -f "$tmp/esp/EFI/BOOT/BOOTAA64.EFI" "$tmp/grub.cfg" "$tmp/virt.dtb" "$tmp/vars.fd"; rmdir "$tmp/esp/EFI/BOOT" "$tmp/esp/EFI" "$tmp/esp" "$tmp"' EXIT
mkdir -p "$tmp/esp/EFI/BOOT"
args=(-machine virt,gic-version=3,acpi=off -cpu cortex-a76 -smp 1 -m 1024 -device virtio-rng-pci -nic none -nographic -no-reboot)
qemu-system-aarch64 "${args[@]}" -machine "dumpdtb=$tmp/virt.dtb" >/dev/null
cat >"$tmp/grub.cfg" <<'GRUB'
echo 'Starting GRUB EFI Linux smoke test (virtual machine only)'
if devicetree (memdisk)/virt.dtb; then
    if linux (memdisk)/Image console=ttyAMA0 earlycon=pl011,mmio32,0x09000000 acpi=off rdinit=/init; then
        boot
    fi
fi
GRUB
"$mk" -O arm64-efi -d "$mods" --locales='' --fonts='' --themes='' --install-modules='normal linux fdt memdisk tar echo boot test' --modules='normal linux fdt memdisk tar' -o "$tmp/esp/EFI/BOOT/BOOTAA64.EFI" "boot/grub/grub.cfg=$tmp/grub.cfg" "Image=$IMAGE" "virt.dtb=$tmp/virt.dtb"
cp /usr/share/AAVMF/AAVMF_VARS.fd "$tmp/vars.fd"
: >"$LOG"
qemu-system-aarch64 "${args[@]}" -drive if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd -drive "if=pflash,format=raw,file=$tmp/vars.fd" -drive "if=none,format=raw,id=esp,file=fat:rw:$tmp/esp" -device virtio-blk-pci,drive=esp >"$LOG" 2>&1 & pid=$!
for ((i=0;i<110;i++)); do if grep -aq 'DADA_RAM_PROBE .*efi=yes' "$LOG" || ! kill -0 "$pid" 2>/dev/null; then break; fi; sleep 1; done
kill "$pid" 2>/dev/null || :; wait "$pid" || :
grep -a 'DADA_RAM_PROBE .*efi=yes' "$LOG"
