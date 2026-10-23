/* Per-pad insert effects: what insert.c (firmware glue) and insert_dsp.c (the effects; also built for the Mac) share. */
#ifndef INSERT_H
#define INSERT_H
#include <stdint.h>

#include "transient.h"

enum { INS_OFF, INS_PHASER, INS_FLANGER, INS_GATE, INS_TRANS, INS_TYPES };
enum { PH_PEBBLE, PH_NINETY, PH_VIBE, PH_DEEP, PH_STEPS, PH_MODELS };
enum { FL_ELECTRA, FL_JET, FL_TAPE, FL_METAL, FL_MODELS };

#define INS_LINE   1024          /* frames of delay line per channel (21 ms), a power of two */
#define INS_STAGES 12

/*
 * The pad's settings, every knob 0..1. The six are shared by Phaser and Flanger; the Gate has its own five
 * (it listens to the pad's own signal and uses no delay line at all, so it costs no SDRAM - see NOTES.md on the
 * 2026-10-09 dropouts), and borrows Mix from the shared set because that one means the same thing either way.
 */
enum { IN_OFF, IN_LEFT, IN_RIGHT, IN_STEREO, IN_SOURCES };

struct ins_set {
    uint8_t type, model, input, _r;
    float rate, depth, manual, fb, spread, mix;
    float thresh, attack, hold, release, floor;
    struct ts_params ts;                     /* Transient (transient.c): its own seven settings */
};

struct ins_state {
    uint8_t type, model, primed, _r;
    uint32_t phase, rng, w;
    float depth, manual, fb, mix;            /* the knobs, smoothed once a block */
    float lamp[2];                           /* Vibe: the bulb's brightness, which lags the oscillator */
    float env, gain;                         /* Gate: the follower, and where the gain has got to */
    float hold_left;                         /* Gate: milliseconds of hold still owed */
    uint8_t open, _r2[3];                    /* Gate: whether it is letting sound through */
    float held[2], glide[2];                 /* Steps: this step's value and where the sweep has got to */
    float cur[2][4];                         /* per channel: the all-pass coefficient(s), or the delay in frames */
    float ap[2][INS_STAGES];
    float loop[2];                           /* what feeds back */
    float tone[2];                           /* the wet path's low-pass */
    struct ts_state ts;                      /* Transient: its followers and gain */
    float line[2][INS_LINE];
};

/* One block, in place. r may be 0 (a mono mix). */
void ins_render(struct ins_state *s, const struct ins_set *p, float *l, float *r, int n);
int b2_live(void);               /* cpu.c: is flash bank 2, where ins_render lives, the matching payload */

#endif
