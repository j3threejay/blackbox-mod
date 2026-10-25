/*
 * Clip selection (clipsel.c): the way back into stock setup past its first instruction, and the pad for the two
 * file-length calls inside it.
 */
    .syntax unified
    .thumb

/*
 * sel_setup_stock(pad, clk): the trampoline at 0x08064a94 replaced setup's first instruction with a b.w to sel_setup,
 * so replay it here (the SAME register set: stock's epilogue @0x08064cee pops {r4-r8, sb, pc}) and carry on at the
 * next one. r12 is free at a function entry.
 */
    .global sel_setup_stock
    .thumb_func
    .type sel_setup_stock, %function
sel_setup_stock:
    push.w  {r4, r5, r6, r7, r8, r9, lr}
    ldr     r12, =0x08064a99
    bx      r12
    .ltorg

/* BL @0x08064b2c and @0x08064c5a (FUN_080636f0, the file length): r4 is setup's pad throughout */
    .global sel_len_b
    .thumb_func
    .type sel_len_b, %function
sel_len_b:
    mov     r1, r4
    b.w     sel_len
