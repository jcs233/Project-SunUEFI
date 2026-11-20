# dada 离线 BOOT selector

这是 repacker 跳入的一小段 AArch64 LE 裸代码，不是独立的 `Image`、Android 模块或刷机工具。只链接指定 fork 的 `BootRequest.c`、dada guard 的只读判定和 libfdt，不链接 piano 的 picker、按键、trace、MMIO 或 reset 路径。

## 构建和单测（Linux / WSL，完全离线）

```bash
bash ports/dada/selector/build.sh FORK_ROOT OUTPUT_DIR
python3 ports/dada/selector/test.py FORK_ROOT -v
```

`FORK_ROOT` 是有 `uefi/handoff/bootselect/BootRequest.{c,h}` 的已展开 `jcs233/Project-SunUEFI@c5928587` 源码；本工作区可传 `.cache/jcs233-review`。脚本核对两文件摘要，不调用 Git、不取子模块。需要 Bash、Python 3、GNU AArch64 GCC/binutils（可设 `CROSS_COMPILE` 前缀）；主机单测另用 `cc`、`libfdt-dev`、`dtc` 和 `fdtput`。

- guard 默认查找本仓库 `ports/dada/ram/firmware/guard`、`firmware/guard`、再到 `FORK_ROOT/ports/dada/ram/firmware/guard`。可用 `RAM_ROOT` 指定含 `firmware/guard` 的目录。
- libfdt 优先用 `LIBFDT_DIR`（直接含 `fdt.c`、`fdt_check.c` 等的源码目录）；其次用 `FW_SRC/Mu_Basecore/MdePkg/Library/BaseFdtLib/libfdt/libfdt`。两者未设时，从 RAM tree 或本仓库的 `.cache/libfdt.tar.gz` 离线解压并校验固定 SHA-256。当前工作区不需要这些环境变量。没有归档的 fork 需提供上述 libfdt 源码之一。
- 输出 `selector.bin` 和 `selector.json`。从同一次链接读取 `memory_bytes`、`metadata_offset` 两个整数字段；不要以文件长度替代前者。128 字节全零元数据槽在文件内、16 字节对齐。私有栈至少 16 KiB，不在文件内但全在 repacker 分配的 selector 内存内。其末端就是 4 KiB 对齐的 shim 起点；链接期和打包前均检查 `8192 < memory_bytes < 65536`。

## 分支与信任边界

入口从 PC 和 SPLITv1 (`+24` selector 偏移、`+32` 原 Image span、`+40/+44` 原 code0/code1) 恢复基址，核对 live code0 和改写后的 `B` 确实指回自己。Android 旁路是 `Image + 4 + sign_extend(imm26)*4`，不回跳被打补丁的指令，不改写 GKI header。若 SPLIT/原厂续跳地址本身无效，停在本地 WFE 循环，不猜跳址。两条可用出口均保留进入 selector 时的 x0..x3、SP、DAIF；不依赖传入的栈，其他通用寄存器及 NZCV 不承诺保持。

如果两页的原始 target 字段都不是 2，直接进 GKI，不碰 FDT、不用栈。预筛**不能**选择 Linux：仍必须由原版 `PianoBootRequestSelect` 对 selector 前的 8192 字节、以 `metadata+96` 起的 16 字节 generation，处理 CRC、序号、相等序号冲突等，且最终结果必须恰为 Linux (2)。NONE、menu、setup、无效请求均进 GKI；不消费或改写 NEXT。Linux 分支还核对 live Image 长度、selector/shim/FD/APP 区间、guard Image magic 和 `image_size == shim_size + 0x300000`。最后只跳相邻的 dada guard；FD 的复制与执行仍由 guard 负责。

这里信任离线构造并完整加载的 SPLIT 容器（含可写私有栈），以及 AArch64 引导协议的 x0：非空时必须指向实际可读的 normal RAM DTB。selector 只写自己随 Image 分配的栈，不写固定物理地址。它不是恶意引导器的隔离层：软件无法单凭一个数证明物理地址可读；与已加载 Image 别名的伪造 initrd 也不能假定其原始内容仍完好。不是对载荷、设备身份或 FDT 的签名验证。

## Linux 放行条件 / QEMU 契约

这些条件必须**全部**满足；无法识别但原厂续跳可信时，退回 GKI。

1. **现场 DT**：x0 非零，8 字节对齐，40 字节到 2 MiB，区间不回绕。复用 `firmware/guard/check.c` 的 `dada_check()`（含 `fdt_check_full`），而不是只匹配 magic：`qcom,sun`、根和 `/reserved-memory` 的 2+2 cells、空 `ranges`、原 splash、可用内存覆盖和 carveout 检查与 guard 相同。不要求不存在的 `xiaomi,dada` compatible；`qcom,board-id=<0 0>` 不影响判定。
2. **活跃范围**均按 `[lo,hi)`。整个合体 Image（包括原 GKI、NEXT、selector 栈、guard、FD、APP、目录和末尾填充）、DTB、存在时的整个 initrd，两两不重叠；每段必须完整落在某个 enabled RAM tuple，不与 `/memreserve/` 或固定 `/reserved-memory/*/reg` 重叠。三者都不能碰 guard 工作窗口 `[0xa7000000,0xa8000000)`、`[0xb90c0000,0xd4e23000)`。窗口与 FDT 的判断直接复用 guard 源码的范围函数。相邻不算冲突。OTA 自带的占位 `/memory/reg` 不会通过。
3. **正常模式不是 Linux 意图**。唯一正面模式证据是唯一 `/chosen` 的 `bootargs` 中**恰好一个**完整 `bootmonitor.bootmode=normal`；仍须 NEXT=2。`androidboot.force_normal_boot` 存在时只接受精确的 `0` 或 `1`；这台手机正常进入 Android 时也报告 `ro.boot.force_normal_boot=0`。两种值都不是 Linux 意图，也不会覆盖恢复或充电信号。`androidboot.mode=normal` 或 `sunuefi.boot=linux` 也不能替代正常模式证据。`bootmonitor.bootmode=recovery/poweroff_cg`、重复或未知值、显式 `androidboot.mode=charger` 等始终否决，包括另一来源后出现的冲突。`mca_log.charge_boot_mode` 如存在只接受 `0`；`silent_boot.mode`、`mtdoops.boot_mode` 如存在只接受 `nonsilent`、`0`。仅按完整的相关键判定；不会因为无关变量含有 `charg`/`recovery` 字样就拒绝。没有物理按键逻辑。
4. `bootargs` 必须是以单 NUL 结尾的字符串（含终止符最多 8192 字节）。`/chosen` 支持的其他属性为 `linux,initrd-start/end`、`stdout-path`、`linux,stdout-path`、`phandle`、`linux,phandle`、`kaslr-seed`、`rng-seed` 和可选 `name="chosen"`（精确 `chosen\0`）。未知属性、重复项、子节点或另有旧式 `/firmware/android` 参数来源均不放行。
5. **initrd 可以不存在**。存在时 start/end 必须成对、同为一个或两个大端 cells，非空、end > start。先做上述范围检查，才读取末尾 Linux/Android `#BOOTCONFIG\n` trailer：小端长度及字节和、数据最多 32767 字节，允许 magic 后 0..3 个零。只支持可判读的平面配置；普通 vendor key、简单引号、整行注释可以接受。无有效尾标、坏校验、未知语法（例如树形或 `kernel.`/`init.` 参数注入）、第二个 `bootmonitor.bootmode`、明确的充电/恢复模式都会退回 GKI。不扫描或解压 cpio，也不把 initrd 中的数据当代码。

**最小正例**：QEMU RAM `0x40000000..0xe0000000`，合体 Image `0xa8000000`，FDT `0xb7000000`。在 `out/device/stock-selected.dtb` 的**测试副本**上改 `/memory/reg=<0 0x40000000 0 0xa0000000>` 和 `/chosen/bootargs="bootmonitor.bootmode=normal"`；无需改板号、加按键、加 initrd 或额外 `androidboot.mode`。NEXT 选 Linux 时预期进入 `Image + SPLIT.shim`，否则在原 code1 的目标停断。负例可保留 `androidboot.mode=normal`，只将 bootmonitor 改为 `poweroff_cg`，预期仍是原 GKI。若模拟 initrd，普通零填充不是有效 bootconfig，测试用的最小 trailer 可参见 `test.py` 中的 `trailer()`。

主机单测只验证解析与拒绝策略；即使合体包在 QEMU 跳到 FD，也不证明真实 ABL 的内存布局、initrd 格式或持久安装安全。
