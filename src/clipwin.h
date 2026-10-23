/*
 * Clip Window (clipwin.c): what bank 1 and bank 2 (clipwin_b2.c) share - the class-B pad's fields both read, the knob's
 * and the waveform's, and the state they keep in SDRAM. Bank 2 is compiled against this file, and the asserts at the
 * end pin every offset the cw_* functions read or write, so that moving one is a deliberate act: it makes a new bank 2
 * payload, and a unit then needs this build's BBEXTRA.BIN. Until the card loader has written it every bank 2 feature
 * (Prism, Confetti, the inserts, and all of the Clip Window) is off, because bank 1 pairs with the whole payload at
 * once, on its sum (cpu.c, b2_live). Bank 2's id does not hash this file (build.sh): an edit here that leaves bank 2's
 * bytes alone (a comment, a field appended to cw_bank, a define bank 2 does not use) needs no reflash.
 */
#ifndef CLIPWIN_H
#define CLIPWIN_H
#include <stddef.h>
#include <stdint.h>

/* class-B pad ('L', vtable 0x080d0890) */
#define PAD_CLASS   0x04             /* u8 0x4c */
#define PAD_SIBLING 0x08             /* the cell's class-H ('H') object, the next module (notes/re/x3) */
#define PAD_ID      0x18             /* u32 row << 8 | col; bank << 16 (0 for the pads) */
#define PAD_SOURCE  0x24
#define PAD_ON      0x29             /* u8 Clip or Slicer mode active */
#define PAD_RATE    0x1f0            /* f32 source rate / 48000 (no pitch term): every segment's rate (FUN_08065550) */
#define PAD_LOOP    0x1f4            /* u8 Loop Mode (0x8d) on */
#define PAD_SYNCED  0x1f5            /* u8 1: Quant and Sync are both not None (stock's, from the two) */
#define PAD_LAUNCH  0x1f8            /* u8 Launch Mode + 1: 1 Trigger, 2 Gate, 3 Toggle */
#define PAD_HARD0   0xba1            /* u8 1 = Attack (0x3c) is 0: stock starts every step 0 without a fade-in */
#define PAD_FPS     0x1fc            /* f32 source frames per step */
#define PAD_FPS_WAS 0x200            /* f32 the frames per step a Sync or Quant set re-gridded from (notes/re/a2) */
#define PAD_STEP_OUT 0x204           /* f32 output samples per step: a segment's countdown + 256 (FUN_08065550) */
#define PAD_TPS     0x208            /* i64 ticks per step */
#define PAD_STEPS   0x210            /* u32 steps n */
#define PAD_QUANT   0x218            /* i64 the launch quantum, ticks (Quant; 0 = None) */
#define PAD_SYNC    0x220            /* i64 sync step, ticks: SYNC_SLICE = Sync Slice */
#define PAD_WRAP_GRID 0x230          /* i64 the wrap's grid, ticks: min(Quant, clip) */
#define ENGINE_BPM  0x18             /* f32 the engine's (the clock's) tempo */
#define PAD_SLICES  0x250            /* u32 slice markers */
#define PAD_SLICER  0x254            /* u8 */
#define LAYER0      0x260            /* two layers (voices) of 0x410: + 0 u8 active */
#define LAYER_SIZE  0x410
#define SYNC_SLICE  0xf0000
/* class-H ('H', vtable 0x080d06c8): the Sample-mode positions, kept in Clip mode too, source frames (x3) */
#define H_CLASS     0x48
#define H_LOOP_START 0xfc
#define H_LOOP_END  0x100
#define SEG0        0x30
#define SEG_SIZE    0x70
#define SEG_POS     0x08
#define SEG_END     0x10             /* i64 the frame it stops on (the last step: its file's length - 1), 0 none */
#define SEG_FRAC    0x1c
#define SEG_DELAY   0x20
#define SEG_FADE_IN 0x24             /* i32 fade-in samples left (256 when made), then +0x28 the countdown to the fade-out */
#define FADE_IN     256              /* stock's step crossfade, in and out (0x080656ba, 0x08065700) */
#define SEG_STEP    0x34
#define SEG_FIRST   0x3c
#define SRC_BAD     0x10000000       /* fw_src_len's "the provider reported 0 frames" */
/* the knob's stepper (notes/re/a3, at knob + 0x270): + 0 i64 accumulated counts, the counts per step, the index, the
   start (the value = index + start) */
#define STEPPER_STEP  0x08
#define STEPPER_INDEX 0x0c
#define STEPPER_START 0x18
/* the waveform widget: the white bracket, i32 Loop Start and End, and whether it is shown; its dirty flag */
#define WAVE_DIRTY  0x32
#define WAVE_LOOP   0x22c
#define WAVE_LOOP_ON 0x239
/* the settings */
#define P_SYNC      0x94             /* stock's Sync: Slice, 1 bar, 1/2, 1/4, 1/8, 1/16, None (0 .. 6, unchecked) */
#define SLIP_MAX    3840             /* Slip's range, +- one bar of ticks */
#define LOOPLEN_MAX 7                /* Loop Len: Off, then 1/16 << (value - 1) up to 4 bars */
#define FIT_AUTO    1                /* Fit: Off, Auto (Bars), Auto (Beats), then 1/4, 1/2, 3 beats, 1 bar, 6 */
#define FIT_BEATS   2                /* ...beats, 2, 4 and 8 bars */
#define FIT_MAX     10
#define FIT_AUTO_MAX 1024            /* Fit Auto's most beats (an 8.5-minute loop at 120 BPM; a whole number of bars) */
#define LOOP_FADE_MAX 1000           /* stock's Loop Fade row (0xfa): 0 .. 1000 = 0 .. 100 % of the loop */

struct cw_latch {
    int32_t rs, vlen, delta;         /* the region (or the whole file) and the shift, frames */
    int32_t len;                     /* fw_src_len when latched: the file the region and the shift were made for */
};

struct cw_region {
    int32_t rs, vlen;                /* the region the pad plays this pass, frames; vlen 0 = the whole file */
};

struct cw_bank {
    uint32_t magic, scan;
    int32_t slip[16];                /* as last polled */
    uint8_t *pad[16];                /* the engine's pad object, cached by H1 */
    uint8_t valid[16];               /* bit k: latch[q][k] holds */
    struct cw_latch latch[16][4];
    uint8_t h1[16];                  /* bit k: slot k's segment was made through H1 (not a slice segment, H1') */
    uint8_t hinted[16];              /* bit k: H2 has hinted rs for slot k's crossing of the region end */
    uint32_t zero_at;                /* the Slip knob: GUI ms a turn last arrived on 0 (the detent counts from there) */
    int8_t zero_dir;                 /* ...and the direction that turn was going, */
    uint8_t zero_slow;               /* ...and 1 if it was slow (its hold is ZERO_DETENT_SLOW_MS, cw_turn) */
    uint8_t wrap;                    /* 1 + the pad whose wrap is recomputing right now (clipwin_wrap), else 0 */
    struct cw_region region[16];
    int32_t good[16][2];             /* the last loop points from the app's store that made sense (the fallback) */
    int32_t origin[16];              /* Loop Len: the window's in-point, ticks into the clip */
    uint8_t ll[16];                  /* Loop Len as taken (0 Off, else W = 240 << (ll - 1) ticks) */
    uint8_t forced[16];              /* 1: Loop Len has forced the pad's Sync; Off gives the store's back */
    int32_t sf[16][4];               /* Slip's part of latch[q][k].delta, frames (Loop Len's engage takes it out) */
    int16_t knob_counts;             /* the Slip knob's last turn event: its counts, */
    uint8_t knob_speed;              /* ...and the accelerator's speed for it (1 .. 6): a bench read */
    uint8_t llv[16];                 /* Loop Len as the poll last read it from the store, */
    uint8_t llc[16];                 /* ...and how many polls since it changed (it is taken at LL_SETTLE, cw_tick) */
    int32_t flen[16];                /* fw_src_len at the pad's last recompute (H3 site 1): the Waveform's length */
    uint8_t fit[16];                 /* Fit as taken with the region (at the pad's wrap, or stopped): 0 Off, 1 Auto
                                        (Bars), 2 Auto (Beats) */
    uint8_t pfit[16];                /* ...the one it had before (cw_hold puts it back when it holds the wrap) */
    uint8_t fon[16];                 /* 1: the pad's last recompute stored Fit's step fields (cw_fit) */
    uint16_t abeats[16];             /* Fit Auto: the beats it counted ... */
    int32_t alen[16];                /* ... for this length, frames (0: none counted) */
    float bpm[16];                   /* the tempo a fitted pad's step fields were made at */
    const uint8_t *engine;           /* the engine (the clock) as the poll last had it: cw_fit's tempo */
    uint16_t fade[16];               /* Loop Fade as taken with the region: 0 .. LOOP_FADE_MAX */
    uint8_t fin[16];                 /* bit k: slot k's segment starts inside the audio: its first read gives back the
                                        fade-in stock takes from a hard start (cw_latch, cw_slot) */
    uint8_t wrapped[16];             /* 1: pad q's wrap has just been recomputed (cw_hold): its next segment is that
                                        pass's step 0, not a launch */
    uint8_t abars[16];               /* 1: abeats is Auto (Bars)' count, 0: Auto (Beats)' (cw_fit counts again when the
                                        other Auto is chosen) */
};
#define CW_MAGIC  0x43574e42u        /* "CWNB": bumped with the layout (SDRAM keeps its contents through a reset) */
#define CW_OFFSET (0x56800u + 0x2d100u)   /* master.c: PRISM_BYTES + 0x2d100, where this bank begins */
#define CW_BYTES  0x1000u            /* what master.c's EXTRA_BYTES gives the bank */
_Static_assert(sizeof(struct cw_bank) <= CW_BYTES, "master.c's EXTRA_BYTES gives the bank CW_BYTES");
_Static_assert(CW_OFFSET == 0x56800u + 0x2d100u, "master.c: PRISM_BYTES + 0x2d100, cleared in master_alloc");
_Static_assert(offsetof(struct cw_bank, zero_at) == 0x4b8 && offsetof(struct cw_bank, zero_dir) == 0x4bc &&
               offsetof(struct cw_bank, zero_slow) == 0x4bd &&
               offsetof(struct cw_bank, knob_counts) == 0x720 && offsetof(struct cw_bank, knob_speed) == 0x722 &&
               offsetof(struct cw_bank, fit) == 0x784 && offsetof(struct cw_bank, fon) == 0x7a4 &&
               offsetof(struct cw_bank, abeats) == 0x7b4 && offsetof(struct cw_bank, alen) == 0x7d4 &&
               offsetof(struct cw_bank, bpm) == 0x814 && offsetof(struct cw_bank, fin) == 0x878 &&
               offsetof(struct cw_bank, wrapped) == 0x888 && offsetof(struct cw_bank, abars) == 0x898 &&
               sizeof(struct cw_bank) == 0x8a8,
               "test_clipwin.py reads the knob's and Fit's fields here");

/*
 * clipwin_b2.c, in bank 2: the maths and the policy of every hook. Call only when b2_live() holds (clipwin.c's
 * bank() asks it); each is leaf code, and clipwin.c makes every stock call they need.
 */
int cw_pad(const uint8_t *pad);      /* 0 .. 15 for one of the sixteen pads, else -1 */
/* H3: the length stock is told at site 0 .. 3 (at site 3, a fitted pad's step fields stored again: cw_fit); set = the
   pad's store rows below, read for site 1 only */
#define CW_SET_REGION 0
#define CW_SET_START  1
#define CW_SET_END    2
#define CW_SET_FIT    3
#define CW_SET_FADE   4
#define CW_SET_ROWS   5
int32_t cw_len(struct cw_bank *b, unsigned q, uint8_t *pad, int site, int32_t clip, int32_t len, const int32_t *set);
/* ...cw_len's at site 3: a fitted pad's step fields over len (its region or its file); 1 = stored, 0 = not fitted */
int cw_fit(struct cw_bank *b, unsigned q, uint8_t *pad, int32_t len);
/* H3': after the wrap's recompute, 1 = the region before it (was: rs, vlen, then the wrap grid and the clip, ticks, the
   pad had) is back and the pad must recompute again */
#define CW_WAS_GRID 2
#define CW_WAS_CLIP 3
int cw_hold(struct cw_bank *b, unsigned q, const uint8_t *pad, const uint32_t *t, const int32_t *was);
/* H1: latch slot k, return where to prefetch (pos < 0: from the segment's own start); H1': a slice segment in slot k */
int32_t cw_latch(struct cw_bank *b, unsigned q, unsigned k, uint8_t *pad, int32_t len, int32_t pos);
void cw_slice(struct cw_bank *b, unsigned q, unsigned k);
/* H2: the latch of the segment whose fraction is at frac (0: none, read as stock); at[0] = its real position for pos,
   at[1] = Loop Fade's frames before the region's end (0 none); 1 = hint now: rs, and rs - fade (the read takes fade);
   Loop Fade's crossfade over a read's window */
const struct cw_latch *cw_slot(struct cw_bank *b, unsigned q, const uint8_t *pad, float *frac);
void cw_map(const struct cw_bank *b, unsigned q, const uint8_t *pad, const struct cw_latch *l, int32_t pos,
            int32_t *at);
int cw_hint(struct cw_bank *b, unsigned q, const struct cw_latch *l, int32_t real, int32_t fade);
/* H5: the frame slot k of pad q really reads at stock's position pos (cw_map's), for the playhead; -1 = stock's */
int32_t cw_playhead(const struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned k, int32_t pos, int32_t len);
void cw_fade(float *l, float *r, int count, int32_t i0, int32_t fade);
/* the poll: bit 0 = drop and remake the pending segments (cw_drop: the slots to latch again), bit 1 = send msg, bit 2 =
   the cached pad is pad q's (cw_retire may look at its segments, len = fw_src_len of its source), bit 3 = recompute it
   (Fit: its step fields were made at another tempo) */
int cw_tick(struct cw_bank *b, unsigned q, int32_t slip, unsigned ll, uint32_t sync, const void *engine, uint32_t *msg);
unsigned cw_drop(const struct cw_bank *b, unsigned q, uint8_t *pad);
void cw_retire(uint8_t *pad, int32_t len);
/* Loop Len's take (from cw_tick) and its window (from cw_latch) */
int cw_looplen(struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned ll, uint32_t sync, uint32_t *msg);
int32_t cw_window(const struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned k, int32_t clip);
/* the Slip knob: 0 = no move, else *add for the stepper; its text (at most 13 bytes); the Waveform's bracket */
int cw_turn(struct cw_bank *b, const uint8_t *stepper, int counts, unsigned m, uint32_t now, int32_t *add);
void cw_text(char *t, int v);
int32_t cw_bracket(uint8_t *wave, int mode, int32_t ls, int32_t le, int32_t len, int was);

/* what the cw_* functions are compiled against (no code: the compiler checks them). Changing one reprograms bank 2. */
_Static_assert(offsetof(struct cw_bank, slip) == 0x8 && offsetof(struct cw_bank, pad) == 0x48 &&
               offsetof(struct cw_bank, valid) == 0x88 && offsetof(struct cw_bank, latch) == 0x98 &&
               sizeof(struct cw_latch) == 16 && offsetof(struct cw_latch, vlen) == 4 &&
               offsetof(struct cw_latch, delta) == 8 && offsetof(struct cw_latch, len) == 12 &&
               offsetof(struct cw_bank, h1) == 0x498 && offsetof(struct cw_bank, hinted) == 0x4a8 &&
               offsetof(struct cw_bank, wrap) == 0x4be && offsetof(struct cw_bank, region) == 0x4c0 &&
               sizeof(struct cw_region) == 8 && offsetof(struct cw_bank, good) == 0x540 &&
               offsetof(struct cw_bank, origin) == 0x5c0 && offsetof(struct cw_bank, ll) == 0x600 &&
               offsetof(struct cw_bank, forced) == 0x610 && offsetof(struct cw_bank, sf) == 0x620 &&
               offsetof(struct cw_bank, llv) == 0x723 && offsetof(struct cw_bank, llc) == 0x733 &&
               offsetof(struct cw_bank, flen) == 0x744 && offsetof(struct cw_bank, pfit) == 0x794 &&
               offsetof(struct cw_bank, engine) == 0x854 && offsetof(struct cw_bank, fade) == 0x858,
               "bank 2 (the cw_* functions) is compiled against these cw_bank offsets: moving one reprograms bank 2");
_Static_assert(SEG0 == 0x30 && SEG_SIZE == 0x70 && SEG_POS == 0x08 && SEG_FRAC == 0x1c && SEG_DELAY == 0x20 &&
               SEG_FADE_IN == 0x24 && FADE_IN == 256 &&
               SEG_STEP == 0x34 && SEG_FIRST == 0x3c && SEG_END == 0x10 && PAD_FPS == 0x1fc && PAD_TPS == 0x208 &&
               PAD_STEPS == 0x210 && PAD_RATE == 0x1f0 && PAD_QUANT == 0x218 && ENGINE_BPM == 0x18 &&
               PAD_SYNC == 0x220 && PAD_CLASS == 0x04 && PAD_SIBLING == 0x08 && PAD_ID == 0x18 && PAD_ON == 0x29 &&
               PAD_LOOP == 0x1f4 && PAD_SYNCED == 0x1f5 && PAD_LAUNCH == 0x1f8 && PAD_STEP_OUT == 0x204 &&
               PAD_HARD0 == 0xba1 &&
               PAD_WRAP_GRID == 0x230 && PAD_SLICES == 0x250 && PAD_SLICER == 0x254 && LAYER0 == 0x260 &&
               LAYER_SIZE == 0x410 &&
               H_CLASS == 0x48 && H_LOOP_START == 0xfc && H_LOOP_END == 0x100 &&
               offsetof(struct cw_region, vlen) == 4,
               "bank 2 (the cw_* functions) is compiled against these pad, class-H and segment offsets: changing one "
               "reprograms bank 2");
_Static_assert(STEPPER_STEP == 0x08 && STEPPER_INDEX == 0x0c && STEPPER_START == 0x18 && WAVE_DIRTY == 0x32 &&
               WAVE_LOOP == 0x22c && WAVE_LOOP_ON == 0x239 && P_SYNC == 0x94 && SLIP_MAX == 3840 && LOOPLEN_MAX == 7 &&
               SRC_BAD == 0x10000000 && SYNC_SLICE == 0xf0000 && CW_SET_REGION == 0 && CW_SET_START == 1 &&
               CW_SET_END == 2 && CW_SET_FIT == 3 && CW_SET_FADE == 4 && CW_SET_ROWS == 5 && CW_WAS_GRID == 2 &&
               CW_WAS_CLIP == 3 && FIT_AUTO == 1 && FIT_BEATS == 2 && FIT_MAX == 10 &&
               FIT_AUTO_MAX == 1024 && LOOP_FADE_MAX == 1000,
               "bank 2 (cw_turn, cw_bracket, cw_tick, cw_looplen, cw_len, cw_latch, cw_hold) is compiled against the "
               "knob's and the waveform's fields, these settings and values, clipwin_len's row order and "
               "clipwin_wrap's: changing one reprograms bank 2");

#endif
