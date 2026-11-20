/* SPDX-License-Identifier: BSD-2-Clause */
ENTRY(selector)
PHDRS { code PT_LOAD FLAGS(5); scratch PT_LOAD FLAGS(6); }
SECTIONS {
    . = 0;
    .image : { KEEP(*(.entry)) *(.text .text.*) *(.rodata .rodata.*) . = ALIGN(16); } :code
    .unexpected : { *(.data .data.* .bss .bss.* COMMON .got .got.*) }
    ASSERT(SIZEOF(.unexpected) == 0, "selector requires runtime data/relocation")
    .stack (NOLOAD) : { . = ALIGN(16); stack_bottom = .; . += 16384; . = ALIGN(4096); stack_top = .; } :scratch
    ASSERT(selector == 0 && stack_top > 8192 && stack_top < 65536 && (stack_top % 4096) == 0, "invalid SPLIT layout")
    /DISCARD/ : { *(.comment .note* .eh_frame*) }
}
