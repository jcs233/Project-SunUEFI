/* SPDX-License-Identifier: BSD-2-Clause */
/* Entered by the patched B at Image+4, not as a callable function. No
 * loader stack, MMIO, cache maintenance, interrupt or EL state changes. */
.section .entry,"ax"
.global selector
selector:
    adr x9, selector
    adr x10, metadata
    adr x4, split_tag
    ldp x5, x6, [x4]
    ldp x7, x8, [x10]
    cmp x5, x7
    ccmp x6, x8, #0, eq
    b.ne invalid
    ldp w5, w6, [x10, #16]
    cmp w5, #1
    b.ne invalid
    cmp w6, #128
    b.ne invalid

    ldp x11, x13, [x10, #24]   /* selector offset, original Image span */
    cmp x13, #4096
    b.lo invalid
    mov x4, #0x6000000          /* fork BOOT_BYTES */
    cmp x11, x4
    b.hs invalid
    cmp x13, x11
    b.hs invalid
    add x4, x13, #4095
    and x4, x4, #-4096
    add x4, x4, #8192
    cmp x4, x11
    b.ne invalid
    subs x12, x9, x11          /* Image base; PC-relative, not a load address */
    b.lo invalid
    ldp w5, w6, [x10, #40]     /* original code0/code1 */
    lsr w4, w6, #26
    cmp w4, #5                 /* B imm26, never BL; PC is Image+4 */
    b.ne invalid
    sbfiz x17, x6, #2, #26
    add x17, x17, #4
    cmp x17, #64
    b.lo invalid
    cmp x17, x13
    b.hs invalid
    add x17, x12, x17
    ldp w7, w8, [x12]
    cmp w7, w5                 /* live code0 is unchanged by repack */
    b.ne invalid
    sub x4, x11, #4
    lsr w4, w4, #2
    mov w7, #0x14000000
    orr w4, w4, w7             /* patched code1 must point back here */
    cmp w8, w4
    b.ne invalid

    /* Fast stock path: neither a valid request nor FDT validation is needed
     * to keep booting Android. Target words alone can only VETO Linux. */
    sub x4, x9, #8192
    ldr w5, [x4, #32]
    add x4, x4, #4096
    ldr w6, [x4, #32]
    cmp w5, #2
    ccmp w6, #2, #4, ne
    b.ne stock
    tst x9, #4095
    b.ne stock
    cbz x0, stock
    tst x0, #7
    b.ne stock
    ldr x5, [x12, #16]         /* live image_size */
    ldr x6, [x10, #88]
    cmp x5, x6
    b.ne stock
    mov x6, #0x6000000
    cmp x5, x6
    b.hs stock
    adds x6, x12, x5
    b.cs stock
    adr x4, stack_top
    cmp x4, x6
    b.hi stock
    cmp x0, x12                 /* don't use our stack if x0 aliases Image */
    b.hs 1f
    adr x5, stack_bottom
    sub x6, x5, x0
    cmp x6, #0x200, lsl #12    /* even maximal DT must not touch our stack */
    b.lo stock
    b use_stack
1:
    cmp x0, x6
    b.lo stock
use_stack:
    mov x19, sp
    mov sp, x4
    mov x20, x0
    mov x21, x1
    mov x22, x2
    mov x23, x3
    mov x24, x17
    mov x1, x12
    mov x2, x10
    sub x3, x4, x9             /* linked memory_bytes */
    bl linux_target
    cmp x0, #0
    csel x17, x24, x0, eq
    mov sp, x19
    mov x0, x20
    mov x1, x21
    mov x2, x22
    mov x3, x23
stock:
    br x17
invalid:                        /* no trusted stock continuation */
    wfe
    b invalid
.balign 16
split_tag: .asciz "SUNUEFI-SPLITv1"
.balign 16
.global metadata
metadata: .zero 128
