ENTRY(head)
SECTIONS {
  . = 0;
  .shim : { *(.head) *(.text .text.*) *(.rodata .rodata.*) . = ALIGN(16); . += 0x4000; scratch_stack = .; BYTE(0); . = ALIGN(16); blob = .; }
  end_image = blob + 0x300000;
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
