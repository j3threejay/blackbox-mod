/*
 * Per-voice filter call sites. r0 = filter object, r1 = audio buffer; r2 = the pad object the voice belongs to.
 * Sample pads (class A, 0x08055c60): the pad object is in r6.
 * Clip / slicer pads (class B, 0x080669d6, in FUN_080667b8): the pad object is in r6 there too. (Up to 3.1.T this
 * took the pad as filter object - 0x3ac. That is only the pad's FIRST voice, object pad + 0x260 with its filter at
 * + 0x14c; a slicer or clip set to play several voices has more, so their voices past the first read some other
 * pad's Fidelity, or none.)
 */
    .syntax unified
    .thumb
    .text

    .global filter_voice_a
    .thumb_func
    .type filter_voice_a, %function
filter_voice_a:
    mov     r2, r6
    b.w     filter_process

    .global filter_voice_b
    .thumb_func
    .type filter_voice_b, %function
filter_voice_b:
    mov     r2, r6
    b.w     filter_process

/*
 * The clip / slicer reader's one call (0x08066622, in FUN_08066454). There fp is the voice object, whose filter object
 * is voice + 0x14c. Stock leaves r1 unused in this call; clip_read gets the filter object in it, to leave the rate
 * where the output stage looks for it.
 */
    .global clip_read_b
    .thumb_func
    .type clip_read_b, %function
clip_read_b:
    add.w   r1, fp, #0x14c
    b.w     clipwin_read            @ clipwin.c: Slip's mapping, then filter.c's clip_read

/*
 * The four calls to the sample-voice reader (FUN_08056fd0 -> FUN_08055f0c). At each of them r4 is the voice and s1 its
 * signed playback rate. The voice's filter object is voice + 0xa8, and filter.c keeps the rate at object + 0x60 for
 * the output stage, which runs later in the same function.
 */
    .global voice_read_a
    .thumb_func
    .type voice_read_a, %function
voice_read_a:
    vstr    s1, [r4, #0x108]
    b.w     voice_read

