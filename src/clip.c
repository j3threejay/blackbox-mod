/*
 * The master clipper: the last thing on Out 1, after the compressor. Original 1010music Blackbox, firmware 3.1.9.
 * No firmware calls in this file: host/render_clip.py compiles it for the Mac, so what is rendered there is this code.
 *
 *   Clip    how hard the mix is pushed into the ceiling: 0 .. +18 dB. At 0 it only catches what is already over.
 *   Shape   where the rounding starts: 0 % = from the bottom (a parabola all the way up, soft), 100 % = not at all
 *           (flat top, hard). In between, the signal is untouched up to Shape x ceiling and rounded from there; the
 *           last few percent are the "converter" clip: hard, with the corner just taken off.
 *   Clean   the same curve both ways.
 *   Diode   the two halves differ, as with one diode against two: the top half rounds earlier (half the Shape) and
 *           stops at 0.75 of the ceiling. That adds even harmonics; a blocker takes off the offset it leaves.
 * The ceiling is -0.3 dBFS, the Limit model's. Nothing leaves above it.
 *
 * A clipper makes harmonics without end, and at 48 kHz the ones past 24 kHz fold back down as harsh, unrelated
 * tones. So the curve runs at 96 kHz: each sample and the point half way to the next (an 11-tap maximally flat
 * half-band interpolator). Only what the curve TOOK OFF is brought back down (the same half-band) and added to the
 * input, five samples late. So below the knee the output is the input, bit for bit, and only the clipping products
 * are band-limited. A band-limited clip overshoots a little (it cannot be both), so a plain clamp at the ceiling
 * finishes; that clamp is all that still folds back. Measured against a plain clip: host/render_clip.py.
 */
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* per-sample on the master, built for speed (3.3.l) */
#include "clip.h"

#define CEILING 0.9661f          /* -0.3 dBFS, as comp.c's Limit */
#define MAGIC   0x434c5032u      /* "CLP2" */

struct half {
    float t, top, inv;           /* knee start (of this half's ceiling), this half's ceiling, 1 / it */
};

/* what the curve takes off u: 0 up to the knee. h[0] = the top half, h[1] = the bottom. */
static inline float cut(float u, const struct half *h)
{
    const struct half *k = &h[u < 0.0f];
    float a = (u < 0.0f ? -u : u) * k->inv, y;
    if (a <= k->t)
        return 0.0f;
    if (a >= 2.0f - k->t) {
        y = 1.0f;
    } else {
        float d = a - k->t;
        y = a - d * d / (4.0f * (1.0f - k->t));
    }
    y *= k->top;
    return (u < 0.0f ? -y : y) - u;
}

void clip_block(struct clip_state *s, int type, float amount, float shape, float *l, float *r, int n)
{
    if (type <= CLIP_OFF || type >= CLIP_TYPES || n <= 0) {
        s->magic = 0;
        return;
    }
    amount = amount < 0.0f ? 0.0f : amount > 1.0f ? 1.0f : amount;
    shape = shape < 0.0f ? 0.0f : shape > 0.995f ? 0.995f : shape;      /* 0.995: a corner 0.5 % wide, never a divide by 0 */
    /* 10^(18 x amount / 20) = e^(2.0723 x amount): a short series, squared twice; within 0.2 % */
    float e = 2.0723f * amount * 0.25f, g = 1.0f + e * (1.0f + e * (0.5f + e * (1.0f / 6.0f)));
    g *= g;
    g *= g;
    g *= 1.0f / CEILING;                                     /* work with the ceiling at 1 */
    if (s->magic != MAGIC) {
        for (unsigned i = 0; i < sizeof *s / 4; i++)
            ((uint32_t *)s)[i] = 0;
        s->gain = g;
        s->magic = MAGIC;
    }
    struct half h[2] = {{shape, 1.0f, 1.0f}, {shape, 1.0f, 1.0f}};
    if (type == CLIP_DIODE) {
        h[0].t = 0.5f * shape;
        h[0].top = 0.75f;
        h[0].inv = 1.0f / 0.75f;
    }
    float g0 = s->gain, dg = (g - g0) / (float)n;
    float *ch[2] = {l, r};
    for (int c = 0; c < 2; c++) {
        float *x = ch[c];
        if (!x)
            continue;
        float *in = s->in[c], *d = s->cut[c];
        float gi = g0, dc_in = s->dc_in[c], dc_out = s->dc_out[c];
        uint32_t p = s->pos;
        for (int i = 0; i < n; i++, p++) {
            gi += dg;
            in[p & 7] = x[i] * gi;
#define IN(k) in[(p - (k)) & 7]
#define D(k)  d[(2 * p - (k)) & 15]
            /* 96 kHz: the point half way between in[-3] and in[-2], then in[-2] itself */
            float mid = (3.0f * (IN(0) + IN(5)) - 25.0f * (IN(1) + IN(4)) + 150.0f * (IN(2) + IN(3))) * (1.0f / 256.0f);
            D(0) = cut(mid, h);
            d[(2 * p + 1) & 15] = cut(IN(2), h);
            /* back to 48 kHz, centred on in[-5] */
            float off = 0.5f * D(5) + (3.0f * (D(0) + D(10)) - 25.0f * (D(2) + D(8)) + 150.0f * (D(4) + D(6))) * (1.0f / 512.0f);
            float out = IN(5) + off;
#undef IN
#undef D
            if (type == CLIP_DIODE) {                        /* about 5 Hz */
                dc_out = out - dc_in + 0.99935f * dc_out;
                dc_in = out;
                out = dc_out;
            }
            x[i] = (out > 1.0f ? 1.0f : out < -1.0f ? -1.0f : out) * CEILING;
        }
        s->dc_in[c] = dc_in;
        s->dc_out[c] = dc_out;
    }
    s->pos += (uint32_t)n;
    s->gain = g;
}
