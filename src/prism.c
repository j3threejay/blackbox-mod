/*
 * "Prism": four-block multi-effect for the Master FX slot. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Clean-room, after the Hologram Chroma Console manual: four blocks in series, each with five effects to pick from and
 * one amount (0 = that block is out of the path), plus one extra control per block.
 *
 *   Drive    Drive (overdrive), Sweet (warm, even harmonics), Fuzz, Snarl (overdrive behind a resonance that opens with each hit),
 *            Bloom (notes fade in)                                             extra: Tilt (dark <-> bright)
 *   Motion   Doubler, Vibrato, Phaser, Tremolo, Pitch (a shifted copy)         extra: Rate (for Pitch: the interval)
 *   Space    PingPong (ping-pong repeats), Tape (tape echo), Hall (reverb), Scatter (scattered pieces),
 *            Reverse                                                          extra: Time (note length; Hall: its size)
 *   Texture  Filter (resonant low-pass), Clamp (compressor), Cassette (wow, flutter, hiss), Glitch (crushed, drops
 *            out), Static (radio band, crackle)                                extra: Mix (dry <-> all four blocks)
 *
 * Memory: one block of PRISM_BYTES that master.c gets from the firmware's own permanent allocator at boot.
 * No firmware calls in here, so host/ can compile the same file for the Mac and render audio with it.
 */
#include <stdint.h>

#include "rev4.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2: room to spare, so built for speed (3.3.l) */

#define PR_FS 48000.0f
#define PR_MAGIC 0x50525331u         /* "PRS1" */
#define SP_WET 0.7f
#ifndef DR_K
#define DR_K 0.75f
#endif
#ifndef SNARL_K
#define SNARL_K 1.0f
#endif
#ifndef SQ_MAKE
#define SQ_MAKE 0.35f
#endif

#define MV_N 4096                    /* Motion line: stereo float frames */
#define CS_N 1024                    /* Cassette line */
#define DL_N 65536                   /* Space line: stereo 16-bit frames, 1.36 s */
#define DL_GAIN 16384.0f
#define RV_FLOATS REV4_FLOATS        /* Hall's lines (rev4.c) */
#define OFF_MV 0x800
#define OFF_CS (OFF_MV + MV_N * 8)
#define OFF_RV (OFF_CS + CS_N * 8)
#define OFF_DL (OFF_RV + 0xC000)
#define PRISM_BYTES (OFF_DL + DL_N * 4)
_Static_assert(PRISM_BYTES == 0x56800, "master.c allocates this many bytes");

enum { B_DRIVE, B_MOTION, B_SPACE, B_TEX };

struct prism_params {
    uint32_t fx[4];                  /* effect of each block, 0..4 */
    float amt[4];                    /* 0..1 */
    float tilt, rate, mix;           /* 0..1 */
    uint32_t time;                   /* 0..7: 1/32 1/16 1/8T 1/8 1/8D 1/4 1/4D 1/2 */
};

struct prism {
    uint32_t magic, fx[4], on[4];
    float amt[4], tilt, mix;         /* smoothed */
    uint32_t rng;
    /* Drive */
    float dc[2][2], bp[2][2], sw_env, sw_gain;
    float tl[2];
    /* Motion */
    uint32_t mw, lfo;
    float ap[2][4], ph_last[2], shift;
    /* Space */
    uint32_t dw, wow, rev_at, rev_k, col_k[2], col_back[2];
    struct rev4 hall;
    uint32_t dl_have;                /* frames written to the Space line since it was last started (up to DL_N) */
    float dlp[2], dtime;
    /* Texture */
    float sv[2][2], sq_env, clp[2], hold[2], drop, drop_to, st_env, st_hp[2], st_lp[2], pop;
    uint32_t cw, cph1, cph2, hold_n, drop_timer;
};

_Static_assert(sizeof(struct prism) <= OFF_MV, "state must fit before the lines");

static inline float p_rnd(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return (float)(*s >> 8) * (1.0f / 16777216.0f);
}

static inline float p_soft(float x)
{
    x = x < -3.0f ? -3.0f : x > 3.0f ? 3.0f : x;
    return x * (27.0f + x * x) / (27.0f + 9.0f * x * x);
}

static inline float p_abs(float x)
{
    return x < 0.0f ? -x : x;
}

static inline float p_unit(float v)
{
    return v < 0.0f ? 0.0f : v > 1.0f ? 1.0f : v;
}

/* sin(2 pi phase / 2^32), parabola */
static inline float p_lfo(uint32_t ph)
{
    float x = (float)(int32_t)ph * (1.0f / 2147483648.0f);
    return 4.0f * x * (1.0f - p_abs(x));
}

static inline float p_log2(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xff) - 128);
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;
    return e + (-0.34484843f * v.f + 2.02466578f) * v.f - 0.67487759f;
}

static inline float p_exp2(float x)
{
    if (x < -30.0f)
        return 0.0f;
    if (x > 30.0f)
        x = 30.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

/* a fractional tap `delay` frames behind write position w in a stereo float line of n frames (n a power of two) */
static inline float p_tap(const float *line, uint32_t n, uint32_t w, float delay, int c)
{
    uint32_t di = (uint32_t)delay;
    float frac = delay - (float)di;
    float a = line[((w - di) & (n - 1)) * 2 + c], b = line[((w - di - 1) & (n - 1)) * 2 + c];
    return a + (b - a) * frac;
}

static inline float d_rd(const int16_t *dl, uint32_t at, int c)
{
    return (float)dl[(at & (DL_N - 1)) * 2 + c] * (1.0f / DL_GAIN);
}

/* `back` frames behind the write position, or silence if the line has not been written that far back since it was
   started: so starting it needs no clearing (256 KB in one audio block was a crackle waiting to happen) */
static inline float d_back(const int16_t *dl, uint32_t w, uint32_t have, uint32_t back, int c)
{
    return back > have ? 0.0f : d_rd(dl, w - back, c);
}

static inline void d_wr(int16_t *dl, uint32_t at, int c, float x)
{
    x = 2.0f * p_soft(0.5f * x) * DL_GAIN;
    dl[(at & (DL_N - 1)) * 2 + c] = (int16_t)(x > 32767.0f ? 32767.0f : x < -32767.0f ? -32767.0f : x);
}

static void p_zero(void *p, uint32_t bytes)
{
    volatile uint32_t *w = (volatile uint32_t *)p;
    for (uint32_t i = 0; i < bytes / 4; i++)
        w[i] = 0;
}

static const float time_beats[8] = {0.125f, 0.25f, 1.0f / 3.0f, 0.5f, 0.75f, 1.0f, 1.5f, 2.0f};
static const float shift_ratio[6] = {0.5f, 0.66742f, 0.74915f, 1.33484f, 1.49831f, 2.0f};   /* -12 -7 -5 +5 +7 +12 */
void prism_block(uint8_t *mem, const struct prism_params *p, float bpm, float *l, float *r, int n)
{
    struct prism *s = (struct prism *)mem;
    float *mv = (float *)(mem + OFF_MV), *cs = (float *)(mem + OFF_CS), *rv = (float *)(mem + OFF_RV);
    int16_t *dl = (int16_t *)(mem + OFF_DL);
    if (s->magic != PR_MAGIC) {
        p_zero(mem, OFF_MV);
        s->rng = 0x70726973u;
        s->mix = 1.0f;
        s->tilt = 0.5f;
        s->magic = PR_MAGIC;
    }
    /* a block that comes on, or changes its effect, starts from silence: nothing old in its line or its filters */
    for (int b = 0; b < 4; b++) {
        uint32_t fx = p->fx[b] < 5 ? p->fx[b] : 0, on = p->amt[b] > 0.0f;
        if ((on && !s->on[b]) || fx != s->fx[b]) {
            if (b == B_DRIVE) {
                p_zero(s->dc, sizeof s->dc + sizeof s->bp);
                s->sw_env = s->sw_gain = 0.0f;
            } else if (b == B_MOTION) {
                p_zero(mv, MV_N * 8);
                p_zero(s->ap, sizeof s->ap + sizeof s->ph_last);
            } else if (b == B_SPACE) {
                if (fx == 2)
                    p_zero(rv, RV_FLOATS * 4);
                s->dl_have = 0;
                p_zero(s->dlp, sizeof s->dlp);
                p_zero(&s->hall, sizeof s->hall);
                s->rev_k = s->col_k[0] = s->col_k[1] = 0;
                s->dtime = 0.0f;
            } else {
                p_zero(cs, CS_N * 8);
                p_zero(s->sv, sizeof s->sv);
                s->sq_env = s->clp[0] = s->clp[1] = s->st_env = s->pop = 0.0f;
                s->st_hp[0] = s->st_hp[1] = s->st_lp[0] = s->st_lp[1] = 0.0f;
                s->drop = s->drop_to = 1.0f;
                s->drop_timer = s->hold_n = 0;
            }
        }
        s->fx[b] = fx;
        s->on[b] = on;
        s->amt[b] += (p_unit(p->amt[b]) - s->amt[b]) * 0.25f;
        if (!on && s->amt[b] < 0.002f)
            s->amt[b] = 0.0f;
    }
    s->tilt += (p_unit(p->tilt) - s->tilt) * 0.25f;
    s->mix += (p_unit(p->mix) - s->mix) * 0.25f;

    const float a_dr = s->amt[B_DRIVE], a_mo = s->amt[B_MOTION], a_sp = s->amt[B_SPACE], a_tx = s->amt[B_TEX];
    const uint32_t f_dr = s->fx[B_DRIVE], f_mo = s->fx[B_MOTION], f_sp = s->fx[B_SPACE], f_tx = s->fx[B_TEX];
    float rate = p_unit(p->rate);

    /* Drive */
    float dr_gain = f_dr == 0 ? 1.0f + 14.0f * a_dr : f_dr == 1 ? 1.0f + 2.5f * a_dr : f_dr == 2 ? 4.0f + 80.0f * a_dr : 1.0f + 10.0f * a_dr;
    float dr_out = 1.0f / (1.0f + DR_K * (dr_gain - 1.0f) + (f_dr == 3 ? SNARL_K * (a_dr * 6.0f > 1.0f ? 1.0f : a_dr * 6.0f) : 0.0f));
    float fuzz_mix = a_dr * 6.0f > 1.0f ? 1.0f : a_dr * 6.0f;
    float sw_k = 1.0f / ((0.02f + 1.5f * a_dr) * PR_FS);
    /* Tilt: +-6 dB around 800 Hz */
    float tg = (s->tilt - 0.5f) * 2.0f, t_lo = p_exp2(-tg), t_hi = p_exp2(tg);
    int flat = tg > -0.004f && tg < 0.004f;                  /* centred: nothing is touched, bit for bit */
    /* Motion */
    uint32_t lfo_inc = (uint32_t)(0.05f * p_exp2(7.3f * rate) * (4294967296.0f / PR_FS));           /* 0.05 .. 8 Hz */
    float ratio = shift_ratio[(int)(rate * 5.99f)], shift_inc = p_abs(ratio - 1.0f) * (1.0f / 1800.0f);
    /* Space */
    if (!(bpm > 20.0f))
        bpm = 120.0f;                /* tempo not known: master.c passes 0 */
    float tf = time_beats[p->time < 8 ? p->time : 3] * 60.0f / bpm * PR_FS;
    tf = tf < 960.0f ? 960.0f : tf > 32000.0f ? 32000.0f : tf;
    uint32_t T = (uint32_t)tf;
    if (s->dtime < 1.0f)
        s->dtime = tf;
    float sp_fb = f_sp == 0 ? 0.25f + 0.45f * a_sp : f_sp == 1 ? 0.3f + 0.45f * a_sp : f_sp == 3 ? 0.5f * a_sp : 0.3f * a_sp;
    float rev_g = 0.80f + 0.02f * (float)(p->time < 8 ? p->time : 3);
    /* Texture */
    float fc = 12000.0f * p_exp2(-6.3f * a_tx), gx = 3.14159f * fc / PR_FS;
    float sv_g = gx * (1.0f + gx * gx * (0.33333f + 0.13333f * gx * gx)), sv_k = 2.0f - 1.7f * (0.3f + 0.5f * a_tx);
    float sv_a = 1.0f / (1.0f + sv_g * (sv_g + sv_k)), sv_mix = a_tx * 5.0f > 1.0f ? 1.0f : a_tx * 5.0f;
    float sq_th = -1.0f - 5.0f * a_tx, sq_make = p_exp2(-0.5f * (sq_th + 1.0f));                           /* log2 units */
    float cas_lp = 1.0f - 0.65f * a_tx, cas_hiss = a_tx * a_tx * 0.006f;
    uint32_t hold_len = 1 + (uint32_t)(a_tx * 14.0f);
    float quant = p_exp2(15.0f - 9.0f * a_tx);
    float st_hp_a = (60.0f + 300.0f * a_tx) * (6.2832f / PR_FS), st_lp_a = 1.0f - 0.7f * a_tx, st_make = 1.0f + 1.2f * a_tx;

    float *ch[2] = {l, r};
    for (int i = 0; i < n; i++) {
        float dry[2] = {l[i], r[i]}, x[2] = {l[i], r[i]};

        if (a_dr > 0.0f) {
            if (f_dr == 4) {                                 /* Bloom */
                float lev = p_abs(x[0]) > p_abs(x[1]) ? p_abs(x[0]) : p_abs(x[1]);
                s->sw_env = lev > s->sw_env ? lev : s->sw_env * 0.9998f;
                if (s->sw_env < 0.004f)
                    s->sw_gain *= 0.999f;                    /* silence: ready for the next note */
                else if (s->sw_gain < 1.0f)
                    s->sw_gain += sw_k;
                x[0] *= s->sw_gain;
                x[1] *= s->sw_gain;
            } else {
                float lev = p_abs(x[0]) > p_abs(x[1]) ? p_abs(x[0]) : p_abs(x[1]);
                s->sw_env = lev > s->sw_env ? lev : s->sw_env * 0.9995f;
                for (int c = 0; c < 2; c++) {
                    float t = x[c] * dr_gain, y;
                    if (f_dr == 0) {
                        y = p_soft(t);
                    } else if (f_dr == 1) {
                        y = p_soft(t);
                        y += 0.35f * a_dr * y * y;
                    } else if (f_dr == 2) {                  /* Fuzz: squared off, but as loud as what came in */
                        t += 0.04f;
                        y = (t > 0.5f ? 0.5f : t < -0.5f ? -0.5f : t) * 1.3f * s->sw_env;
                        y = x[c] + fuzz_mix * (y - x[c]);
                    } else {                                 /* Snarl: a resonance that opens with each hit, then the clip */
                        float f = 0.05f + 0.3f * (s->sw_env > 1.0f ? 1.0f : s->sw_env);   /* ~400 Hz .. 2.7 kHz */
                        float hi = x[c] - s->bp[c][1] - 0.25f * s->bp[c][0];
                        s->bp[c][0] += f * hi;
                        s->bp[c][1] += f * s->bp[c][0];
                        y = p_soft(t + dr_gain * 2.0f * a_dr * s->bp[c][0]);
                    }
                    s->dc[c][0] += (y - s->dc[c][0]) * 0.0013f;
                    x[c] = (y - s->dc[c][0]) * (f_dr == 2 ? 1.0f : dr_out);
                }
            }
        }

        if (a_mo > 0.0f) {
            s->lfo += lfo_inc;
            if (f_mo == 2) {                                 /* Phaser */
                for (int c = 0; c < 2; c++) {
                    float k = (300.0f * p_exp2(3.3f * (0.5f + 0.5f * p_lfo(s->lfo + (c ? 0x20000000u : 0))))) * (3.14159f / PR_FS);
                    float co = (1.0f - k) / (1.0f + k), y = x[c] + 0.55f * a_mo * s->ph_last[c];
                    for (int st = 0; st < 4; st++) {
                        float o = s->ap[c][st] - co * y;
                        s->ap[c][st] = y + co * o;
                        y = o;
                    }
                    s->ph_last[c] = y;
                    x[c] = (x[c] + a_mo * y) / (1.0f + 0.9f * a_mo);
                }
            } else if (f_mo == 3) {                          /* Tremolo */
                x[0] *= 1.0f - a_mo * 0.5f * (1.0f + p_lfo(s->lfo));
                x[1] *= 1.0f - a_mo * 0.5f * (1.0f + p_lfo(s->lfo + 0x20000000u));
            } else {
                mv[(s->mw & (MV_N - 1)) * 2] = x[0];
                mv[(s->mw & (MV_N - 1)) * 2 + 1] = x[1];
                if (f_mo == 0) {                             /* Doubler */
                    float wl = p_tap(mv, MV_N, s->mw, 576.0f + 240.0f * (1.0f + p_lfo(s->lfo)), 0);
                    float wr = p_tap(mv, MV_N, s->mw, 816.0f + 240.0f * (1.0f + p_lfo(s->lfo + 0x40000000u)), 1);
                    x[0] = (x[0] + 0.8f * a_mo * wl) / (1.0f + 0.35f * a_mo);
                    x[1] = (x[1] + 0.8f * a_mo * wr) / (1.0f + 0.35f * a_mo);
                } else if (f_mo == 1) {                      /* Vibrato */
                    float d = 8.0f + 190.0f * a_mo * (1.0f + p_lfo(s->lfo));
                    x[0] = p_tap(mv, MV_N, s->mw, d, 0);
                    x[1] = p_tap(mv, MV_N, s->mw, d, 1);
                } else {                                     /* Pitch: two taps sliding through 37 ms, cross-faded */
                    s->shift += shift_inc;
                    if (s->shift >= 1.0f)
                        s->shift -= 1.0f;
                    float ph2 = s->shift + 0.5f < 1.0f ? s->shift + 0.5f : s->shift - 0.5f;
                    float g1 = 1.0f - p_abs(2.0f * s->shift - 1.0f), g2 = 1.0f - g1;
                    float d1 = 8.0f + 1800.0f * (ratio > 1.0f ? 1.0f - s->shift : s->shift);
                    float d2 = 8.0f + 1800.0f * (ratio > 1.0f ? 1.0f - ph2 : ph2);
                    for (int c = 0; c < 2; c++) {
                        float sh = g1 * p_tap(mv, MV_N, s->mw, d1, c) + g2 * p_tap(mv, MV_N, s->mw, d2, c);
                        x[c] = x[c] * (1.0f - 0.4f * a_mo) + a_mo * sh;
                    }
                }
                s->mw++;
            }
        }

        if (a_sp > 0.0f) {
            float wet[2] = {0.0f, 0.0f};
            if (f_sp == 2) {                                 /* Hall */
                rev4_step(&s->hall, rv, 0.5f * (x[0] + x[1]), rev_g, 0.5f, wet);
                wet[0] *= 0.45f;
                wet[1] *= 0.45f;
            } else {
                float back[2] = {0.0f, 0.0f};
                if (f_sp == 0) {                             /* PingPong: each side feeds the other */
                    wet[0] = d_back(dl, s->dw, s->dl_have, T, 0);
                    wet[1] = d_back(dl, s->dw, s->dl_have, T, 1);
                    back[0] = wet[1];
                    back[1] = wet[0];
                } else if (f_sp == 1) {                      /* Tape: the time drifts, the repeats dull and saturate */
                    s->wow += (uint32_t)(0.7f * (4294967296.0f / PR_FS));
                    s->dtime += (tf - s->dtime) * 0.0002f;   /* a time change bends the pitch, like a tape machine */
                    float d = s->dtime * (1.0f + 0.004f * p_lfo(s->wow));
                    uint32_t di = (uint32_t)d;
                    float frac = d - (float)di;
                    for (int c = 0; c < 2; c++) {
                        float a0 = d_back(dl, s->dw, s->dl_have, di, c), a1 = d_back(dl, s->dw, s->dl_have, di + 1, c);
                        s->dlp[c] += (a0 + (a1 - a0) * frac - s->dlp[c]) * 0.3f;
                        wet[c] = back[c] = p_soft(s->dlp[c] * 1.1f);
                    }
                } else if (f_sp == 3) {                      /* Scatter: two overlapping pieces from random places */
                    for (int g = 0; g < 2; g++) {
                        if (!s->col_k[g]) {
                            if (g == 1 && s->col_k[0] > T / 2)
                                continue;                    /* the second piece starts half a piece after the first */
                            s->col_k[g] = T;
                            uint32_t far = T + (uint32_t)(p_rnd(&s->rng) * 3.0f * (float)T);
                            s->col_back[g] = far > DL_N - 4096 ? DL_N - 4096 : far;
                        }
                        if (!s->col_k[g])
                            continue;
                        if (s->col_k[g] > T)
                            s->col_k[g] = T;                 /* Time was turned down mid-piece */
                        uint32_t k = T - s->col_k[g], half = T / 2;
                        float env = k < half ? (float)k / (float)half : (float)(T - k) / (float)half;
                        wet[0] += env * d_back(dl, s->dw, s->dl_have, s->col_back[g], g);
                        wet[1] += env * d_back(dl, s->dw, s->dl_have, s->col_back[g], g ^ 1);
                        s->col_k[g]--;
                    }
                    back[0] = wet[0];
                    back[1] = wet[1];
                } else {                                     /* Reverse: the last piece, backwards */
                    if (s->rev_k >= T) {
                        s->rev_k = 0;
                        s->rev_at = s->dw;
                    }
                    uint32_t k = s->rev_k++, rest = T - k;
                    float env = k < 240 ? (float)k * (1.0f / 240.0f) : rest < 240 ? (float)rest * (1.0f / 240.0f) : 1.0f;
                    wet[0] = back[0] = env * d_back(dl, s->dw, s->dl_have, s->dw - s->rev_at + k, 0);
                    wet[1] = back[1] = env * d_back(dl, s->dw, s->dl_have, s->dw - s->rev_at + k, 1);
                }
                d_wr(dl, s->dw, 0, x[0] + sp_fb * back[0]);
                d_wr(dl, s->dw, 1, x[1] + sp_fb * back[1]);
                s->dw++;
                if (s->dl_have < DL_N - 1)
                    s->dl_have++;
            }
            x[0] += SP_WET * a_sp * wet[0];
            x[1] += SP_WET * a_sp * wet[1];
        }

        if (a_tx > 0.0f) {
            if (f_tx == 0) {                                 /* Filter */
                for (int c = 0; c < 2; c++) {
                    float v1 = sv_a * (s->sv[c][0] + sv_g * (x[c] - s->sv[c][1])), v2 = s->sv[c][1] + sv_g * v1;
                    s->sv[c][0] = 2.0f * v1 - s->sv[c][0];
                    s->sv[c][1] = 2.0f * v2 - s->sv[c][1];
                    x[c] += sv_mix * (v2 - x[c]);
                }
            } else if (f_tx == 1) {                          /* Clamp: 8:1, fast */
                float lev = p_abs(x[0]) > p_abs(x[1]) ? p_abs(x[0]) : p_abs(x[1]);
                s->sq_env += (lev - s->sq_env) * (lev > s->sq_env ? 0.01f : 0.00014f);
                float over = p_log2(s->sq_env + 1e-9f) - sq_th, g = sq_make * (over > 0.0f ? p_exp2(-0.875f * over) : 1.0f);
                x[0] *= g;
                x[1] *= g;
            } else if (f_tx == 2) {                          /* Cassette */
                s->cph1 += (uint32_t)(0.8f * (4294967296.0f / PR_FS));
                s->cph2 += (uint32_t)(9.0f * (4294967296.0f / PR_FS));
                float d = 4.0f + a_tx * (40.0f * (1.0f + p_lfo(s->cph1)) + 5.0f * (1.0f + p_lfo(s->cph2)));
                cs[(s->cw & (CS_N - 1)) * 2] = x[0];
                cs[(s->cw & (CS_N - 1)) * 2 + 1] = x[1];
                for (int c = 0; c < 2; c++) {
                    s->clp[c] += (p_tap(cs, CS_N, s->cw, d, c) - s->clp[c]) * cas_lp;
                    x[c] = 1.25f * p_soft(0.8f * s->clp[c]) + cas_hiss * (2.0f * p_rnd(&s->rng) - 1.0f);
                }
                s->cw++;
            } else if (f_tx == 3) {                          /* Glitch */
                if (s->drop_timer) {
                    s->drop_timer--;
                } else if (s->drop_to < 1.0f) {
                    s->drop_to = 1.0f;
                    s->drop_timer = (uint32_t)((0.15f + p_rnd(&s->rng) * 3.0f * (1.05f - a_tx)) * PR_FS);
                } else {
                    s->drop_to = 1.0f - a_tx * (0.5f + 0.5f * p_rnd(&s->rng));
                    s->drop_timer = (uint32_t)((0.02f + 0.12f * p_rnd(&s->rng)) * PR_FS);
                }
                s->drop += (s->drop_to - s->drop) * 0.004f;
                if (!s->hold_n) {
                    s->hold_n = hold_len;
                    for (int c = 0; c < 2; c++) {
                        float q = x[c] * quant;
                        s->hold[c] = (float)(int)(q + (q < 0.0f ? -0.5f : 0.5f)) / quant;
                    }
                }
                s->hold_n--;
                x[0] = s->hold[0] * s->drop;
                x[1] = s->hold[1] * s->drop;
            } else {                                         /* Static */
                float lev = p_abs(x[0]) > p_abs(x[1]) ? p_abs(x[0]) : p_abs(x[1]);
                s->st_env += (lev - s->st_env) * 0.002f;
                /* pops: rare and quiet low on the knob (at 54 % the first version fired 15 loud ones a second, which
                   he took for a fault), the full crackle only towards the top */
                if (p_rnd(&s->rng) < a_tx * a_tx * a_tx * 0.0008f)
                    s->pop = (p_rnd(&s->rng) - 0.5f) * (0.1f + 0.9f * a_tx * a_tx);
                s->pop *= 0.92f;
                float hiss = a_tx * (0.006f + 0.25f * s->st_env);
                for (int c = 0; c < 2; c++) {
                    s->st_hp[c] += (x[c] - s->st_hp[c]) * st_hp_a;
                    s->st_lp[c] += (x[c] - s->st_hp[c] - s->st_lp[c]) * st_lp_a;
                    x[c] = st_make * s->st_lp[c] + s->pop + hiss * (2.0f * p_rnd(&s->rng) - 1.0f);
                }
            }
        }

        for (int c = 0; c < 2; c++) {
            s->tl[c] += (x[c] - s->tl[c]) * 0.1f;            /* ~800 Hz */
            float y = flat ? x[c] : s->tl[c] * t_lo + (x[c] - s->tl[c]) * t_hi;
            if (s->mix < 0.999f)
                y = dry[c] + s->mix * (y - dry[c]);
            float m = p_abs(y);
            if (m > 0.8f)                                    /* the last 2 dB before full scale are rounded off */
                y = (y < 0.0f ? -1.0f : 1.0f) * (0.8f + 0.2f * p_soft((m - 0.8f) * 5.0f));
            ch[c][i] = y;
        }
    }
}
