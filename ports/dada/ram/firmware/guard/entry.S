/* SPDX-License-Identifier: BSD-2-Clause. The stack is part of the image ABL
 * loaded, not an address chosen from a different handset. No copy on refusal. */
.section .head,"ax"
.global head
head:
  b start
  nop
  .quad 0xa7100000 /* match dada upstream arm64 header */
  .quad end_image-head
  .quad 0,0,0,0
  .ascii "ARM\x64"
  .long 0
start:
  adr x1, head
  tst x1,#4095
  b.ne refuse
  cbz x0,refuse
  tst x0,#7
  b.ne refuse
  adr x4, scratch_stack
  mov sp,x4
  adr x2, blob
  add x2,x2,#0x300,lsl #12
  mov x3,x0
  mov x19,x0
  bl dada_check
  cbnz w0,failed_check
  adr x4,blob
  mov x5,#0xa7100000
  mov x6,#0x300000
1:ldp x2,x3,[x4],#16
  stp x2,x3,[x5],#16
  subs x6,x6,#16
  b.ne 1b
  dsb sy
  ic iallu
  dsb sy
  isb
  mov x5,#0xa7100000
  br x5
failed_check:
  cmp w0,#3
  b.lo refuse
  mov x0,x19
  bl dada_can_reset
  cbz w0, refuse
  movz w0,#9
  movk w0,#0x8400,lsl #16   /* PSCI SYSTEM_RESET, standard SMC32 */
  smc #0
refuse:
  wfe
  b refuse
