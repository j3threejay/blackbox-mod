/* ChopShop's whole-file beat scan (chop_dsp.c, bank 2; also built for the Mac) and what chop.c (bank 1) picks from it. */
#ifndef CHOP_H
#define CHOP_H
#include <stdint.h>

#define CHOP_BEATS  1024         /* beats scanned at most (~10 min at 100 BPM) */
#define CHOP_WIN    1024         /* frames read around each beat: 512 before (the "before" level), 512 after */
#define CHOP_PER    4            /* beats scanned per audio block */

enum { CHOP_IDLE, CHOP_SCAN, CHOP_DONE, CHOP_FAILED };

struct chop_job {
    uint32_t state;
    int32_t pad;                 /* app pad index 0..15 */
    void *obj;                   /* the sample */
    int32_t len;                 /* frames */
    int stereo;
    float anchor, fpb;           /* the beat grid: beat one (frames), frames per beat */
    int n, idx;                  /* beats on the grid (<= CHOP_BEATS), the next to scan */
    uint32_t misses;
    int (*fetch)(struct chop_job *j, float *l, float *r, int n, int32_t pos);   /* 0 = not loaded yet: again next block */
    float level[CHOP_BEATS];     /* RMS of the 512 frames from the beat on */
    float hit[CHOP_BEATS];       /* how much louder than the 512 frames before it (0 if not) */
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
};

void chop_scan_start(struct chop_job *j, int pad, void *obj, int32_t len, int stereo, float anchor, float fpb);
int chop_scan_step(struct chop_job *j, float *scratch);   /* scratch: 2 x CHOP_WIN floats */
int chop_fw_fetch(struct chop_job *j, float *l, float *r, int n, int32_t pos);   /* firmware only */

#endif
