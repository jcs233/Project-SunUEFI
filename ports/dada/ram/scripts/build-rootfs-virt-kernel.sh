#!/usr/bin/env bash
# QEMU-only kernel: one virtio-mmio block disk, no phone block controller or initramfs userland.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${SRC:?pinned mainline Linux source}" "${WORK:?native Linux build workspace}"
export ARCH=arm64 CROSS_COMPILE=${CROSS_COMPILE:-aarch64-linux-gnu-}
test "$(make -sC "$SRC" kernelversion)" = 7.4.0-rc3
b="$WORK/build-rootfs-virt"; out="$root/out/tests/rootfs-virt"; mkdir -p "$b" "$out"
grep -Ev '^CONFIG_(CMDLINE|BLK_DEV_INITRD|INITRAMFS_COMPRESSION_GZIP)=' "$root/board/probe.config" >"$b/seed"
cat >>"$b/seed" <<'KCONF'
CONFIG_BLOCK=y
CONFIG_BLK_DEV=y
CONFIG_VIRTIO_MENU=y
CONFIG_VIRTIO_MMIO=y
CONFIG_VIRTIO_BLK=y
CONFIG_EXT4_FS=y
CONFIG_DEVTMPFS_MOUNT=y
CONFIG_BLK_DEV_INITRD=n
KCONF
k=(make --no-print-directory -C "$SRC" O="$b")
KCONFIG_ALLCONFIG="$b/seed" "${k[@]}" allnoconfig
for opt in VIRTIO_MMIO VIRTIO_BLK EXT4_FS DEVTMPFS_MOUNT EFI_STUB; do grep -qx "CONFIG_$opt=y" "$b/.config"; done
if grep -Eq '^CONFIG_(VIRTIO_PCI|BLK_DEV_INITRD|SCSI_UFSHCD|MMC_BLOCK)=[ym]' "$b/.config"; then echo 'Unexpected device or initrd configuration' >&2; exit 2; fi
"${k[@]}" -j"${JOBS:-8}" Image
cp "$b/arch/arm64/boot/Image" "$out/Image"; cp "$b/.config" "$out/kernel.config"
