/*
 * RTA (real-time analyser) on the master EQ screen: the analysis and the drawing (rta.c has the hooks). Flash bank 2.
 *
 * Audio task: rta_feed keeps the last RTA_N frames of Out 1 right after the stock EQ, (L + R) / 2, while the EQ screen
 * is showing (alive). GUI task: rta_frame runs on every overlay pass of the EQ graph, before stock draws its curve and
 * nodes. Every third frame (~20 a second) it takes the newest RTA_N frames, Hann window, 2048-point real FFT (as a
 * 1024-point complex one), power per bin, then one value per pixel column on the graph's own frequency axis (x = 32 log2(f / 20), 20 Hz .. 20.48 kHz, as
 * stock maps it): below ~400 Hz a column sits between two bins and is interpolated, above it takes the loudest bin it
 * covers. +4.5 dB / octave tilt around 1 kHz (FabFilter's default), so a mix reads roughly flat. A column rises at once
 * and falls 1.5 dB an update (~30 dB a second). Drawn as a line in palette index RTA_COLOUR, so themes colour it.
 * Scale: a full-scale sine reads 0 dB; the graph shows RTA_TOP at its top edge down to RTA_BOTTOM at the bottom.
 * Calls out of bank 2: stock's line primitive only.
 */
#include <stdint.h>
#include "rta.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*line_fn)(const int32_t *p0, const int32_t *p1, int colour, void *canvas);
#define fw_line ((line_fn)FN(0x0808ea7e))

#define RTA_TOP     (-6.0f)
#define RTA_BOTTOM  (-90.0f)
#define RTA_TILT    4.5f         /* dB per octave, 0 dB at 1 kHz */
#define RTA_FALL    1.5f         /* dB an update */
#define RTA_EVERY   3            /* GUI frames per update */
#define RTA_COLOUR  17           /* the dim grey of the waveform labels (theme.c) */
#define FS 48000.0

static inline float log2_fast(float x)
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)(int32_t)((v.u >> 23) & 0xffu) - 128.0f;   /* the polynomial below carries the +1 */
    v.u = (v.u & 0x7fffffu) | 0x3f800000u;
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;
}

static void tables(struct rta_state *s)
{
    /* twiddles by rotation in double: cos / sin of the step from their Taylor series (theta = 0.0031) */
    double th = 6.283185307179586 / RTA_N, t2 = th * th;
    double dc = 1.0 - t2 / 2.0 + t2 * t2 / 24.0 - t2 * t2 * t2 / 720.0;
    double ds = th * (1.0 - t2 / 6.0 + t2 * t2 / 120.0 - t2 * t2 * t2 / 5040.0);
    double c = 1.0, sn = 0.0;
    for (int k = 0; k < RTA_N / 2; k++) {
        s->cs[k] = (float)c;
        s->sn[k] = (float)sn;
        double c2 = c * dc - sn * ds;
        sn = sn * dc + c * ds;
        c = c2;
    }
    /* columns: centre f = 20 * 2^(x / 32), edges half a column either side, in bins */
    const double col = 1.0218971486541166, half = 1.0108892860517005;      /* 2^(1/32), 2^(1/64) */
    double b = 20.0 * RTA_N / FS;
    for (int x = 0; x < RTA_COLS; x++, b *= col) {
        double lo = b / half, hi = b * half;
        if (hi - lo < 1.0) {                                 /* narrower than a bin: interpolate at the centre */
            int i = (int)b;
            s->lo[x] = (uint16_t)i;
            s->hi[x] = 0;
            s->fr[x] = (float)(b - i);
        } else {
            int i = (int)(lo + 0.5), j = (int)(hi + 0.5);
            if (j > RTA_N / 2)
                j = RTA_N / 2;
            s->lo[x] = (uint16_t)i;
            s->hi[x] = (uint16_t)(j > i ? j : i + 1);
            s->fr[x] = 0.0f;
        }
        s->db[x] = RTA_BOTTOM - 10.0f;
    }
}

static struct rta_state *ready(struct rta_state *s)
{
    if (s->magic != RTA_MAGIC) {
        s->alive = 0;
        s->w = 0;
        s->frame = 0;
        for (int i = 0; i < RTA_N; i++)
            s->ring[i] = 0.0f;
        tables(s);
        s->magic = RTA_MAGIC;
    }
    return s;
}

/* ---- audio ---- */

void rta_feed(struct rta_state *s, const float *l, const float *r, int n)
{
    if (s->magic != RTA_MAGIC || !s->alive)
        return;
    s->alive--;
    uint32_t w = s->w;
    float *ring = s->ring;
    if (!l)
        for (int i = 0; i < n; i++)
            ring[w++ & (RTA_N - 1)] = 0.0f;
    else if (!r)
        for (int i = 0; i < n; i++)
            ring[w++ & (RTA_N - 1)] = l[i];
    else
        for (int i = 0; i < n; i++)
            ring[w++ & (RTA_N - 1)] = 0.5f * (l[i] + r[i]);
    s->w = w;
}

/* ---- GUI ---- */

/* N / 2 = M-point complex FFT in place; its twiddles cos / sin(2 pi k / M) are the N-point tables' every second entry */
static void fft(float *re, float *im, const float *cs, const float *sn)
{
    const unsigned M = RTA_N / 2;
    for (unsigned i = 1, j = 0; i < M; i++) {
        unsigned bit = M >> 1;
        for (; j & bit; bit >>= 1)
            j ^= bit;
        j ^= bit;
        if (i < j) {
            float t = re[i];
            re[i] = re[j];
            re[j] = t;
            t = im[i];
            im[i] = im[j];
            im[j] = t;
        }
    }
    for (unsigned len = 2; len <= M; len <<= 1) {
        unsigned half = len >> 1, step = 2 * (M / len);
        for (unsigned k = 0; k < half; k++) {
            float wr = cs[k * step], wi = -sn[k * step];
            for (unsigned a = k; a < M; a += len) {
                unsigned b = a + half;
                float tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] += tr;
                im[a] += ti;
            }
        }
    }
}

static void update(struct rta_state *s)
{
    const unsigned M = RTA_N / 2;
    uint32_t w = s->w;
    /* the newest RTA_N frames, oldest first, Hann window; even frames into re, odd into im (the real-input trick) */
    for (unsigned n = 0; n < RTA_N; n++) {
        float c = n < M ? s->cs[n] : n == M ? -1.0f : s->cs[RTA_N - n];
        float v = s->ring[(w + n) & (RTA_N - 1)] * (0.5f - 0.5f * c);
        if (n & 1)
            s->im[n >> 1] = v;
        else
            s->re[n >> 1] = v;
    }
    fft(s->re, s->im, s->cs, s->sn);
    /* X[k] = E[k] + e^(-2 pi i k / N) O[k], E / O from Z[k] and conj Z[M - k]; power into pw[] */
    for (unsigned k = 0; k <= M; k++) {
        unsigned a = k == M ? 0 : k, b = k == 0 ? 0 : M - k;
        float zr = s->re[a], zi = s->im[a], cr = s->re[b], ci = -s->im[b];
        float er = 0.5f * (zr + cr), ei = 0.5f * (zi + ci);
        float orr = 0.5f * (zi - ci), oi = -0.5f * (zr - cr);
        float wr = k < M ? s->cs[k] : -1.0f, wi = k < M ? -s->sn[k] : 0.0f;
        float xr = er + orr * wr - oi * wi, xi = ei + orr * wi + oi * wr;
        s->pw[k] = xr * xr + xi * xi;
    }
    /* 0 dB = a full-scale sine: its peak bin is (N / 4)^2 through the Hann window */
    const float norm = 1.0f / ((RTA_N / 4.0f) * (RTA_N / 4.0f));
    for (int x = 0; x < RTA_COLS; x++) {
        float p;
        unsigned lo = s->lo[x], hi = s->hi[x];
        if (!hi) {
            p = s->pw[lo] + s->fr[x] * (s->pw[lo + 1] - s->pw[lo]);
        } else {
            p = s->pw[lo];
            for (unsigned k = lo + 1; k < hi; k++)
                p = s->pw[k] > p ? s->pw[k] : p;
        }
        p *= norm;
        float db = p > 1e-13f ? 3.0103f * log2_fast(p) : -130.0f;
        db += RTA_TILT * ((float)x * (1.0f / 32.0f) - 5.643856f);      /* log2(1000 / 20) */
        float was = s->db[x] - RTA_FALL;
        s->db[x] = db > was ? db : was;
    }
}

static int32_t y_of(float db, int32_t y0, int32_t h)
{
    float t = (db - RTA_BOTTOM) * (1.0f / (RTA_TOP - RTA_BOTTOM));
    t = t < 0.0f ? 0.0f : t > 1.0f ? 1.0f : t;
    return y0 + (int32_t)(t * (float)(h - 1));
}

void rta_frame(struct rta_state *s, const int32_t *rect, void *canvas)
{
    ready(s);
    if (s->frame++ % RTA_EVERY == 0)
        update(s);
    int32_t x0 = rect[0], y0 = rect[1], w = rect[2], h = rect[3];
    if (w <= 1 || h <= 1)
        return;
    int cols = w < RTA_COLS ? w : RTA_COLS;
    int32_t p0[2] = {x0, y_of(s->db[0], y0, h)}, p1[2];
    for (int x = 1; x < cols; x++) {
        p1[0] = x0 + x;
        p1[1] = y_of(s->db[x], y0, h);
        if (p0[1] > y0 || p1[1] > y0)                     /* nothing along the floor */
            fw_line(p0, p1, RTA_COLOUR, canvas);
        p0[0] = p1[0];
        p0[1] = p1[1];
    }
}
