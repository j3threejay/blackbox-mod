/*
 * The five compressor models' DSP: Glue, Punch, Opto, Squash, Limit (comp.c has the list and the glue).
 * Moved here from comp.c in 3.3.y so it lives in flash bank 2 (build.sh BANK2_SRCS): bank 1 was down to ~1.8 KB.
 * Leaf DSP, no calls out of bank 2. comp_process (bank 1) only calls it when bank 2 is live; without it a model runs
 * as Stock.
 */
#include <stdint.h>

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")   /* O2 measured +5 % instructions here (3.3.y) */

#define MODELS 5

#define FS 48000.0f
#define COEF(ms) __builtin_expf(-1.0f / ((ms) * 0.001f * FS))   /* folded at compile time */

struct model {
    float thresh, ratio, knee;   /* dB, x:1 (0 = infinite), dB */
    float att, rel_fast, rel_slow, auto_db;   /* smoothing coefficients; slow release once within auto_db of target */
    float rms;                   /* RMS detector coefficient, 0 = peak */
    float pre, makeup, mix;      /* linear input gain, linear output gain, wet share */
    int lookahead;               /* frames */
};

static const struct model models[MODELS] = {
    /* Glue: 2:1, 6 dB knee, 10 ms attack, auto release 100 -> 600 ms, RMS, +3 dB */
    {-18.0f, 2.0f, 6.0f, COEF(10.0f), COEF(100.0f), COEF(600.0f), 2.0f, COEF(10.0f), 1.0f, 1.4125f, 1.0f, 0},
    /* Punch: 4:1, 3 dB knee, 30 ms attack lets the hit through, 80 ms release, peak, +4 dB */
    {-20.0f, 4.0f, 3.0f, COEF(30.0f), COEF(80.0f), COEF(80.0f), 0.0f, 0.0f, 1.0f, 1.5849f, 1.0f, 0},
    /* Opto: 3:1, 10 dB knee, 10 ms attack, 60 ms then 1.5 s release, RMS, +4 dB */
    {-22.0f, 3.0f, 10.0f, COEF(10.0f), COEF(60.0f), COEF(1500.0f), 3.0f, COEF(20.0f), 1.0f, 1.5849f, 1.0f, 0},
    /* Squash: 20:1, hard, 0.5 ms attack, 60 ms release, peak, +12 dB wet, blended 50/50 with dry */
    {-35.0f, 20.0f, 0.0f, COEF(0.5f), COEF(60.0f), COEF(60.0f), 0.0f, 0.0f, 1.0f, 3.9811f, 0.5f, 0},
    /* Limit: +6 dB in, ceiling -0.3 dBFS, 1.5 ms look-ahead, 60 ms release */
    {-0.3f, 0.0f, 0.0f, COEF(0.5f), COEF(60.0f), COEF(60.0f), 0.0f, 0.0f, 1.9953f, 1.0f, 1.0f, 72},
};
#define CEILING 0.9661f          /* -0.3 dBFS */

#define LA_MAX 72
struct comp_state {
    uint32_t magic;
    uint32_t model;
    float gr;                    /* current gain reduction, dB (<= 0) */
    float ms;                    /* RMS detector: mean square */
    uint32_t la_pos;
    float la[LA_MAX][2];
};
#define S ((volatile struct comp_state *)0x38800400u)
/* 596 bytes: up to 3.3.g this ran 4 bytes into usbdev.c's state at 0x38800650, and Limit's lookahead wrote its last
   slot over the USB SETUP packet. usbdev.c moved to 0x38800680; this keeps it from coming back. */
_Static_assert(0x38800400u + sizeof(struct comp_state) <= 0x38800680u, "comp.c's state runs into usbdev.c's at 0x38800680");
#define MAGIC 0x434f4d31u        /* "COM1" */

/* log2 / exp2, bit tricks with quadratic correction (error ~0.005 / ~0.3%) */
static inline __attribute__((always_inline)) float log2f_fast(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xff) - 128);
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;
}

static inline __attribute__((always_inline)) float exp2f_fast(float x)
{
    if (x < -30.0f)
        return 0.0f;
    if (x > 30.0f)
        x = 30.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i;
    float p = 1.0f + f * (0.6565f + f * 0.3435f);           /* 2^f on [0, 1) */
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

static float computer(const struct model *m, float level_db)
{
    float over = level_db - m->thresh, slope = m->ratio > 0.0f ? 1.0f / m->ratio - 1.0f : -1.0f;
    if (m->knee > 0.0f && 2.0f * over > -m->knee && 2.0f * over < m->knee) {
        float k = over + 0.5f * m->knee;
        return slope * k * k / (2.0f * m->knee);
    }
    return over > 0.0f ? slope * over : 0.0f;
}

static void process(const struct model *m, float *l, float *r, int n)
{
    float gr = S->gr, ms = S->ms;
    uint32_t pos = S->la_pos;
    for (int i = 0; i < n; i++) {
        float xl = l[i] * m->pre, xr = r[i] * m->pre;
        float level;
        if (m->rms > 0.0f) {
            float p = 0.5f * (xl * xl + xr * xr);
            ms = p + m->rms * (ms - p);
            level = 3.0103f * log2f_fast(ms + 1e-12f);     /* 10 log10 */
        } else {
            float a = xl < 0.0f ? -xl : xl, b = xr < 0.0f ? -xr : xr;
            level = 6.0206f * log2f_fast((a > b ? a : b) + 1e-9f);   /* 20 log10 */
        }
        float target = computer(m, level);
        if (target < gr)
            gr = target + m->att * (gr - target);
        else
            gr = target + (target - gr < m->auto_db ? m->rel_slow : m->rel_fast) * (gr - target);
        float g = exp2f_fast(gr * 0.16610f) * m->makeup;   /* dB -> linear */
        float dl = xl, dr = xr;
        if (m->lookahead) {
            dl = S->la[pos][0];
            dr = S->la[pos][1];
            S->la[pos][0] = xl;
            S->la[pos][1] = xr;
            if (++pos >= (uint32_t)m->lookahead)
                pos = 0;
        }
        float yl = dl * g, yr = dr * g;
        if (m->mix < 1.0f) {
            yl = m->mix * yl + (1.0f - m->mix) * dl / m->pre;
            yr = m->mix * yr + (1.0f - m->mix) * dr / m->pre;
        }
        yl = yl > CEILING ? CEILING : yl < -CEILING ? -CEILING : yl;
        yr = yr > CEILING ? CEILING : yr < -CEILING ? -CEILING : yr;
        l[i] = yl;
        r[i] = yr;
    }
    S->gr = gr;
    S->ms = ms;
    S->la_pos = pos;
}

/* One block of model `model` (2 .. 6, the list value) on Out 1, Comp Thresh `off` dB (-24 .. +12). Up to 3.3.x this was
   inline in comp_process. The state starts over when the model changes or anything else used the block. */
void comp_model_block(unsigned model, float off, float *l, float *r, int n)
{
    if (S->magic != MAGIC || S->model != model) {
        S->gr = 0.0f;
        S->ms = 0.0f;
        S->la_pos = 0;
        for (int i = 0; i < LA_MAX; i++)
            S->la[i][0] = S->la[i][1] = 0.0f;
        S->model = model;
        S->magic = MAGIC;
    }
    if (n > 0) {
        struct model m = models[model - 2];
        if (m.ratio > 0.0f)
            m.thresh += off;
        else
            m.pre *= exp2f_fast(-off * 0.16610f);            /* Limit: lower threshold = more push into the ceiling */
        process(&m, l, r, n);
    }
}
