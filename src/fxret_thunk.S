/*
 * The engine block's two effect-return mixes (FUN_08053164: bl FUN_0804da6c @0x08053506 = Out 1 += the delay's bus 10,
 * @0x08053516 = Out 1 += the reverb's bus 11): r0 = Out 1's bus, r1 = the return's bus, and the bus table (what stock
 * passes FUN_0805f37c) is in r8 there. Hand it on as the third argument, which is all fxret_mix needs to pick another
 * output bus. Nothing else is touched: r2 / r3 / r12 are free at both sites (the next instructions reload them).
 */
    .syntax unified
    .thumb
    .text

    .global fxret_dly_thunk
    .thumb_func
    .type fxret_dly_thunk, %function
fxret_dly_thunk:
    mov     r2, r8
    movs    r3, #0
    b.w     fxret_mix

    .global fxret_rev_thunk
    .thumb_func
    .type fxret_rev_thunk, %function
fxret_rev_thunk:
    mov     r2, r8
    movs    r3, #1
    b.w     fxret_mix
