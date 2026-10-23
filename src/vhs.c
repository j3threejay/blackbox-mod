/*
 * VHS, Master FX type 1: the DSP (master.c has the settings, the list and the glue). Moved here from master.c in 3.3.y
 * so it lives in flash bank 2 (build.sh BANK2_SRCS): bank 1 was down to ~1.8 KB. Leaf DSP, no calls out of bank 2;
 * master.c only calls it when bank 2 is live (the backup SRAM clock is on by then), and passes through without it.
 *
 * Clean-room, after the Chase Bliss Generation Loss manual: a worn tape / VHS machine.
 *   Saturate -> short modulated delay (Wow slow + deep, Flutter fast + shallow) -> Dropout (random level dropouts, one
 *   or both channels) -> Hi Cut (12 dB) -> Lo Cut (6 dB) -> + Noise (hiss).
 * The delay line is 256 stereo 16-bit frames in the backup SRAM, so the wet path is 16-bit with 6 dB of headroom.
 */
#include <stdint.h>
#include "vhs.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2: built for speed (3.3.y: -5 % instructions measured) */

#define FS        48000.0f
#define LINE      256                    /* frames, power of two */
#define LINE_GAIN 16384.0f               /* 16-bit store with 6 dB of headroom */
#define WOW_MAX   100.0f                 /* frames of swing each way (2.1 ms) */
#define FLUT_MAX  14.0f                  /* 0.29 ms */
#define BASE_DLY  2.0f

struct gl_state {
    uint32_t magic;
    uint32_t wpos, ph_wow, ph_flut, rng, timer;
    float dw, df;                        /* smoothed swing depths, frames */
    float lp1[2], lp2[2], hp[2];
    float g[2], gt[2];                   /* dropout gain and its target, per channel */
};
#define GL   ((volatile struct gl_state *)0x38800f20u)
#define GLBUF ((int16_t *)0x38800b20u)   /* LINE x 2 int16 = 0x400 bytes, up to 0x38800f20 */
#define MAGIC VHS_MAGIC                  /* "GL01" */

static inline float exp2_fast(float x)
{
    if (x < -30.0f)
        return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v;
    v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}

/* sin(2 pi phase / 2^32), parabola */
static inline float lfo(uint32_t ph)
{
    float x = (float)(int32_t)ph * (1.0f / 2147483648.0f);
    return 4.0f * x * (1.0f - (x < 0.0f ? -x : x));
}

static inline float softclip(float x)
{
    x = x < -3.0f ? -3.0f : x > 3.0f ? 3.0f : x;
    return x * (27.0f + x * x) / (27.0f + 9.0f * x * x);
}

static inline float rnd(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return (float)(*s >> 8) * (1.0f / 16777216.0f);
}

void vhs_block(const struct vhs_params *p, float *l, float *r, int n)
{
    if (GL->magic != MAGIC) {
        for (int i = 0; i < LINE * 2; i++)
            GLBUF[i] = 0;
        for (unsigned i = 0; i < sizeof(struct gl_state) / 4; i++)
            ((volatile uint32_t *)GL)[i] = 0;
        GL->rng = 0x2545f491u;
        GL->g[0] = GL->g[1] = GL->gt[0] = GL->gt[1] = 1.0f;
        GL->magic = MAGIC;
    }
    float wow = p->wow, flut = p->flut, sat = p->sat, fail = p->fail, noise = p->noise;
    float hicut = p->hicut, locut = p->locut;

    float drive = 1.0f + 3.0f * sat, makeup = exp2_fast(-0.5f * 1.5850f * sat * (2.0f - sat));   /* ~1 / sqrt(drive) */
    float sat_mix = sat * 4.0f > 1.0f ? 1.0f : sat * 4.0f;
    float dw_t = wow * WOW_MAX, df_t = flut * FLUT_MAX;
    uint32_t inc_wow = (uint32_t)((0.4f + 1.6f * wow) * (4294967296.0f / FS));
    uint32_t inc_flut = (uint32_t)((6.0f + 8.0f * flut) * (4294967296.0f / FS));
    /* one-pole coefficients: 20 kHz .. 1 kHz, 20 Hz .. 800 Hz */
    float lp_a = 1.0f - exp2_fast(-1.4427f * 6.2832f * 20000.0f * exp2_fast(-4.32f * hicut) / FS);
    float hp_a = 1.0f - exp2_fast(-1.4427f * 6.2832f * 20.0f * exp2_fast(5.32f * locut) / FS);
    float hiss = noise * noise * 0.02f;

    struct gl_state s;                                       /* word copies: no memcpy in the cave */
    for (unsigned i = 0; i < sizeof s / 4; i++)
        ((volatile uint32_t *)&s)[i] = ((volatile uint32_t *)GL)[i];
    float *ch[2] = {l, r};
    for (int i = 0; i < n; i++) {
        s.dw += (dw_t - s.dw) * 0.0002f;
        s.df += (df_t - s.df) * 0.0002f;
        s.ph_wow += inc_wow;
        s.ph_flut += inc_flut;
        float d = BASE_DLY + s.dw * (1.0f + lfo(s.ph_wow)) + s.df * (1.0f + lfo(s.ph_flut));
        int di = (int)d;
        float frac = d - (float)di;

        if (fail <= 0.0f) {
            s.gt[0] = s.gt[1] = 1.0f;
            s.timer = 0;
        } else if (s.timer) {
            s.timer--;
        } else if (s.gt[0] < 1.0f || s.gt[1] < 1.0f) {       /* a dropout ends; wait for the next */
            s.gt[0] = s.gt[1] = 1.0f;
            s.timer = (uint32_t)((0.1f + rnd(&s.rng) * (0.15f + 4.0f * (1.0f - fail))) * FS);
        } else {                                             /* a dropout starts: 20 .. 220 ms */
            float depth = 1.0f - fail * (0.4f + 0.6f * rnd(&s.rng)), side = rnd(&s.rng);
            s.gt[0] = side < 0.25f ? 1.0f : depth;
            s.gt[1] = side >= 0.25f && side < 0.5f ? 1.0f : depth;
            s.timer = (uint32_t)((0.02f + 0.2f * rnd(&s.rng)) * FS);
        }

        for (int c = 0; c < 2; c++) {
            float x = ch[c][i];
            x = (x + sat_mix * (softclip(x * drive) * makeup - x)) * LINE_GAIN;   /* Saturate 0 = clean */
            x = x > 32767.0f ? 32767.0f : x < -32767.0f ? -32767.0f : x;
            GLBUF[(s.wpos & (LINE - 1)) * 2 + c] = (int16_t)x;
            float a = (float)GLBUF[((s.wpos - (uint32_t)di) & (LINE - 1)) * 2 + c];
            float b = (float)GLBUF[((s.wpos - (uint32_t)di - 1) & (LINE - 1)) * 2 + c];
            float y = (a + (b - a) * frac) * (1.0f / LINE_GAIN);
            s.g[c] += (s.gt[c] - s.g[c]) * 0.003f;
            y *= s.g[c];
            if (hicut > 0.0f) {
                s.lp1[c] += (y - s.lp1[c]) * lp_a;
                s.lp2[c] += (s.lp1[c] - s.lp2[c]) * lp_a;
                y = s.lp2[c];
            }
            if (locut > 0.0f) {
                s.hp[c] += (y - s.hp[c]) * hp_a;
                y -= s.hp[c];
            }
            ch[c][i] = y + hiss * (2.0f * rnd(&s.rng) - 1.0f);
        }
        s.wpos++;
    }
    for (unsigned i = 0; i < sizeof s / 4; i++)
        ((volatile uint32_t *)GL)[i] = ((volatile uint32_t *)&s)[i];
}
