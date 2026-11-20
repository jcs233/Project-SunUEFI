#!/usr/bin/env bash
# Run against a dedicated Linux checkout of 7Night-kqx/uefi-dada at the
# locked revision with submodules initialized. No Android tooling is invoked.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${FW_SRC:?dedicated Linux checkout of pinned uefi-dada with submodules}"
cd "$FW_SRC"; export WORKSPACE=$PWD
export EDK_TOOLS_PATH=$PWD/Mu_Basecore/BaseTools PYTHON_COMMAND=python3
export PYTHONPATH="$EDK_TOOLS_PATH/Source/Python${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$EDK_TOOLS_PATH/Source/C/bin:$EDK_TOOLS_PATH/BinWrappers/PosixLike:$PATH"
export PACKAGES_PATH="$PWD:$PWD/Platforms/Xiaomi:$PWD/Common/Mu:$PWD/Common/Mu_OEM_Sample:$PWD/Mu_Basecore:$PWD/Silicon/Qualcomm:$PWD/Silicon/Silicium:$PWD/Silicium-ACPI:$PWD/Silicium-ACPI/Platforms/Xiaomi:$PWD/Silicium-ACPI/Silicon/Qualcomm"
apply_once() { local dir=$1 patch=$2; if ! (cd "$dir" && git apply --reverse --check "$patch") 2>/dev/null; then (cd "$dir" && git apply "$patch"); fi; }
for patch in AsmMacroLib Auth-Service Boot-Manager Timer Usb-Bus; do apply_once Mu_Basecore "$PWD/Resources/MuPatches/$patch.patch"; done
apply_once . "$root/firmware/linux-probe.patch"
apply_once . "$root/firmware/dada-carveouts.patch"
name=Mu-dada-probe; target="$root/out/firmware"; dt=Resources/DTBs/dada.dtb
if [[ -n ${PROBE_KERNEL_OUT:-} ]]; then
  : "${PROBE_STOCK_DTB:?selected OTA inputs required}"
  (cd "$PROBE_KERNEL_OUT" && sha256sum -c SHA256SUMS && sha256sum -c efi.sha256)
  python3 "$root/scripts/configure-fv-probe.py" "$FW_SRC" "$PROBE_KERNEL_OUT/EFI/BOOT/BOOTAA64.EFI"
  name=Mu-dada-linux-ram; target="$PROBE_KERNEL_OUT/firmware"; dt=$PROBE_STOCK_DTB
elif [[ -f Platforms/Xiaomi/dadaPkg/DadaRam.efi ]]; then
  echo "Dedicated FV-enabled checkout: do not use for firmware-only builds" >&2; exit 2
fi
mkdir -p Conf
for t in tools_def target build_rule; do cp "$EDK_TOOLS_PATH/Conf/$t.template" "Conf/$t.txt"; done
# distro clang/lld/llvm and checked-in Mu BaseTools; no networked Stuart setup.
make -C "$EDK_TOOLS_PATH/Source/C" -j"${JOBS:-8}" HOST_ARCH=X64
build -p dadaPkg/dada.dsc -a AARCH64 -t CLANGPDB -b RELEASE -n "${JOBS:-8}" \
  -D FD_BASE=0xA7100000 -D FD_SIZE=0x300000 -D FD_BLOCKS=0x300 \
  -D ENABLE_SECUREBOOT=0 -D MEMORY_PROTECTION=TRUE -D SHIP_MODE=FALSE -D DEVICE_MODEL=0
fd=Build/dadaPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd
test "$(stat -c %s "$fd")" = 3145728
if [[ -n ${PROBE_KERNEL_OUT:-} ]]; then
  bash "$root/scripts/build-guard.sh"; shim=Build/dada-guard/shim.bin
else
  make -B -C BootShim REQUIRES_KERNEL_HEADER=1 FD_BASE=0xA7100000 FD_SIZE=0x300000; shim=BootShim/BootShim.bin
fi
mkdir -p "$target"
(cat "$shim" "$fd" | gzip -n -c; cat "$dt") > Build/dada-probe.payload
tmp=$(mktemp "$target/.incoming.XXXXXXXX.img")
trap 'rm -f -- "$tmp"' EXIT
python3 Resources/Scripts/mkbootimg.py --header_version 4 --kernel Build/dada-probe.payload --ramdisk Resources/ramdisk -o "$tmp"
if [[ -n ${PROBE_KERNEL_OUT:-} ]]; then
  python3 "$root/scripts/audit-fv-probe.py" "$PROBE_KERNEL_OUT" "$dt" "$shim" --image "$tmp" >Build/dada-fv-audit.json
  cp "$shim" "$target/guard.bin"; cp Build/dada-fv-audit.json "$target/fv-audit.json"
fi
mv -f -- "$tmp" "$target/$name.img"
(cd "$target" && sha256sum "$name.img" >SHA256SUMS)
