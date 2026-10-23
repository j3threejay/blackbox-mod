/*
 * Transient shaper for the per-pad insert. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Clean-room, from research/TRANSIENT_SHAPERS.md (the differential-envelope technique as SPL documents it for its
 * Transient Designer, and Sonnox's "ratio" law): a fast envelope and a slow one, compared as a RATIO in log2, so the
 * shaping does not depend on how loud the pad is and needs no threshold.
 *   Ef  the fast envelope: peak of a high-passed L+R sidechain, held, then released
 *   Ea  Ef through a slow rise (falls with Ef at once): Ef / Ea > 1 only while a hit is starting
 *   Es  Ef with a slow release (rises with Ef at once): Es / Ef > 1 only while a hit is dying away
 *   gain (log2) = attack x log2(Ef / Ea) + sustain x log2(Es / Ef), clamped to -24 .. +15 dB, smoothed
 * One detector for both channels. It runs once per 4 frames on the peak of those 4, and the gain is ramped across
 * them (the research's host sim: within 0.2 dB of running it every sample, at about half the cost).
 *
 * Models (one row of constants each; names are ours):
 *   Differ  even-handed attack and sustain (the research's default)
 *   Punch   a shorter, harder bump that hits the click more than the body (faster rise, short hold, 300 Hz sidechain)
 *   Smooth  a mean-square detector: softer, slower attack change, less wobble on bass and sustained synths
 * Knobs: Attack -1..+1, Sustain -1..+1, Speed 0..1 (the rise: 30 .. 1.5 ms), Length 0..1 (the sustain release:
 * 50 ms .. 2 s), Output 0..1 (-12 .. +12 dB, 0.5 = 0 dB), Mix 0..1 (parallel: 1 = all shaped).
 * Attack and Sustain both 0: the block is left alone apart from Output (zero cost at 0 dB).
 *
 * No firmware calls and no libm: host/render_transient.py compiles this same file for the Mac.
 * CPU (research estimate, static count of the prototype): ~54 instructions per stereo frame = ~0.65 % at 400 MHz;
 * measure with the emulator and the CPU_PROF build once it is in the insert.
 */
#include "transient.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define TS_FS     48000.0f
#define TS_GROUP  4                      /* the detector's step, in frames */
#define TS_EPS    0.001f                 /* the envelope floor, -60 dB of the sidechain: noise is left alone */
#define TS_CEIL   4.0f                   /* +12 dBFS: a safety ceiling only (the master clipper is downstream) */

#define TS_MAGIC 0x54535431u             /* "TST1" */

/* 2^x and log2(x) by the float's bits: ~0.3 % and ~0.005 (0.03 dB) - plenty for a gain */
static inline float ts_exp2(float x)
{
    if (x < -30.0f)
        x = -30.0f;
    if (x > 30.0f)
        x = 30.0f;
    int i = (int)(x < 0.0f ? x - 1.0f : x);
    float f = x - (float)i;
    float p = 1.0f + f * (0.6951786f + f * (0.2261961f + f * 0.0786253f));
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

static inline float ts_log2(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)(int)((v.u >> 23) & 0xff) - 128.0f;
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;      /* mantissa in [1, 2) */
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;   /* e = exponent - 128: the quadratic adds ~1 */
}

/* one-pole coefficient: the part of the way a follower moves per step of `per` seconds, for time constant tau */
static inline float ts_k(float tau, float per)
{
    return 1.0f - ts_exp2(-1.44269504f * per / tau);
}

void ts_block(struct ts_state *s, const struct ts_params *p, float *restrict l, float *restrict r, int n)
{
    if (!s || !p || !l || n <= 0)
        return;
    const unsigned model = p->model < TS_MODELS ? p->model : TS_DIFFER;
    const float floor = model == TS_SMOOTH ? TS_EPS * TS_EPS : TS_EPS;  /* Smooth's detector is a mean square */
    if (s->magic != TS_MAGIC || s->model != model) {    /* fresh, or another model: its envelopes from rest */
        s->lp = 0.0f;
        s->ef = s->ea = s->es = floor;
        s->gs = 0.0f;
        if (s->magic != TS_MAGIC)
            s->gp = 1.0f;
        s->hold = 0;
        s->model = model;
        s->magic = TS_MAGIC;
    }
    float out = ts_exp2((p->output - 0.5f) * 4.0f);                    /* -12 .. +12 dB */
    const float att = p->attack, sus = p->sustain, mix = p->mix;
    if (att == 0.0f && sus == 0.0f) {
        if (out != 1.0f)
            for (int i = 0; i < n; i++) {
                l[i] *= out;
                if (r)
                    r[i] *= out;
            }
        return;
    }
    /* the model's constants (seconds, Hz) */
    float hp_hz = 120.0f, hold_s = 0.010f, rel_s = 0.040f, rise_mul = 1.0f, smooth_s = 0.0005f, att_mul = 1.2f;
    if (model == TS_PUNCH) {
        hp_hz = 300.0f; hold_s = 0.003f; rel_s = 0.015f; rise_mul = 0.35f; att_mul = 1.8f;
    } else if (model == TS_SMOOTH) {
        hold_s = 0.0f; rise_mul = 2.0f; smooth_s = 0.002f;
    }
    const float per = (float)TS_GROUP / TS_FS;
    const float tau_a = 0.030f * ts_exp2(-4.3f * p->speed) * rise_mul;  /* 30 .. 1.5 ms (x the model) */
    const float tau_s = 0.050f * ts_exp2(5.3f * p->length);             /* 50 ms .. 2 s */
    const float hp_c = 1.0f - ts_exp2(-1.44269504f * 6.2831853f * hp_hz / TS_FS);
    const float rf = 1.0f - ts_k(rel_s, per), ka = ts_k(tau_a, per), rs = 1.0f - ts_k(tau_s, per);
    const float kg = ts_k(smooth_s, per), ms_k = ts_k(0.003f, 1.0f / TS_FS);
    const int32_t hold_n = (int32_t)(hold_s / per);
    const float ga = att * att_mul, gsus = sus;
    const float lscale = model == TS_SMOOTH ? 0.5f : 1.0f;              /* mean square: half the log */
    float lp = s->lp, ef = s->ef, ea = s->ea, es = s->es, gs = s->gs, gp = s->gp;
    int32_t hold = s->hold;
    int i = 0;
    for (; i + TS_GROUP <= n; i += TS_GROUP) {
        float pk = 0.0f;
        for (int j = 0; j < TS_GROUP; j++) {
            float m = r ? l[i + j] + r[i + j] : 2.0f * l[i + j];
            lp += hp_c * (m - lp);
            float h = m - lp;
            if (model == TS_SMOOTH) {
                ef += ms_k * (h * h - ef);
                pk = ef;
            } else
                pk = __builtin_fmaxf(pk, __builtin_fabsf(h));
        }
        if (model == TS_SMOOTH)
            ef = __builtin_fmaxf(pk, floor);
        else if (pk > ef) {
            ef = pk;
            hold = hold_n;
        } else if (hold > 0)
            hold--;
        else
            ef = __builtin_fmaxf(ef * rf, floor);
        ea = ef > ea ? ea + ka * (ef - ea) : ef;
        es = __builtin_fmaxf(es * rs, ef);
        float lf = ts_log2(ef);
        float g2 = lscale * (ga * (lf - ts_log2(ea)) + gsus * (ts_log2(es) - lf));
        g2 = __builtin_fminf(__builtin_fmaxf(g2, -4.0f), 2.5f);       /* -24 .. +15 dB */
        gs += kg * (g2 - gs);
        float g = ts_exp2(gs);
        g = (1.0f + mix * (g - 1.0f)) * out;
        float dg = (g - gp) * (1.0f / TS_GROUP);
        for (int j = 0; j < TS_GROUP; j++) {
            gp += dg;
            l[i + j] = __builtin_fminf(__builtin_fmaxf(l[i + j] * gp, -TS_CEIL), TS_CEIL);
            if (r)
                r[i + j] = __builtin_fminf(__builtin_fmaxf(r[i + j] * gp, -TS_CEIL), TS_CEIL);
        }
        gp = g;
    }
    for (; i < n; i++) {                 /* a block that is not a multiple of 4: the tail at the last gain */
        l[i] *= gp;
        if (r)
            r[i] *= gp;
    }
    s->lp = lp; s->ef = ef; s->ea = ea; s->es = es; s->gs = gs; s->gp = gp; s->hold = hold;
}
