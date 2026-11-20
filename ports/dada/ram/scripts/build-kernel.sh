#!/usr/bin/env bash
# Build on a native Linux filesystem; never needs root or touches a device.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${SRC:?absolute path to clean, unpacked upstream Linux}" "${WORK:?absolute build directory}"
export ARCH=arm64 CROSS_COMPILE=${CROSS_COMPILE:-aarch64-linux-gnu-}
ver=$(make -sC "$SRC" kernelversion)
case "$ver" in 7.3.5|7.4.0-rc3|7.4-rc3) ;; *) echo "Unpinned kernel $ver" >&2; exit 1;; esac
profile=${RAM_INIT:-busybox}; case "$profile" in busybox) tag="";; tiny) tag=-tiny;; *) exit 2;; esac
b=$WORK/build-$ver$tag; publish=${OUT:-$root/out}/$ver$tag
mkdir -p "$b/ram" "$publish"
if [[ $profile == busybox ]]; then
: "${BUSYBOX_DEB:?arm64 Ubuntu busybox-static .deb}"
# Ubuntu's signed Packages index supplies the pinned package hash.
echo "fcf50794faf920455895d7ef103d1c54b9ebf7f18d2e52982dbf3903b7769592  $BUSYBOX_DEB" | sha256sum -c -
dpkg-deb -x "$BUSYBOX_DEB" "$b/ram"
cat >"$b/initramfs.list" <<EOF
dir /bin 0755 0 0
dir /dev 0755 0 0
dir /proc 0555 0 0
dir /sys 0555 0 0
nod /dev/console 0600 0 0 c 5 1
file /bin/busybox $b/ram/usr/bin/busybox 0755 0 0
file /init $root/initramfs/init 0755 0 0
EOF
else
"${CROSS_COMPILE}gcc" -Os -static -nostdlib -no-pie -fno-builtin -fno-stack-protector -mgeneral-regs-only -Wl,--build-id=none,-e,_start,-s "$root/initramfs/probe.c" -o "$b/init-tiny"
cat >"$b/initramfs.list" <<EOF
dir /dev 0755 0 0
dir /sys 0555 0 0
nod /dev/console 0600 0 0 c 5 1
file /init $b/init-tiny 0755 0 0
EOF
fi
cp "$root/board/probe.config" "$b/seed"
printf 'CONFIG_INITRAMFS_SOURCE="%s"\n' "$b/initramfs.list" >>"$b/seed"
km=(make --no-print-directory -C "$SRC" O="$b")
KCONFIG_ALLCONFIG="$b/seed" "${km[@]}" allnoconfig
for key in EFI EFI_STUB BLK_DEV_INITRD DEVTMPFS PROC_FS SYSFS BINFMT_SCRIPT SERIAL_AMBA_PL011_CONSOLE FRAMEBUFFER_CONSOLE; do grep -qx "CONFIG_$key=y" "$b/.config" || { echo "Missing $key" >&2; exit 1; }; done
for key in SCSI_UFSHCD MMC_BLOCK MTD_BLOCK SCSI_SD BLK_DEV_SD EFI_VARS_PSTORE; do ! grep -Eq "^CONFIG_$key=[ym]" "$b/.config" || exit 1; done
# Build against the exact same SoC dtsi and bindings as the kernel without modifying its sources.
"${CROSS_COMPILE}gcc" -E -P -nostdinc -undef -D__DTS__ -x assembler-with-cpp -I"$SRC/scripts/dtc/include-prefixes" -I"$SRC/arch/arm64/boot/dts/qcom" "$root/board/sm8750-xiaomi-dada-probe.dts" -o "$b/dada.pp.dts"
dtc -q -I dts -O dtb -o "$b/dada.dtb" "$b/dada.pp.dts"
test "$(fdtget "$b/dada.dtb" / compatible)" = 'xiaomi,dada qcom,sm8750'
"${km[@]}" -j"${JOBS:-$(nproc)}" Image
cp "$b/arch/arm64/boot/Image" "$publish/Image"; cp "$b/dada.dtb" "$publish/dada.dtb"; cp "$b/.config" "$publish/kernel.config"
(cd "$publish" && sha256sum Image dada.dtb kernel.config >SHA256SUMS)
