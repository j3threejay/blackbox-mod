/* The reverb slot's Room (fx2_room.c, bank 2) and the slot itself (fx2.c, bank 1) share these. */
#ifndef FX2_H
#define FX2_H
#include <stdint.h>

#define FS 29800.0f              /* the reverb's own rate */

static inline float exp2_fast(float x)
{
    if (x < -30.0f)
        return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

/* the plate's buffers: state word index, floats */
static const struct { uint8_t word; uint16_t len; } bufs[12] = {
    {0x08, 512}, {0x0b, 512}, {0x0e, 512}, {0x11, 512}, {0x14, 1024}, {0x19, 1024},
    {0x1e, 8192}, {0x21, 8192}, {0x25, 8192}, {0x27, 8192}, {0x29, 8192}, {0x2b, 8192},
};
#define BUF(state, i) (*(float **)((uint32_t *)(state) + bufs[i].word))

struct fx2_state {
    uint32_t magic, alg;
    uint32_t er_pos;
    uint16_t in_ap_pos[4], line_pos[8];
    uint8_t line_ap_pos[8];
    float lp[8];
    uint32_t lfo[4];             /* modulation phases (32-bit wrap = one cycle) */
};
#define S ((volatile struct fx2_state *)0x38800a00u)
#define MAGIC 0x46583233u        /* "FX23": bumped with the layout */

struct room_params {
    float size, mod, early, width;
};

/* One block of Room at 29.8 kHz on the plate's own buffers: mono in, stereo out. Leaf DSP in bank 2: no calls out. */
void room(float *state, const float *in, float *outl, float *outr, int n, const struct room_params *rp);

#endif
