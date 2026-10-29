/* ChopShop's whole-file attack scan (chop_dsp.c, bank 2; also built for the Mac) and what chop.c (bank 1) places from it. */
#ifndef CHOP_H
#define CHOP_H
#include <stdint.h>

/* The whole-file attack scan (chop_dsp.c, bank 2, a few thousand frames an audio block; asked 10-27: "transients to land
   square", stock's own transient Scan was "night and day" next to beat-grid chops). Every 128 frames: the energy of
   the second difference (the top end, where a hit stands out of a full mix: against librosa's onsets on 8 test files
   it found the hits on top of held sounds that the first difference missed, F1 0.84 -> 0.91, host/chop_check.py).
   A hit = where the next ON_R blocks hold at least ON_RISE x the energy of the ON_R before, and that rise is the
   largest within +-ON_P blocks; placed on the 32-frame hop in that rise with the sharpest jump, 16 frames ahead of it. The ON_MAX
   strongest are kept (position, rise, level). The level is the plain energy after it (how loud it looks on the
   waveform): the second difference makes a click in a gap look as big as a snare. */
#define ON_H        128          /* frames a block */
#define ON_SUB      32           /* frames a sub-hop (placement) */
#define ON_R        8            /* blocks each side of the rise (~21 ms) */
#define ON_P        12           /* a hit is the largest rise within +-ON_P blocks (~32 ms) */
#define ON_RISE     3.0f
#define ON_RING     64           /* power of two, > 2 (ON_P + ON_R) + 2 */
#define ON_MAX      1024
#define ON_CHUNK    2048         /* frames a fetch */
#define ON_PER      1            /* fetches an audio block (2048 frames: 16x real time, a 2-minute file in ~7.5 s) */

enum { CHOP_IDLE, CHOP_SCAN, CHOP_DONE, CHOP_FAILED };

struct chop_job {
    uint32_t state;
    int32_t pad;                 /* app pad index 0..15 */
    void *obj;                   /* the sample */
    int32_t len;                 /* frames to scan (chop.c may raise it and set CHOP_SCAN again: the scan goes on) */
    int stereo;
    int n;                       /* hits kept (<= ON_MAX), in no order once full (the weakest is replaced) */
    int32_t next, blocks;        /* the next frame to read; blocks measured so far (hits are found ON_R + ON_P
                                    blocks behind: the last ~2.6k frames read are not judged yet) */
    uint32_t misses;
    int (*fetch)(struct chop_job *j, float *l, float *r, int n, int32_t pos);   /* 0 = not loaded yet: again next block */
    float pl, pr, dl, dr;        /* the last frame read and its first difference (they run across fetches) */
    float e[ON_RING];            /* block energies (second difference) */
    float pe[ON_RING];           /* block energies (plain) */
    float sub[ON_RING * (ON_H / ON_SUB)];   /* sub-hop energies */
    float rise[ON_RING];         /* rise of the block that starts there */
    float acc, pacc;             /* the block being summed (second difference, plain) */
    int32_t at[ON_MAX];          /* the hits: frame */
    float score[ON_MAX];         /* rise (after / before) */
    float level[ON_MAX];         /* mean plain block energy over the ON_R blocks from the hit */
};

/* chop.c: one chop operation in flight (GUI task) */
enum { CHOP_OP_NONE, CHOP_OP_BEATS, CHOP_OP_FIND, CHOP_OP_RANDOM };
enum { CHOP_PH_IDLE, CHOP_PH_TEMPO, CHOP_PH_SCAN };
#define CHOP_ANY_PAD (-2)          /* chop_roll_text: the run's own pad */
const char *chop_roll_text(int q, char *buf);   /* chop.c: the Roll row's cue text (buf >= 16) */
struct chop_run {
    uint8_t op, phase, pad, unit;  /* unit (Beats): 0 1/4, 1 1/2, 2 beat, 3 2 beats, 4 bar */
    uint8_t fail, spare[3];        /* last result: 0 ok, 1 no tempo, 2 no audio / scan failed; spare = the Roll cue
                                      (chop.c CUE_*: dice frames, result frames, chops placed) */
    uint32_t seed, frames;         /* the re-roll seed; GUI frames waited (gives up at ~30 s) */
    float fpb, anchor;             /* the tempo the last chop used (re-rolls skip the detector) */
    int32_t want;                  /* chops for Find / Random */
    int32_t pos[128];              /* the points being placed (SDRAM, not the GUI task's stack) */
    int32_t seen;                  /* the scan's next frame when last polled (progress resets the wait) */
};

void chop_scan_start(struct chop_job *j, int pad, void *obj, int32_t len, int stereo);
int chop_scan_step(struct chop_job *j, float *scratch);   /* scratch: 2 x ON_CHUNK floats */
int chop_fw_fetch(struct chop_job *j, float *l, float *r, int n, int32_t pos);   /* firmware only */

#endif
