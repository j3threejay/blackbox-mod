/*
 * Clip Window (clipwin.c): the two segment-start hooks and the length hooks. The first two replace a `bl FUN_0806375c`
 * (the source prefetch, r0 = src, r1 = position) with a bl to a thunk that adds the segment slot and the pad, then
 * tail-calls C, which ends in the prefetch itself. sp is the caller's at the bl, so the slot is read where the
 * caller keeps it; r4 is the pad at both sites, and the callers reload r2 / r3 before using them again (notes/re/a2,
 * README section 2.2).
 */
    .syntax unified
    .thumb
    .text

/* H1, FUN_08065550 @0x0806578c: the slot is at [sp + 0x20] */
    .global clipwin_seg_start_b
    .thumb_func
    .type clipwin_seg_start_b, %function
clipwin_seg_start_b:
    ldr     r2, [sp, #0x20]
    mov     r3, r4
    b.w     clipwin_seg_start

/* H1', FUN_08065290 @0x0806541a: the slot is at [sp + 4] (stored at 0x0806540c) */
    .global clipwin_slice_start_b
    .thumb_func
    .type clipwin_slice_start_b, %function
clipwin_slice_start_b:
    ldr     r2, [sp, #4]
    mov     r3, r4
    b.w     clipwin_slice_start

/* H5, the render @0x080668fc posting the playhead: r0 = the UI's queue, r1 = msg 0x4a (sp + 0x58), r6 = the pad, fp =
   the slot of the segment it has just read (loaded at 0x0806687c, kept across the reader's call). The render reloads
   r3 from [sp + 0x34] after the post. */
    .global clipwin_playhead_b
    .thumb_func
    .type clipwin_playhead_b, %function
clipwin_playhead_b:
    mov     r2, r6
    mov     r3, fp
    b.w     clipwin_playhead

/* H3, the clip's length: each replaces a `bl FUN_080636f0` (fw_src_len, r0 = the source) where r4 is the pad, and
   tells clipwin_len which site it is (r2). The callers keep nothing in r1-r3 across that call (it is an AAPCS call
   that reaches the provider through a pointer). */
/* 0x08064b2c, the recompute's first call: Beat Count Auto, frames per step (a stopped pad takes its region here) */
    .global clipwin_len_recompute_b
    .thumb_func
    .type clipwin_len_recompute_b, %function
clipwin_len_recompute_b:
    mov     r1, r4
    movs    r2, #1
    b.w     clipwin_len

/* 0x08064c5a, the recompute's second call, right after it stored the step fields: r9 is the clip in output samples
   there (loaded from [sp + 0x20] at 0x08064bac on every path, the output of FUN_08070420), for a clip of one step */
    .global clipwin_len_steps_b
    .thumb_func
    .type clipwin_len_steps_b, %function
clipwin_len_steps_b:
    mov     r1, r4
    movs    r2, #3
    mov     r3, r9
    b.w     clipwin_len

/* 0x0806561e (FUN_08065550's > 0 check) */
    .global clipwin_len_b
    .thumb_func
    .type clipwin_len_b, %function
clipwin_len_b:
    mov     r1, r4
    movs    r2, #0
    b.w     clipwin_len

/* H3', the recompute at a wrap: each replaces a `bl FUN_08064a94` (r0 = the pad, r1 = the clock) and adds r2 = where
   the tick of the new pass is. 0x08066fac, the synced wrap: the render's i64 at [sp + 0x58] (FUN_08069c44's tick of
   the next start, snapped to +0x230 at 0x08066f92 / 0x08066f96, then turned into samples at 0x08066f9e) */
    .global clipwin_wrap_b
    .thumb_func
    .type clipwin_wrap_b, %function
clipwin_wrap_b:
    add     r2, sp, #0x58
    b.w     clipwin_wrap

/* 0x08066e9e, the unsynced wrap: no tick, no grid */
    .global clipwin_wrap_free_b
    .thumb_func
    .type clipwin_wrap_free_b, %function
clipwin_wrap_free_b:
    movs    r2, #0
    b.w     clipwin_wrap

/* 0x08065690: the last step's end (length - 1), and the seamless wrap */
    .global clipwin_len_end_b
    .thumb_func
    .type clipwin_len_end_b, %function
clipwin_len_end_b:
    mov     r1, r4
    movs    r2, #2
    b.w     clipwin_len
