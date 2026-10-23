/*
 * Clip Window: Slip, Region, Loop Len, Fit and Loop Fade. Original 1010music Blackbox, firmware 3.1.9.
 * The reverse engineering and the bench measurements behind it are in github.com/Maigre/blackbox-mod, branch
 * maigre: notes/re/ and notes/bench/ (cited below as notes/...).
 *
 * Why: a clip that plays in sync can only start on the grid. A loop cut by ear from an unsynced recording (a song off a
 * phone, a take from other hardware) then sits a little ahead of or behind the groove of everything else, and nothing
 * on the unit moves it. Slip shifts what a Clip pad plays against the clock, by up to a bar either way, in ticks (960 to
 * a beat: one tick is about half a millisecond at 120 BPM), live: the Electrix Repeater's "Slip".
 *
 * Stock (notes/re/a1, a2, README section 2): a synced clip plays one segment per Sync step. Segment j starts at source
 * frame (int)((float)j * fps) (fps = pad + 0x1fc) when the clock reaches its grid point and crossfades 256 samples with
 * the one before. Only WHEN a segment starts comes from the clock; there is no clock-derived target to offset. Each
 * class-B pad owns one pool of four segments (pad + 0x30 + k * 0x70), shared by its two voices:
 *   +0x00 u8 active, +0x01 u8 done, +0x08 i64 position (whole source frames), +0x1c f32 fraction (the reader's frac),
 *   +0x20 i32 start delay (> 0: not started yet), +0x34 u32 step j, +0x3c u8 first-block flag (a pending launch).
 *
 * This: Slip is a constant circular shift of what every segment plays (stock frame + slip_f, folded into the file),
 * decided once per segment when stock creates it and applied where the segment reads:
 *   H1  clipwin_seg_start    the source prefetch in FUN_08065550, the segment start (bl FUN_0806375c @0x0806578c):
 *                            latch slot k's shift (and region), prefetch where it will really read
 *   H1' clipwin_slice_start  the same in FUN_08065290, slice-marker segments (bl FUN_0806375c @0x0806541a): no shift
 *   H2  clipwin_read         the segment read (filter_thunk.S clip_read_b ends here; filter.c's clip_read next)
 *   H3  clipwin_len          Region: the clip's length where it shapes the clip (four bl FUN_080636f0, below)
 *   H3' clipwin_wrap         Region: the recompute at the two wraps (bl FUN_08064a94), where a new region starts
 *   clipwin_tick             duck_block, once per block: one pad's Slip (and Loop Len) from the app's store; on a
 *                            change, mark the pad's pending segments done so stock re-makes them, and H1 re-latches, in
 *                            the same render
 * Stock's timing, crossfades, Sync re-grid, wrap, one-shot and launch logic are untouched, and with Slip 0 (and no
 * region, Loop Len Off) every hook passes through: bit-identical to stock. A Slip change is heard at the next Sync
 * step, through stock's crossfade.
 * A new file under a playing pad (a load, the browser's pre-listen into the pad, a take landing in it): stock does not
 * restart the voice; its segments read on at their positions in the new file. A segment latched for another file length
 * reads as stock does (H2), and the next one made latches the new file. A last step whose position is past the new
 * file's end would never end, and holds the pad on its step 0 (stock's own): the poll retires it (cw_retire).
 * Not covered: Slicer pads and Clip pads on Sync = Slice with markers (their segments start in H1': no shift); the
 * playhead on the waveform still shows the unslipped position.
 * Setting: "Slip:" on the Clip Pos page after Sync, -3840 .. +3840 ticks shown as beats.ticks ("+1.480" is one beat and
 * 480 ticks), + = ahead of the beat, - = behind (a CDJ jog: clockwise speeds up, counter-clockwise slows down), per
 * pad, saved with the preset as "clipslip". The knob: single ticks slow, faster as it turns faster (one curve), 1/64
 * steps at the top speed, and a detent on 0: a turn stops there, and passes after a pause, longer when it came
 * slowly (clipwin_turn).
 *
 * Region (notes/re/README.md section 3, a2, x3): a Clip pad plays its Sample-mode loop [Loop Start, Loop End) instead
 * of the whole file - no Trim. Stock keeps those points in Clip mode, in the cell's class-H object (pad + 8), so they
 * are read there. Stock is made to believe the file IS the region: the four fw_src_len calls that shape a clip (H3,
 * clipwin_len) answer the region's length, so Beat Count Auto, the frames per step and the last step's end follow it,
 * and every segment latches [rs, rs + vlen) in H1, which H2 reads circularly (the same latch Slip uses). A region
 * changed while the pad plays waits for its next wrap (clipwin_wrap, the recompute there, which runs when the next
 * pass's step 0 is made, about one Sync step before it sounds; a stopped pad takes it at its next recompute, the
 * launch's at the latest): changed mid-pass, the steps already made would point past the new end (notes/re/a2: 11 418
 * or 23 490 silent samples). One that moves the wrap grid (a longer clip) waits for a wrap on its own grid, where a
 * launch would start it: elsewhere stock snaps that pass's end into the past and doubles. When no such wrap can come
 * (the passes before had no grid, or never meet the new one) it is taken at once. Seamless wrap: with a region, Loop
 * On and Launch not Trigger the last step has no end, so it crossfades into the next pass like any step: no notch,
 * no gap when the region is shorter than its beats, no doubling when longer; a clip of one Sync step has that step
 * timed by the clip (H3 site 3), as stock times steps when there are more. A region under half a beat on Beat Count
 * Auto is a clip of 0 ticks: no grid, it loops on its length.
 * Setting: "Region:" Auto | File | Loop before Slip, saved as "clipregion". Auto = Loop: the loop points when 0 <=
 * start < end <= length and they are not the whole file ([0, length - 1] or more: what a load leaves, x3 t13); Sample
 * mode's Loop Mode is not asked (a Clip pad never shows that row). File = stock.
 *
 * Loop Len (notes/re/README.md section 3, a2 k_looplen): only a window of W ticks loops, on the clock, where the
 * music was when it was engaged (the KP3's loop). Stock keeps making its steps on its grid; each segment H1 makes is
 * latched to play the step of the window that lines up with its own: w = (origin + ((j x tps - origin) mod W)) / tps,
 * content = (int)((float)w x fps) + slip_f, stock's own product, so a window plays the frames its steps would. origin
 * = the phase of the frame the sounding segment that started last plays (its latch's, Slip taken out, so a window
 * still sounding after Off is taken again; else stock's position), x tps / fps, rounded down to W; taken when Loop Len
 * leaves Off and kept while it changes (the in-point stays), so the window holds the beat that was playing. A stopped
 * pad sets it back to 0: its next launch loops from the clip's start, as after power-on. A W the steps do not divide
 * (shorter than a Sync step) has the pad's Sync forced, as the app would set it (the class-B param-set, FUN_08067648
 * with 0x94): the largest Sync up to the user's that divides W, the origin and the clip, so the user's comes back as
 * soon as it divides them again (a longer W), and on Off, as the app's store has it. Stock re-grids the playing segment
 * there (notes/re/a1), so the change lands on the new grid. Never while a launch waits for its Quant point (the
 * re-grid would sound it at once); the poll tries again. Off: every new segment plays its own step again, in phase.
 * Needs Quant and Sync (no grid, or no clock phase, without them); a W of the whole clip or more does nothing.
 * Setting: "Loop Len:" Off | 1/16 | 1/8 | 1/4 | 1/2 | 1 bar | 2 bars | 4 bars after Slip, saved as "cliplooplen".
 *
 * Fit: a loop that is no whole number of beats, or a region under a WAV's own Beat Count, is re-placed at every Sync
 * step (Mk1 Clip mode never stretches). Fit makes what the pad plays last a whole number of beats at the tempo - Auto
 * the nearest (14.015 -> 14), else the list's - by storing stock's own step fields again at H3 site 3 (cw_fit: the wrap
 * grid, ticks and steps, frames and output samples per step) with the rate every segment takes (+0x1f0), so each step
 * lands where the audio already is. A clip that is no whole number of Quants is polymetric: its wrap grid is gcd(Quant,
 * clip), its steps gcd(Sync, clip). It is taken with the region; the poll recomputes a fitted pad when the tempo moves;
 * a fitted file wraps seamlessly, as a region does.
 * Setting: "Fit:" Off | Auto (Bars) | Auto (Beats) | 1/4 | 1/2 | 3 beats | 1 bar | 6 beats | 2 bars | 4 bars |
 * 8 bars after Loop Len, saved as "clipfit".
 *
 * Loop Fade on a Region (without it the seam is a hard splice): Sample mode's own row (0xfa), taken with the
 * region; the region's last F = (int)(vlen x row / 1000) frames (at most Loop Start) crossfade, equal-gain and linear
 * as Sample mode's, into the F before Loop Start: H2 reads such a window twice, the second time vlen earlier, and
 * mixes them (cw_map, cw_fade). Not in a machine mode, nor above a rate of ~3.9, nor while Loop Len is taken. The
 * seam hint then goes to where the copy starts and to Loop Start. Setting: stock's Loop Fade row, after Fit.
 *
 * The Waveform screen in Clip mode (notes/re/a3, README section 3): stock unbinds all four knobs and draws no loop
 * bracket. TL = Loop Start, TR = Loop End (stock's 0x91 / 0x92, sample positions one zoom pixel a step, ranged as in
 * Sample mode), BL = Slip, BR = Loop Len; the white bracket shows the loop Region plays, from the view's store, so a
 * playing pad catches up with it at its next wrap (clipwin_bind, clipwin_zoom, clipwin_wave). The view's own forward
 * stores them all. A TL or TR turn takes the view to the edge it moves, as a tap on the overview does, and the view
 * follows the playhead again after a pause.
 *
 * Bank 2: the maths and the policy of every hook below are in flash bank 2, clipwin_b2.c (the cw_* functions: the
 * latch, the read's mapping and seam hint, Region's rule and its adoption, the lengths H3 tells, the wrap's hold, the
 * poll and its drop, Loop Len's take, its window and its Sync message, the knob's tiers and detent, the Slip row's
 * text, the bracket). This file keeps the hooks, every stock call they make and the bank's set-up, which leaves room in
 * the bank 1 cave. bank() asks b2_live() first: without this build's payload up there every hook passes straight
 * through to stock, so every Clip pad plays as stock does, Slip, Region, Loop Len, Fit and Loop Fade do nothing (their
 * rows are kept, as stored), the Slip row shows stock's plain number and the waveform no bracket.
 */
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef int (*src_int_fn)(void *src);
typedef void (*prefetch_fn)(void *src, int32_t pos);
typedef void (*fetch_fn)(void *src, float *dst, int n, int32_t pos, int zero);
typedef void (*fetch2_fn)(void *src, float *left, float *right, int n, int32_t pos);
typedef int (*buf_int_fn)(void *buf);
typedef float *(*buf_mono_fn)(void *buf);
typedef int (*buf_pair_fn)(void *buf, float **left, float **right);
typedef void (*kernel_fn)(float rate, const float *src, int n_src, int *used, float *frac, float *dst, int n);
typedef void (*knob_fn)(uint8_t *knob);
typedef int (*knob_value_fn)(uint8_t *knob, int value);
typedef void (*text_fn)(void *widget, const char *text);
typedef void (*ring_push_fn)(void *ring, int counts, uint32_t ms);
typedef unsigned (*ring_speed_fn)(void *ring);
typedef void (*stepper_fn)(void *stepper, int counts);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*recompute_fn)(uint8_t *pad, void *clock);
typedef void (*pad_param_fn)(uint8_t *pad, void *clock, const void *msg, void *ctx);
#define fw_register_num ((register_num_fn)FN(0x0808c12c))
#define fw_pad_param    ((pad_param_fn)FN(0x08067648))   /* the class-B param-set: what a 0x39 message does */
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_recompute    ((recompute_fn)FN(0x08064a94))   /* the class-B pad's recompute: lengths, steps, Beat Count Auto */
#define fw_store_add    ((store_add_fn)FN(0x08093ef6))
#define fw_setting      ((setting_fn)FN(0x08093e9c))
#define fw_src_len      ((src_int_fn)FN(0x080636f0))
#define fw_src_stereo   ((src_int_fn)FN(0x08063790))
#define fw_prefetch     ((prefetch_fn)FN(0x0806375c))
#define fw_fetch        ((fetch_fn)FN(0x08063634))
#define fw_fetch2       ((fetch2_fn)FN(0x08063608))
#define fw_buf_frames   ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_mono     ((buf_mono_fn)FN(0x0804d934))
#define fw_buf_pair     ((buf_pair_fn)FN(0x0804da0c))
#define fw_kernel       ((kernel_fn)FN(0x080603ec))      /* the stock clip reader's four-point kernel */
#define fw_format       ((knob_fn)FN(0x080b0528))        /* a knob's value text */
#define fw_knob_redraw  ((knob_fn)FN(0x080b0480))        /* composes the knob's line: "name value" */
#define fw_knob_name    ((text_fn)FN(0x080b03c0))        /* the knob's name (its + 0x44 text) */
#define fw_list_value   ((knob_value_fn)FN(0x080b0416))  /* type 9: the value a list position stands for */
#define fw_set_text     ((text_fn)FN(0x080c3b98))
#define fw_ring_push    ((ring_push_fn)FN(0x080b0cc4))   /* the knob's 8-entry acceleration ring */
#define fw_ring_speed   ((ring_speed_fn)FN(0x080b0ce0))  /* 1 .. 6 from |sum of counts| / span */
#define fw_stepper_add  ((stepper_fn)FN(0x080b0b74))
#define GUI_MS          (*(volatile uint32_t *)0x2402eee0u)

#define P_REGION    0x1c8            /* ours: 0x1c8..0x1cf are unused by stock (notes/re/a0) */
#define P_SLIP      0x1c9
#define P_LOOPLEN   0x1ca            /* Off, then 1/16 << (value - 1) */
#define P_FIT       0x1cb            /* Off, Auto (Bars), Auto (Beats), then 1/4 .. 8 bars (clipwin_b2.c's fit_beats) */
#define CLOCK_CTX   0x128e0          /* the modules' context, from the engine (= the clock, notes/re/a4) */
#define P_LOOP_START 0x91            /* stock's Sample-mode loop: Loop Start, Loop End, frames */
#define P_LOOP_END  0x92
#define P_LOOP_FADE 0xfa             /* stock's Sample-mode Loop Fade: 0 .. 1000 (clipwin_b2.c cw_map, cw_fade) */
#define TYPE_INT    1
#define APP_PADS    (0x24020088u + 0x1840u)   /* the app's pad stores: + row * 0xf0 + col * 0x30 */

/* knob widget (notes/re/a3) */
#define KNOB_PARAM  0x14
#define KNOB_TYPE   0x31
#define KNOB_VALUE  0x34
#define KNOB_TEXT   0x9c
#define KNOB_STEP0  0x270            /* the stepper; its index at + 0x27c, its start at + 0x288 */
#define KNOB_RING   0x294
#define KNOB_FROZEN 0x2d8

uint8_t *master_block(void);         /* master.c: the boot-time SDRAM block, or 0 */
int b2_live(void);                   /* cpu.c: may bank 2 be run (this build's payload, read clean) */
int clip_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used, float *frac,
              void *scratch, void *out, void **result);
int clip_read_ring(float rate, uint8_t *pad, uint8_t *filter, int32_t real, int32_t rs, int32_t vlen, int n, int *used,
                   float *frac, void *scratch, void *out, void **result);
void clip_fetch(void *src, int stereo, float *l, float *r, int count, int32_t start, int32_t rs, int32_t vlen);

/* ---- the setting ---- */

/* master.c calls these from its registration and pad-defaults chains. */
void clipwin_register(void *table)
{
    static const char *const region_names[3] = {"Auto", "File", "Loop"};
    /* stock's own strings: "Off", then Quant Size's names (0x080ecb08) from 1/16 up to 4 bars */
    static const char *const looplen_names[LOOPLEN_MAX + 1] = {
        (const char *)0x080cd7a8, (const char *)0x080ce714, (const char *)0x080ce710, (const char *)0x080ce70c,
        (const char *)0x080ce708, (const char *)0x080ce700, (const char *)0x080ce6f8, (const char *)0x080ce6f0};
    /* stock's "Off", Quant Size's names for 1 beat .. 8 bars, and our own: the two Autos and two lengths between */
    static const char *const fit_names[FIT_MAX + 1] = {
        (const char *)0x080cd7a8, "Auto (Bars)", "Auto (Beats)", (const char *)0x080ce70c, (const char *)0x080ce708,
        "3 beats", (const char *)0x080ce700, "6 beats", (const char *)0x080ce6f8, (const char *)0x080ce6f0,
        (const char *)0x080ce6e8};
    fw_register_list(table, P_REGION, "Region:", region_names, 3, "clipregion");
    fw_register_num(table, P_SLIP, TYPE_INT, "Slip:", -SLIP_MAX, SLIP_MAX, "clipslip");
    fw_register_list(table, P_LOOPLEN, "Loop Len:", looplen_names, LOOPLEN_MAX + 1, "cliplooplen");
    fw_register_list(table, P_FIT, "Fit:", fit_names, FIT_MAX + 1, "clipfit");
}

void clipwin_defaults(void *store)
{
    for (int p = P_REGION; p <= P_FIT; p++)   /* Region, Slip, Loop Len, Fit (0x1c8 .. 0x1cb), in that order */
        fw_store_add(store, p, 0);   /* stock only overwrites ids already in a store: without these nothing saves */
}

/* ---- the engine ---- */

/* The bank, when bank 2 holds this build's payload (every hook's maths is there) and the boot-time SDRAM block is up;
   else 0, and the hook is stock's. */
static __attribute__((noinline)) struct cw_bank *bank(void)
{
    uint8_t *mem = b2_live() ? master_block() : 0;
    if (!mem)
        return 0;
    struct cw_bank *b = (struct cw_bank *)(mem + CW_OFFSET);
    if (b->magic != CW_MAGIC) {
        /* all of it zero: master_alloc clears only the magic, and SDRAM keeps the rest through a reset (a word loop,
           smaller than clearing the fields that need it, which it covers) */
        for (uint32_t *w = &b->magic; w < (uint32_t *)(b + 1); w++)
            *w = 0;
        b->magic = CW_MAGIC;
    }
    return b;
}

/* ...and pad's index q (cw_pad), when it is one of the sixteen pads */
static __attribute__((noinline)) struct cw_bank *pad_bank(const uint8_t *pad, int *q)
{
    struct cw_bank *b = bank();
    return b && (*q = cw_pad(pad)) >= 0 ? b : 0;
}

static const void *pad_store(unsigned q)
{
    return (const void *)(APP_PADS + (q + (q >> 2)) * 0x30u);   /* row * 0xf0 + col * 0x30 */
}

/* H3. Replaces bl FUN_080636f0 (fw_src_len, r0 = the source; r4 = the pad, clipwin_thunk.S) at 0x08064b2c (site 1: the
   recompute's first, Beat Count Auto and the frames per step), 0x08064c5a (site 3: its second, the file tempo, right
   after it stored the step fields; clip = r9 there, the clip in output samples), 0x0806561e (site 0: FUN_08065550's
   > 0 check) and 0x08065690 (site 2: the last step's end, length - 1). Never at 0x080662f6: the reader's bound keeps
   the real length, clipwin_read folds. A playing pad takes its region only at its wrap; a stopped one at its next
   recompute, which nothing triggers when only the Region row or the loop points change: at the latest the one before
   its next voice start (0x0806838a, 0x08068632, 0x080686a8), so until the launch the clip length told the app (msg
   0x8d) can be the old one. The answer is cw_len's; at site 1 it is handed the store rows the region comes from, Fit
   and Loop Fade. At site 3 a fitted pad's step fields are stored again there (cw_fit). */
static const uint16_t region_rows[CW_SET_ROWS] = {P_REGION, P_LOOP_START, P_LOOP_END, P_FIT, P_LOOP_FADE};  /* CW_SET */

int32_t clipwin_len(void *src, uint8_t *pad, int site, int32_t clip)
{
    int32_t len = fw_src_len(src), set[CW_SET_ROWS];
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (!b)
        return len;
    for (unsigned i = 0; site == 1 && i < CW_SET_ROWS; i++)
        set[i] = fw_setting(pad_store((unsigned)q), region_rows[i]);
    return cw_len(b, (unsigned)q, pad, site, clip, len, set);
}

/* H3'. Replaces bl FUN_08064a94 (the recompute, r0 = pad, r1 = the clock) at 0x08066fac (the synced wrap; t = the
   render's [sp + 0x58], the tick the new pass starts on, snapped to the old +0x230) and 0x08066e9e (the unsynced one;
   t = 0), through clipwin_thunk.S: the region changed while the pad played starts with this pass.
   Unless it moves the wrap grid off this pass (cw_hold): stock snaps a pass's end to +0x230 = min(Quant, clip), so a
   longer clip whose first pass does not start on its own grid has that end snapped back into the past, and the next
   pass sounds at once over the last step: two early passes at gain 2, then the bar (stock does exactly that after a
   live Beat Count change). Such a region waits for a wrap on its grid, where a launch would have started it, when one
   can come (cw_hold: the old wrap grid and clip, read here before the recompute, say where the passes start). */
void clipwin_wrap(uint8_t *pad, void *clock, const uint32_t *t)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (!b) {
        fw_recompute(pad, clock);
        return;
    }
    int32_t was[4] = {b->region[q].rs, b->region[q].vlen, *(const int32_t *)(pad + PAD_WRAP_GRID),
                      *(const int32_t *)(pad + PAD_TPS) * *(const int32_t *)(pad + PAD_STEPS)};   /* CW_WAS_* */
    b->wrap = (uint8_t)(q + 1);
    fw_recompute(pad, clock);
    b->wrap = 0;
    if (cw_hold(b, (unsigned)q, pad, t, was))
        fw_recompute(pad, clock);
}

/* H1. src = pad + 0x24, pos = stock's prefetch point max(0, start - 8), k = the segment slot ([sp + 0x20] in
   FUN_08065550, clipwin_thunk.S), pad = r4. The segment's start (+0x08) and step (+0x34) are final here: cw_latch
   latches slot k's shift (and region) and says where to prefetch, where it will really read. */
void clipwin_seg_start(void *src, int32_t pos, unsigned k, uint8_t *pad)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (b)
        pos = cw_latch(b, (unsigned)q, k, pad, fw_src_len(src), pos);
    fw_prefetch(src, pos);
}

/* H1': a slice-marker segment takes slot k: whatever was latched there no longer applies */
void clipwin_slice_start(void *src, int32_t pos, unsigned k, uint8_t *pad)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (b)
        cw_slice(b, (unsigned)q, k);
    fw_prefetch(src, pos);
}

/* duck_block calls this once per engine block, before the pads render, with the engine (the clock): one pad's Slip
   and Loop Len per call (16 within 43 ms), cw_tick's; the segments the pad's file no longer reaches retired
   (cw_retire). Loop Len's Sync, when it asks for one, goes to the pad as the app would set it: the class-B param-set
   with {0x39, cell, 0x94, idx}, the clock and its context (the only caller, 0x080685d2, passes exactly these). It
   re-grids the playing segments from their own positions and marks the pending ones done (notes/re/a1). Then, on a
   change, the guarded drop (cw_drop), and the launches waiting for their Quant point latched again in place. */
void clipwin_tick(uint8_t *engine)
{
    struct cw_bank *b = bank();
    if (!b)
        return;
    unsigned q = b->scan++ & 15;
    const void *store = pad_store(q);
    int32_t slip = fw_setting(store, P_SLIP);
    unsigned ll = (unsigned)fw_setting(store, P_LOOPLEN);
    uint32_t msg[6];
    int r = cw_tick(b, q, slip, ll, engine && (ll | b->ll[q]) ? (uint32_t)fw_setting(store, P_SYNC) : 0, engine, msg);
    uint8_t *pad = b->pad[q];
    if (r & 8)                           /* Fit: a fitted pad made at another tempo */
        fw_recompute(pad, engine);
    if (r & 4) {                         /* a segment its file no longer reaches (cw_retire) */
        int32_t len = fw_src_len(*(void **)(pad + PAD_SOURCE));
        cw_retire(pad, len);
        /* A Sync or Quant set while the slot was closed re-gridded the playing segments onto a step of the
           closed slot's 2^28-frame clip (+0x200 keeps the frames per step it re-gridded from), and the recompute at
           the open re-grids nothing, so the pad sounds no segment for millions of samples. Its own Sync, sent again,
           re-grids them from the open file (the class-B param-set has no same-value check, notes/re/a2). Only a
           step of the closed slot (SRC_BAD / n, to a frame a step) longer than the whole file: a shorter take
           under a pad synced the ordinary way (+0x200 the old file's step) stays stock's. The param-set stores the
           new step, so it is sent once. Never while a launch waits for its Quant point: any Sync message sounds it
           at once (droplaunch). */
        float was = *(const float *)(pad + PAD_FPS_WAS);
        uint32_t w = was > (float)len && was <= (float)SRC_BAD ? (uint32_t)(was + 0.5f) : 0;
        uint32_t n = w ? (SRC_BAD + w / 2) / w : 0;
        if (engine && !(r & 2) && len > 0 && len < SRC_BAD && pad[PAD_SYNCED] && n &&
            n * w + n >= SRC_BAD && n * w <= SRC_BAD + n) {
            int wait = 0;
            for (unsigned k = 0; k < 4; k++) {
                const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
                wait |= seg[0] && !seg[1] && seg[SEG_FIRST];
            }
            if (!wait) {
                msg[0] = 0x39;
                msg[1] = 0;
                msg[2] = *(const uint32_t *)(pad + PAD_ID);
                msg[3] = P_SYNC;
                msg[4] = (uint32_t)fw_setting(store, P_SYNC);
                msg[5] = 0;
                r |= 2;
            }
        }
    }
    if (r & 2)
        fw_pad_param(pad, engine, msg, engine + CLOCK_CTX);
    if (!(r & 1))
        return;
    unsigned again = cw_drop(b, q, pad);
    for (unsigned k = 0; k < 4; k++)
        if (again & (1u << k)) {
            void *src = *(void **)(pad + PAD_SOURCE);
            fw_prefetch(src, cw_latch(b, q, k, pad, fw_src_len(src), -1));
        }
}

/* H2: in place of filter.c's clip_read, with its arguments (the stock reader FUN_080662e4's). */
int clipwin_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used,
                 float *frac, void *scratch, void *out, void **result)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    const struct cw_latch *l = b ? cw_slot(b, (unsigned)q, pad, frac) : 0;
    if (!l)
        return clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    void *src = *(void **)(pad + PAD_SOURCE);
    /* The file changed under the segment since H1 (notes/re/x3 section 4: the slot closes, fw_src_len answers 0, then
       the new file's length). Stock reads on at the segment's position in the new file; the latch's region and shift
       belong to the old length and could map past the new end. Read as stock does while the length differs: the next
       segment made latches the new file, and a file of the latched length (back after a close) maps as before. Not
       the source pointer: the key map hands the freed asset entry out again, so a load often keeps it. */
    if (fw_src_len(src) != l->len)
        return clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    int32_t rs = l->rs, vlen = l->vlen, at[2];
    /* where it really reads (at[0]), and Loop Fade's frames (at[1], cw_map) */
    cw_map(b, (unsigned)q, pad, l, pos, at);
    int32_t real = at[0];
    int straight = rate == 1.0f && *frac == 0.0f;
    int cap = fw_buf_frames(scratch);
    int count = straight ? n : (int)((float)n * rate) + 8;
    if (count > cap)
        count = cap;
    /* A machine mode: filter.c's machine reader over the circular region, seam or not (it fetches from real - 3,
       n x rate + 8 frames even at rate 1). */
    int ring = clip_read_ring(rate, pad, filter, real, rs, vlen, n, used, frac, scratch, out, result);
    /* Loop Fade, not in a machine mode, and when the window and its copy both fit the scratch (a rate up to about
       3.9): the reads reaching into the region's last F frames take the seam's path. The seam hint once a crossing
       segment is within its reach (cw_hint): at rs; with a fade, where its copy starts and at rs as well (a hint
       reaches 16 384 frames for sure, a fade can be longer, and on a slipped pad nothing else hints rs). */
    int32_t fade = ring < 0 && 2 * count <= cap ? at[1] : 0, edge = rs + vlen - fade;
    if (cw_hint(b, (unsigned)q, l, real, fade)) {
        if (fade)
            fw_prefetch(src, rs - fade);
        fw_prefetch(src, rs);
    }
    if (ring >= 0)
        return ring;
    /* No seam in the window the read needs: stock's reader at the real position. Stock adds `used` to its own
       position, which stays the unslipped one: the next block maps it again. */
    if (real + count <= edge)
        return clip_read(rate, pad, filter, real, 0, n, used, frac, scratch, out, result);
    /* The read crosses the end of the region (once a pass): the stock reader's own work, with the fetch in two parts
       so the kernel interpolates across the seam as if the file were circular. */
    int stereo = fw_src_stereo(src);
    float *sl = 0, *sr = 0;
    if (stereo)
        fw_buf_pair(scratch, &sl, &sr);
    else
        sl = fw_buf_mono(scratch);
    clip_fetch(src, stereo, sl, sr, count, real, rs, vlen);
    /* Loop Fade: the same window vlen earlier (before Loop Start), after it in the scratch, and the crossfade */
    if (fade) {
        clip_fetch(src, stereo, sl + count, stereo ? sr + count : 0, count, real - vlen, 0, 0);
        cw_fade(sl, sr, count, real - edge, fade);
    }
    if (straight) {
        *used = n;
        *result = scratch;
        return 1;
    }
    if (stereo) {
        float *ol = 0, *orr = 0;
        fw_buf_pair(out, &ol, &orr);
        int u = *used;
        float f = *frac;
        fw_kernel(rate, sl, count, &u, &f, ol, n);
        fw_kernel(rate, sr, count, used, frac, orr, n);
    } else {
        fw_kernel(rate, sl, count, used, frac, fw_buf_mono(out), n);
    }
    *result = out;
    return 1;
}

/* ---- the knob ---- */

/* Replaces the value-text call (bl FUN_080b0528) at 0x080b0746 (set value, every type) and 0x080b0e18 (type-1 turn):
   the Slip row reads beats.ticks with its sign (cw_text), stock's plain number without bank 2. */
void clipwin_format(uint8_t *knob)
{
    unsigned type = knob[KNOB_TYPE];
    if (*(int32_t *)(knob + KNOB_PARAM) != P_SLIP || knob[KNOB_FROZEN] || (type != TYPE_INT && type != 9) ||
        !b2_live()) {
        fw_format(knob);                 /* a reset knob keeps a stale id with type 0: the type test matters */
        return;
    }
    uint8_t *st = knob + KNOB_STEP0;
    int v = type == TYPE_INT ? *(int32_t *)(st + STEPPER_INDEX) + *(int32_t *)(st + STEPPER_START)
                             : fw_list_value(knob, *(int32_t *)(knob + KNOB_VALUE));
    char text[16];
    cw_text(text, v);
    fw_set_text(knob + KNOB_TEXT, text);
    fw_knob_redraw(knob);
}

/* Replaces the stepper call of the type-1 turn path (bl FUN_080b0b74 @0x080b0dde), which every screen's turn of a
   type-1 knob goes through: the Pos page's list and the Clip-mode Waveform screen's BL are the same code. For the
   Slip knob: the event goes into the stock accelerator's ring, and cw_turn (its gain by the speed, the detent on 0;
   clipwin_b2.c has the rule and its numbers) says what the stepper gets. Without bank 2, stock's stepper as it was
   called. */
void clipwin_turn(uint8_t *stepper, int counts)
{
    uint8_t *knob = stepper - KNOB_STEP0;
    if (*(int32_t *)(knob + KNOB_PARAM) != P_SLIP || knob[KNOB_TYPE] != TYPE_INT || !counts || !b2_live()) {
        fw_stepper_add(stepper, counts);
        return;
    }
    struct cw_bank *b = bank();
    uint32_t now = GUI_MS;
    int32_t add;
    fw_ring_push(knob + KNOB_RING, counts, now);
    if (cw_turn(b, stepper, counts, fw_ring_speed(knob + KNOB_RING), now, &add))
        fw_stepper_add(stepper, add);
}

/* ---- the Waveform screen in Clip mode (notes/re/a3, README section 3) ---- */

/* Stock unbinds all four knobs there and draws no loop bracket. This binds TL = Loop Start (0x91), TR = Loop End (0x92):
   stock's own Sample-mode rows, sample positions (type 0xd) one zoom pixel a step, ranged as stock ranges them in
   Sample mode (Loop Start 0 .. Loop End, Loop End Loop Start .. the length); BL = Slip, BR = Loop Len, the Pos page's
   rows (Slip with its own text and turn, clipwin_format and clipwin_turn). The view's generic forward stores every one
   of them (0x3d at 0x080a6c6c, a list's 0x3c at 0x080a6c10: SetCellParam), and the class-H object takes Loop Start
   and End from the queue as in Sample mode, where Region reads them: no code. The white bracket shows the loop when
   Region plays it.
   The view (FUN_080a54a0's): + 0x38 the waveform widget, + 0x1a0 its zoom (f32 frames per pixel), knobs TL + 0x670,
   BL + 0x950, TR + 0xc30, BR + 0xf10, + 0x2168 the overview strip, + 0x29c its pad's cell (row << 4 | col), + 0x2370
   its copy of the pad's store (FUN_0809a830 at each setup: its rows, then + 0x20 = the store's + 0x20, the app's file
   length, as + 0x2390).
   That length is not always the pad's file (on a unit, pad 1 = a 336 359-frame file: TR stopped at 192 000 and Loop End
   192 000 hid the bracket; the view froze at 57 % of the loop). The app writes the store's + 0x20 only in its 0xE
   handler FUN_080a121c (0x080a12d0), into the first cell (row 0 col 0 first, FUN_0809a9c4) whose pad record holds the
   asset just opened, and the pad load FUN_080a0ac8 zeroes it: a file that two pads' records name (the browser loads its
   files into the pad it was opened from) gives its length to the first of them only. Both pad stores read 192 000 on
   the unit, B's take. Stock's Sample screen reads it too; the Clip screen here takes the engine's: what fw_src_len
   answered at the pad's last recompute (cw_bank's flen, H3 site 1), the length Region's rule and the reader use. */
typedef void (*bind_fn)(int param, int value, uint8_t *knob);
typedef void (*range_fn)(uint8_t *knob, int lo, int hi);
typedef void (*view_zoom_fn)(uint8_t *view, int zoom);
typedef void (*wave_fn)(uint8_t *wave, const void *slices);
typedef void (*len_fn)(uint8_t *widget, int32_t len);
#define fw_bind         ((bind_fn)FN(0x080a7ee0))        /* the view's binder: label, type, range from the table; value */
#define fw_revalue      ((bind_fn)FN(0x080a7fe6))        /* the view's re-value: a list's position, else knob_value */
#define fw_knob_range   ((range_fn)FN(0x080b09e4))
#define fw_knob_value   ((knob_value_fn)FN(0x080b0790))
#define fw_view_zoom    ((view_zoom_fn)FN(0x080a52c4))   /* the position knobs' step, range, value: not for Clip */
#define fw_wave_slices  ((wave_fn)FN(0x080c6e8c))
#define fw_overview_len ((len_fn)FN(0x080c4df0))      /* the overview strip's length (as len / 16, f32) */
#define fw_wave_show    ((len_fn)FN(0x080c6e68))      /* the view to a frame, held 300 ticks: the overview's tap */
#define VIEW_WAVE   0x38
#define VIEW_OVERVIEW 0x2168
#define VIEW_CELL   0x29c
#define VIEW_STORE  0x2370
#define VIEW_LEN    0x2390
#define WAVE_LEN    0x254            /* the waveform's length: its tick clamps the playhead (and its scroll) to it */
#define VIEW_BR     0xf10
#define P_PAD_MODE  0x8b             /* Pad Mode: Sample, Clip, Slicer, Granular, New Rec, New Multi */
#define PAD_MODE_CLIP 1
#define KNOB_STEP   0x28c            /* type 0xd: frames per step */

/* the knob (its offset in the view << 16) and its row */
static const uint32_t clip_knobs[4] = {0x670u << 16 | P_LOOP_START, 0xc30u << 16 | P_LOOP_END, 0x950u << 16 | P_SLIP,
                                       VIEW_BR << 16 | P_LOOPLEN};
/* ...and its name on this screen. A knob shows "name value" in one line (FUN_080b0480's "%s %s"), 12 px a character
   (the 6 x 8 font at size 0x10), in a box of 151 px from x 6 (TL, BL: left-aligned) or ending at x 309 (TR, BR:
   right-aligned): twelve characters stay in their box. The table's names ("Loop Start:", "Loop End:", "Loop Len:") ran
   the left value under the right knob's text. Stock's Sample mode renames its four after binding too ("Str:", "Len:",
   "LpStr:", "LpEnd:"). The two positions get three letters, so that eight digits still fit ("LpS 12345678": a file of
   up to 99 999 999 frames, 34 minutes at 48 kHz; "LpStr 1234567" would cross into its neighbour from 1 000 000 frames,
   21 s); the bottom row's values are short ("Slip -4.000", "LpLen 4 bars"). */
static const char clip_names[4][6] = {"LpS", "LpE", "Slip", "LpLen"};

/* Replaces bl FUN_080a7ee0 @0x080a582a, the last of the Clip bind block's four unbinds (BR; r2 = view + 0xf10, the
   other three have run): binds all four, through the view's own binder, with the values of the view's store, then
   names them as above (the binder sets the table's name) and has each knob compose its line again. */
void clipwin_bind(int param, int value, uint8_t *knob)
{
    (void)param;
    (void)value;
    uint8_t *view = knob - VIEW_BR;
    for (unsigned i = 0; i < 4; i++) {
        unsigned id = clip_knobs[i] & 0xffff;
        uint8_t *k = view + (clip_knobs[i] >> 16);
        fw_bind((int)id, fw_setting(view + VIEW_STORE, id), k);
        fw_knob_name(k, clip_names[i]);
        fw_knob_redraw(k);
    }
}

/* The length of the view's pad's file: the engine's (flen), when its bank is up and a recompute has measured it; else
   the view's own (stock's). */
static int32_t clip_len(const uint8_t *view)
{
    int32_t len = *(const int32_t *)(view + VIEW_LEN);
    unsigned cell = *(const uint16_t *)(view + VIEW_CELL), row = (cell & 0xff) >> 4, col = cell & 0xf;
    struct cw_bank *b = !(cell & 0x1f00) && row < 4 && col < 4 ? bank() : 0;
    if (b && b->flen[row * 4 + col] > 0 && b->flen[row * 4 + col] < SRC_BAD)
        len = b->flen[row * 4 + col];
    return len;
}

/* The knobs and the bracket from the view's store; step = frames per pixel for the two position knobs, 0 = as they
   are. The binder leaves a type-0xd knob at the table's range (0 .. 1000) with its value only pending, and one turn
   would post the clamped value (notes/re/a3): the step goes first (the range is counted in steps of it), then the
   range, then the value, as stock does for Sample mode. was = the bracket as last drawn: the stock refresh clears it
   without marking the widget dirty, and so would leave a bracket that is gone on the screen.
   A TL or TR turn (a refresh, step 0, that moved one edge of the bracket) takes the view to that edge, as a tap on the
   overview strip takes it to the frame tapped (FUN_080c6e68, the view handler's 0x080a6cc0): the waveform's tick
   (FUN_080c6c34) holds it there while its count (+ 0x180, 300 ticks from each turn) runs, then follows the playhead
   again (else the playhead runs the edge being set off the screen). Not on a bind or a zoom. */
static void clip_view(uint8_t *view, int step, int was)
{
    uint8_t *tl = view + (clip_knobs[0] >> 16), *tr = view + (clip_knobs[1] >> 16), *wave = view + VIEW_WAVE;
    if (*(int32_t *)(tl + KNOB_PARAM) != P_LOOP_START)
        return;                      /* another mode's knobs (FUN_080a53a2 runs for every mode) */
    if (step) {
        *(int32_t *)(tl + KNOB_STEP) = step;
        *(int32_t *)(tr + KNOB_STEP) = step;
    }
    const void *st = view + VIEW_STORE;
    int32_t ls = fw_setting(st, P_LOOP_START), le = fw_setting(st, P_LOOP_END), len = clip_len(view);
    fw_knob_range(tl, 0, le);
    fw_knob_value(tl, ls);
    fw_knob_range(tr, ls, len);
    fw_knob_value(tr, le);
    /* Slip and Loop Len: re-valued only when the store has another value. Every turn comes back as a refresh, and
       a set value parks the stepper mid-step: done each time, it would make the Slip knob twice as fast here as on
       the Pos page (which does not re-value). */
    for (unsigned i = 2; i < 4; i++) {
        uint8_t *k = view + (clip_knobs[i] >> 16);
        unsigned id = clip_knobs[i] & 0xffff;
        int v = fw_setting(st, id);
        if (*(int32_t *)(k + KNOB_STEP0 + STEPPER_INDEX) + *(int32_t *)(k + KNOB_STEP0 + STEPPER_START) != v)
            fw_revalue((int)id, v, k);
    }
    /* the bracket, when Region plays the loop (cw_bracket); without bank 2 none, as stock */
    if (b2_live()) {
        int32_t edge = cw_bracket(wave, fw_setting(st, P_REGION), ls, le, len, was);
        if (!step && edge >= 0)
            fw_wave_show(wave, edge);
    }
}

/* Replaces bl FUN_080a52c4 @0x080a53b0, in FUN_080a53a2 (r1 = (int)zoom): every bind of the screen, every zoom change
   (msg 0xe5, which no refresh follows). Stock returns at once for Clip. Only in Clip mode: New Rec and New Multi bind
   nothing, so after Clip the knobs still hold these rows there (as they hold Sample's after Sample, on stock). The bind
   block has just given the waveform (FUN_080c6f44: + 0x254, its playhead's clamp) and the overview strip (FUN_080c4df0)
   the view's own length; they take the pad's file's here (as above: a 336 359-frame loop whose view stopped scrolling
   at 192 000). */
void clipwin_zoom(uint8_t *view, int zoom)
{
    fw_view_zoom(view, zoom);
    if (fw_setting(view + VIEW_STORE, P_PAD_MODE) != PAD_MODE_CLIP)
        return;
    int32_t len = clip_len(view);
    if (len > 0) {
        *(int32_t *)(view + VIEW_WAVE + WAVE_LEN) = len;
        fw_overview_len(view + VIEW_OVERVIEW, len);
    }
    clip_view(view, zoom > 0 ? zoom : 1, view[VIEW_WAVE + WAVE_LOOP_ON]);
}

/* Replaces bl FUN_080c6e8c @0x080a5b0e (the slice markers), the Clip case of the screen's refresh: every setup and every
   0x66 of the pad (any of its settings stored). */
void clipwin_wave(uint8_t *wave, const void *slices)
{
    int was = wave[WAVE_LOOP_ON];
    fw_wave_slices(wave, slices);
    clip_view(wave - VIEW_WAVE, 0, was);
}

/* Replaces bl FUN_080c6acc @0x080c6dca, in the waveform's tick FUN_080c6c34 (the view's, 0x080a6f70: wave = view +
   0x38), every tick, just after it set the playhead line's pixel (+ 0x23c). In Clip mode the bind block pins that line
   to the view's anchor pixel (+ 0x240) and scrolls the waveform under it (FUN_080c6f44 @0x080a55e4: + 0x248 = 1, as
   for Slicer), so while the view holds on a frame (follow mode + 0x1e0 = 2: a TL or TR turn, clip_view, or a tap on
   the overview) the line marks that frame, the edge being set, not the playhead. It goes then, to the pixel left of the
   waveform's box, which the draw skips (FUN_080c6338 @0x080c68f2), and the tick puts it back once the view follows the
   playhead again. A stopped pad's view holds until it plays, and so does the line. Every other mode keeps stock's
   line. */
#define WAVE_X      0x4
#define WAVE_FOLLOW 0x1e0
#define WAVE_LINE   0x23c
#define WAVE_FIXED  0x248
#define fw_wave_tiles ((len_fn)FN(0x080c6acc))

void clipwin_line(uint8_t *wave, int32_t anchor)
{
    if (wave[WAVE_FOLLOW] == 2 && wave[WAVE_FIXED] &&
        fw_setting(wave - VIEW_WAVE + VIEW_STORE, P_PAD_MODE) == PAD_MODE_CLIP)
        *(int32_t *)(wave + WAVE_LINE) = *(int32_t *)(wave + WAVE_X) - 1;
    fw_wave_tiles(wave, anchor);
}

/* ---- the playhead ---- */

/* H5. Replaces bl FUN_0804f504 @0x080668fc (clipwin_playhead_b: r6 = the pad, fp = the segment's slot): the render
   posting the playhead (msg 0x4a: + 0x10 the position, + 0x14 its per mille of the file) after it read one of the pad's
   segments. Stock posts the segment's own position: unslipped, counted from the region's start, never into Loop Len's
   window, so on a region from 6 072 the line ran 6 072 frames behind the audio and wrapped before Loop End. The line
   shows the frame heard instead (cw_playhead), its per mille as stock reckons it. The render keeps stock's position for
   itself (pad + 0x248), to post only a change; without bank 2 the message is stock's. */
#define MSG_POS     0x10
#define MSG_MILLE   0x14
typedef void (*post_fn)(void *ui, void *msg);
#define fw_post     ((post_fn)FN(0x0804f504))

void clipwin_playhead(void *ui, uint8_t *msg, uint8_t *pad, unsigned k)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (b) {
        int32_t len = fw_src_len(*(void **)(pad + PAD_SOURCE));
        int32_t real = cw_playhead(b, (unsigned)q, pad, k, *(int32_t *)(msg + MSG_POS), len);
        if (real >= 0) {
            *(int32_t *)(msg + MSG_POS) = real;
            *(uint16_t *)(msg + MSG_MILLE) = (uint16_t)(int32_t)((float)real * 1000.0f / (float)len);
        }
    }
    fw_post(ui, msg);
}
