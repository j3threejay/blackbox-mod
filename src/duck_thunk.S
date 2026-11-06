/*
 * Voice-start thunks: called in place of the two pad classes' voice-start functions. If the pad object is pad 1
 * (id 0 at +0x18) set the duck trigger flag; for every pad set its bit in the trigger mask; then continue into the original with every argument untouched.
 * A cell that is no pad sets no bit: the browser's pre-listen voice is a 17th class-B object, cell 0x401 (row 4,
 * col 1; FUN_080525f0 @0x08052b82), which & 3 read as pad 2, retriggering pad 2's LFO 2 / 3 on every pre-listen.
 */
    .syntax unified
    .thumb
    .text

    .equ DUCK_BASE, 0x2405ff70

    .macro voice_start name, original
    .global \name
    .thumb_func
    .type \name, %function
\name:
    push    {r0-r3}
    ldr     r3, =DUCK_BASE
    ldr     r1, [r0, #0x18]         @ pad id: bank << 16 | row << 8 | col
    cbnz    r1, 2f
    movs    r2, #1
    strb    r2, [r3, #8]            @ pad 1: the duck trigger
2:  tst     r1, #0xfc00
    bne     3f                      @ row 4 and up: no pad (the bank bits stay ignored)
    tst     r1, #0xfc
    bne     3f                      @ col 4 and up: no pad
    ubfx    r2, r1, #8, #2
    and     r1, r1, #3
    add     r1, r1, r2, lsl #2      @ row * 4 + col
    movs    r2, #1
    lsls    r2, r1
    ldrh    r0, [r3, #14]
    orrs    r0, r2
    strh    r0, [r3, #14]           @ every pad: its bit for the LFO retriggers (lfo.c)
3:  pop     {r0-r3}
    ldr     r12, =\original + 1
    bx      r12
    .ltorg
    .endm

    voice_start duck_voice_start_a, 0x08058548
    voice_start duck_voice_start_b, 0x08065908
