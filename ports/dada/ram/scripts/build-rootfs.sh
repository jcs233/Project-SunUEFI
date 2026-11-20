#!/usr/bin/env bash
# Offline, unprivileged, image file only; never give mkfs a device path.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); out="$root/out/rootfs"
: "${BUSYBOX_DEB:?pinned Ubuntu arm64 busybox-static .deb}"
echo "fcf50794faf920455895d7ef103d1c54b9ebf7f18d2e52982dbf3903b7769592  $BUSYBOX_DEB" | sha256sum -c -
tmp=$(mktemp -d); trap 'rm -rf -- "$tmp"' EXIT
r="$tmp/root"; mkdir -p "$r"/{bin,sbin,etc,proc,sys,dev,run,tmp,root}; chmod 1777 "$r/tmp"; chmod 0700 "$r/root"
dpkg-deb -x "$BUSYBOX_DEB" "$tmp/pkg"; install -m 0755 "$tmp/pkg/usr/bin/busybox" "$r/bin/busybox"
qemu-aarch64 "$r/bin/busybox" --list >"$tmp/applets"
for app in sh ash cat ls sync uname awk grep tr mount umount mkdir rm dd df dmesg free ps sleep echo id head cut readlink sha256sum vi poweroff reboot; do
  grep -Fqx "$app" "$tmp/applets"; ln -s busybox "$r/bin/$app"
done
grep -Fqx init "$tmp/applets"; install -m 0755 "$root/rootfs/init" "$r/sbin/init"
printf '::askfirst:-/bin/sh\n::shutdown:/bin/sync\n' >"$r/etc/inittab"
printf 'root:x:0:0:root:/root:/bin/sh\n' >"$r/etc/passwd"; printf 'root:x:0:\n' >"$r/etc/group"
printf 'root:!:0:0:99999:7:::\n' >"$r/etc/shadow"; chmod 0600 "$r/etc/shadow"
printf 'NAME="dada development root"\nID=dada-dev\nPRETTY_NAME="dada ARM64 BusyBox development root"\n' >"$r/etc/os-release"
printf 'export PATH=/bin:/sbin HOME=/root\n' >"$r/etc/profile"
# fakeroot assigns root ownership inside the image without privileged mounts/loop devices.
img="$tmp/dada-busybox.ext4"; truncate -s 64M "$img"
fakeroot -- sh -eu -c 'chown -hR 0:0 "$1"; mke2fs -q -t ext4 -L DADA_DEV_ROOT -d "$1" -E lazy_itable_init=0,lazy_journal_init=0 "$2"' sh "$r" "$img"
e2fsck -fn "$img"
mkdir -p "$out"; [[ ! -e "$out/dada-busybox.ext4" || ( -f "$out/dada-busybox.ext4" && ! -L "$out/dada-busybox.ext4" ) ]]
install -m 0644 "$img" "$out/dada-busybox.ext4"; (cd "$out" && sha256sum dada-busybox.ext4 > SHA256SUMS)
