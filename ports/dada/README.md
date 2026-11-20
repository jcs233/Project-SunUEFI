# 小米 15（dada）

这不是平板刷机包。此分支把 [Project SunUEFI](https://github.com/slwyts/Project-SunUEFI) 的合体 BOOT 和无损还原格式移植到小米 15 标准版。**暂时没有可安装的手机双系统**。当前只支持 `OS4.0.4.0.XOCCNXM` 的指定原厂 BOOT；不支持 15 Pro、Ultra 或其他 ROM，也不应在手机上安装 `piano` 模块。

| 能力 | 验证到哪里 |
|---|---|
| 临时运行主线 Linux | 前一轮在 `dada` 上临时启动过独立的 RAM 镜像：屏幕出现 Linux 7.4-rc3 的 EFI 用户态标记，随后回到 Android。此内核不含 UFS 块驱动，不是桌面发行版。 |
| 保留原 Android 与选择 Linux | 主机生成两份 96 MiB BOOT 文件。默认文件走原厂 GKI；显式 Linux 请求且现场设备树通过检查时，走手机自己的 guard → Mu → 固件内的 GRUB/Linux。没有使用平板的早期按键、显示、固定通信地址或写盘路径。初版默认镜像已在手机上临时启动，用户确认回到 Android；显式 Linux 的真机结果与模拟器结果分开记录。 |
| 恢复原厂 BOOT | 两份合体文件都须通过上游文件还原，并与原厂输入逐字节相同才输出。此结果不等同于能恢复手机用户数据或 GPT。 |
| 内置存储与桌面 | 已在 QEMU 上从同一块只读 GPT 的 ESP 和 ext4 启动至 shell；不是手机 UFS 证明。图形桌面、触控、GPU、无线、音频、休眠、Android 助手与 Windows on ARM **均不是此手机分支已实现的功能**。 |

## 在 Linux 主机复验（不需要手机、root 或裸盘）

在 fork 根目录运行。以下用 `RAM_ROOT=$PWD/ports/dada/ram` 指向 RAM 探针源码。在已有的独立 `Xiaomi15-Linux` 工作区中，将 `RAM_ROOT` 指向该工作区；`FORK` 指向这个 fork 的检出。使用自己的本机路径，`OUT` 需是专用构建目录。

```sh
FORK=$PWD
RAM_ROOT=$FORK/ports/dada/ram
OUT=$FORK/build/dada
mkdir -p "$OUT"
git submodule update --init upstream/simple-init
python3 "$FORK/tools/build_boot_repack.py" --arch host --output "$OUT/repacker"
```

**准备已核对的输入。** 如已有原厂 `boot.img`、带 `guard.bin` 的同版 RAM 探针和对应的 `Image`、`dada.dtb`、`kernel.config`、`EFI/BOOT/BOOTAA64.EFI`，可跳到下一段。重建时使用以下来源：

- [dada 的板级 Mu 固件](https://github.com/7Night-kqx/uefi-dada/tree/d4381cc7129bc4cb28eca2683431d65abab23177)，固定提交 `d4381cc7`，须初始化子模块；`FW_SRC` 指向专用 Linux 检出，固件脚本会应用补丁。不要混用平板 FD。
- Linux 主线 `v7.4-rc3`（`aebb7274476403040d582c61478df8f4a7bf9cd3`）；`SRC` 指向其源树。需要 AArch64 GCC/binutils、clang/LLD、EDK2 构建依赖、dtc/fdtoverlay、ARM64 EFI GRUB 和 Python 3.11+。模拟器检查另需 `qemu-system-aarch64`。
- 自备上述 ROM 的**完整** OTA。只读解包；本仓库不分发原厂镜像、专有固件或手机备份。本版本确认的 `dtb_idx=0` 与 `dtbo_idx=0` 不是其他 ROM 的通用规则。

```sh
# OTA、SRC、FW_SRC 和 WORK 均为调用者事先设置的绝对路径。
STOCK="$RAM_ROOT/out/stock/OS4.0.4.0.XOCCNXM"; DT="$RAM_ROOT/out/device"
python3 "$RAM_ROOT/scripts/extract-stock.py" "$OTA" "$STOCK"
printf '%s\n' '{"ro.boot.product.hardware.sku":"dada","ro.board.platform":"sun","ro.boot.dtb_idx":"0","ro.boot.dtbo_idx":"0"}' > "$OUT/indices.json"
python3 "$RAM_ROOT/scripts/select-stock-dt.py" "$STOCK" "$OUT/indices.json" "$DT"
fdtoverlay -i "$DT/stock-base.dtb" -o "$DT/stock-selected.dtb" "$DT/stock-overlay.dtbo"
KERNEL_OUT="$RAM_ROOT/out/7.4.0-rc3-tiny"
RAM_INIT=tiny SRC="$SRC" WORK="$WORK" OUT="$RAM_ROOT/out" bash "$RAM_ROOT/scripts/build-kernel.sh"
KERNEL_OUT="$KERNEL_OUT" bash "$RAM_ROOT/scripts/package-efi.sh"
FW_SRC="$FW_SRC" PROBE_KERNEL_OUT="$KERNEL_OUT" PROBE_STOCK_DTB="$DT/stock-base.dtb" bash "$RAM_ROOT/scripts/build-uefi.sh"
```

**生成、还原并检查两条路径。** 选择器使用同一份板级 guard 和 libfdt 源码；不读取手机或按键。默认只接收已验证 RAM 镜像的摘要；本机重建的 EFI/内核可能因构建工具、时间戳不同而不匹配。此时应检查固件卷、guard 和实际构建来源，复验通过后再传入独立确认的 `--rebuilt-probe-sha256`，不要用下载文件自报的摘要跳过核对。

```sh
RAM_ROOT="$RAM_ROOT" python3 "$FORK/ports/dada/selector/test.py" "$FORK" -v
RAM_ROOT="$RAM_ROOT" FW_SRC="$FW_SRC" bash "$FORK/ports/dada/selector/build.sh" "$FORK" "$OUT/selector"
python3 "$FORK/ports/dada/combine.py" --ram-root "$RAM_ROOT" \
  --repacker "$OUT/repacker/piano-boot-repack" --selector-dir "$OUT/selector" --out "$OUT/combined"
python3 "$FORK/ports/dada/test-handoff.py" --stock "$RAM_ROOT/out/stock/OS4.0.4.0.XOCCNXM/boot.img" \
  --stock-dt "$RAM_ROOT/out/device/stock-selected.dtb" --selector-json "$OUT/selector/selector.json" \
  --android "$OUT/combined/combined-stock.img" --linux "$OUT/combined/combined-linux.img"
```

`combined/evidence.json` 记录输入和产物摘要、NEXT 请求及还原结果。`test-handoff.py` 从合体文件读取实际 ARM64 指令，在 QEMU 中分别观察原厂 GKI 入口、手机 guard 和搬运后的 Mu 固件入口。模拟的启动模式和 DRAM 只存在于测试副本中；模拟器既不运行厂商 DXE，也不证明 Android 已经开机。原厂 BOOT 的预期 SHA-256 是 `7935a651b43945b020bd02744489e1f1f7eeff032bb6c245b70fd31b0c1e2a2f`。合体文件不带小米 OEM 签名。

## 本次验证结果（2026-11-20）

- 两份 BOOT 的 unsigned AVB 内容摘要都匹配，且分别还原出了相同的 100,663,296 个原厂字节。精确输入和产物 SHA-256 在[主机验证记录](verification.json)。这些是离线变体，不是 Android 模块可直接接管的安装包。
- ARM64 QEMU 共 6 例：默认 Android 和显式 Linux 分别到达预期入口；即使已选择 Linux，Recovery、关机充电、initrd 中显式 charger，以及没有可用现场 RAM 映射时，都回到原厂 GKI 入口。QEMU 在入口停下，不把跳到入口算作启动系统成功。
- 另在已启动的手机上只读检查了原厂命令行，本地解析器识别到 `bootmonitor.bootmode=normal`；也解析了同版 OTA `vendor_boot` 中的静态 bootconfig。这不等同于已读取启动瞬间的完整设备树或 ABL 生成的 initrd。

**同一台手机的三次临时启动**（均未刷写或切槽；时间从主机开始传输计算）：

| RAM 镜像 | Android 完成启动 | 结论 |
|---|---:|---|
| 初版默认 Android（`85cd8393…`） | 15.0 秒 | 用户在屏幕上确认已回到原厂系统。 |
| 初版显式 Linux（`c38b6599…`） | 19.2 秒 | 此时 Android 已运行 12.76 秒，不符合探针会在用户态等待 90 秒的预期。 |
| 修正版显式 Linux（`cc3bfd3a…`） | 120.4 秒 | 此时 Android 已运行 15.19 秒，推算 Android 内核约在传输后 105 秒启动；与独立 RAM 探针的时间特征相符，但不能单凭这个间隔确认进入 Linux 用户态。 |

该 ROM 正常运行时报告 `bootmonitor.bootmode=normal` 和 `ro.boot.force_normal_boot=0`；主机重放确认初版会拒绝对应的 `androidboot.force_normal_boot=0`。修正版不再把“没有强制正常启动”解释为“进入恢复模式”。未知值仍拒绝，Recovery、充电、NEXT 和内存范围检查不变。上述结果不证明旧版在实机上究竟命中了哪一道检查。三次返回均为原 A 槽和原厂系统，系统指纹、vbmeta 摘要未变。仓库不附设备原始日志。

## 下一项真机验收

默认路径已通过真机临时启动验证；显式 Linux 路径另需屏幕用户态标记或同等证据。然后才是只读 UFS 枚举、主/备 GPT 核对、从指定分区只读挂载根卷。两项都通过之前，不用这些文件刷 `boot_a/b`、不改 GPT、不缩 `userdata`。平板 WebUI、图形选择器与桌面硬件适配要等各自的手机驱动和恢复路径，不是改个代号即可启用。
