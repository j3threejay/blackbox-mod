/*
 * Live meters (meter.c): in place of the two "pad mix -> output bus" calls, bl FUN_0804da6c @0x0805aa12 (Sample /
 * Multi pads) and @0x08068c0e (Clip / Slicer). r0 = the bus, r1 = the pad's mix buffer, r4 = the pad. Record the
 * buffer's peak, then go on into FUN_0804da6c with r0 / r1 as they were. An AAPCS call boundary, so meter_peak may
 * use the float registers.
 */
    .syntax unified
    .thumb
    .text

    .global meter_add
    .thumb_func
    .type meter_add, %function
meter_add:
    push    {r0, r1, r4, lr}
    mov     r0, r4                  @ pad
    bl      meter_peak              @ (pad, buffer in r1)
    pop     {r0, r1, r4, lr}
    ldr     r12, =0x0804da6c + 1
    bx      r12
    .ltorg
