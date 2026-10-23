/* Transient shaper (transient.c): what the insert (insert.h / insert_dsp.c) and the Mac renders share. */
#ifndef TRANSIENT_H
#define TRANSIENT_H
#include <stdint.h>

enum { TS_DIFFER, TS_PUNCH, TS_SMOOTH, TS_MODELS };

struct ts_params {
    uint32_t model;
    float attack, sustain, speed, length, output, mix;   /* -1..1, -1..1, 0..1, 0..1, 0..1 (0.5 = 0 dB), 0..1 */
};

struct ts_state {
    float lp, ef, ea, es, gs, gp;
    int32_t hold;
    uint32_t magic;
    uint32_t model;                      /* the model the envelopes belong to (Smooth's are in power, not amplitude) */
};

/* One block, in place. r may be 0 (a mono mix). */
void ts_block(struct ts_state *s, const struct ts_params *p, float *restrict l, float *restrict r, int n);

#endif
