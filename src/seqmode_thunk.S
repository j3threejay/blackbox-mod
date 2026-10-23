/*
 * Replaces the app's `bl FUN_08098254` (back the cell up into the UNDO buffer) in the sequence-mode switch,
 * @0x0809fef6: r0 = app, r1 = the cell ref, and the caller holds the new mode in r11 (it stores it with
 * `mov r2, fp` two calls later). Pass it on as the third argument (src/seqmode.c).
 */
    .syntax unified
    .thumb
    .text

    .global seqmode_cross_thunk
    .thumb_func
    .type seqmode_cross_thunk, %function
seqmode_cross_thunk:
    mov     r2, r11
    b.w     seqmode_cross
