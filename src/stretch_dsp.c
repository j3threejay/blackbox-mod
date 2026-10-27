/*
 * Clip time-stretch models, the DSP (stretch.h). Flash bank 2; also built for the Mac (host/render_stretch.py).
 *
 * All three work inside one stock slice (stretch.h): a REFERENCE head walks the slice's source at ref_rate (it reaches
 * the next slice's first frame exactly when the grid does) and the audio is read at the pad's pitch near it.
 *
 * SMOOTH  WSOLA: 1024-frame grains, a new one every 512 output frames, sin^2 crossfades (they sum to one). Each new
 *         grain is taken within +-256 frames of the reference, where it best matches what the old grain is about to
 *         play (normalised cross-correlation on (L + R) / 2: coarse every 8 lags, then every lag +-7 around the best,
 *         every 4th frame of a 512-frame window).
 * CYCLIC  The S-series "cyclic" colour: 2400-frame (50 ms) grains taken AT the reference, no matching, 96-frame linear
 *         joins. The repeats / skips are the sound.
 * KEYFRAME After "Keyframe Time Stretching via Extrema Sampling" (M. Nielsen, DAFx26, CC-BY-4.0). Adapted from
 *         research/stretch/keyframe.c, a clean-room version written from the paper only. Live changes: keyframes are
 *         analysed as the slice plays into a 512-entry ring per channel instead of for the whole file; the
 *         timing decisions (leash, splice length, alignment) are taken on L's keyframes, not on a third (L + R) / 2
 *         set (a third of the analysis, measured: test_stretch.py); the onset lock is left out (each stock slice
 *         already starts on time). Kept: zero-tangent Hermite reconstruction,
 *         the K = 64 keyframe leash, splice length from the span of K keyframes, the polarity / spacing alignment.
 *
 * Calls out of bank 2: only src->fetch (stock's sample fetch, passed in).
 */
#include <stdint.h>
#include "stretch.h"

#ifndef STR_HOST
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")
#endif

#define CHUNK 240                /* output frames per inner pass: CHUNK x rate + 4 must fit half the scratch */
#define RATE_MAX 8.0f
#define HALF (STR_SCRATCH / 2)

/* ---------------------------------------------------------------- grain engine (Smooth, Cyclic) */

#define SM_N 1024
#define SM_F 512
#define SM_D STR_SM_REACH
#ifndef SM_DEC
#define SM_DEC 16                /* search: every 16th frame of the window in the coarse passes */
#endif
#ifndef SM_STEP
#define SM_STEP 8                /* coarse lag step (16 misses the match: host/lsd.py, 10-24) */
#endif
#ifndef SM_DEC2
#define SM_DEC2 2                /* the last pass's frames */
#endif
#define CY_N 2496
#define CY_F 96

/* the incoming grain's gain; the outgoing one gets 1 - this, so any shape sums to one. Smooth: smoothstep (~sin^2). */
static float fade_in(int model, int a, int F)
{
    float x = (float)a / (float)F;
    return model == STR_CYCLIC ? x : x * x * (3.0f - 2.0f * x);
}

/*
 * Read n frames from head h at rate into dl / dr with gains g0 + k x dg added (add = 1) or stored, and move h on.
 * 4-point Hermite between source frames; a plain copy when the head sits on a frame at rate 1.
 */
static void head_read(const struct str_src *src, struct str_grain *h, float rate, int n, float *dl, float *dr,
                      float g0, float dg, int add, float *scratch)
{
    float *sl = scratch, *sr = scratch + HALF;
    if (n <= 0)
        return;
    if (rate == 1.0f && h->f == 0.0f) {
        src->fetch(src, sl, src->stereo ? sr : 0, n, h->i);
        for (int k = 0; k < n; k++) {
            float g = g0 + dg * (float)k;
            float a = sl[k] * g, b = (src->stereo ? sr[k] : sl[k]) * g;
            if (add) { dl[k] += a; if (dr) dr[k] += b; }
            else     { dl[k] = a;  if (dr) dr[k] = b; }
        }
        h->i += n;
        return;
    }
    int need = (int)((float)n * rate + h->f) + 4;
    src->fetch(src, sl, src->stereo ? sr : 0, need, h->i - 1);
    float p = h->f;                                      /* sl[1] is frame h->i */
    for (int k = 0; k < n; k++) {
        int j = (int)p;
        float t = p - (float)j, g = g0 + dg * (float)k;
        const float *x = sl + j;
        float c1 = 0.5f * (x[2] - x[0]), c3 = 1.5f * (x[1] - x[2]) + 0.5f * (x[3] - x[0]);
        float c2 = x[0] - x[1] + c1 - c3;
        float a = ((c3 * t + c2) * t + c1) * t + x[1];
        float b = a;
        if (src->stereo) {
            x = sr + j;
            c1 = 0.5f * (x[2] - x[0]); c3 = 1.5f * (x[1] - x[2]) + 0.5f * (x[3] - x[0]);
            c2 = x[0] - x[1] + c1 - c3;
            b = ((c3 * t + c2) * t + c1) * t + x[1];
        }
        if (add) { dl[k] += a * g; if (dr) dr[k] += b * g; }
        else     { dl[k] = a * g;  if (dr) dr[k] = b * g; }
        p += rate;
    }
    int adv = (int)p;
    h->i += adv;
    h->f = p - (float)adv;
}

/* (L + R) / 2 of n frames from pos into m and, with s, (L - R) / 2 into s (stereo only). R stays in the fetch area's
   second half until the next fetch. */
static void fetch_ms(const struct str_src *src, float *m, float *s, int n, int32_t pos, float *scratch)
{
    float *sr = scratch + HALF;
    src->fetch(src, m, src->stereo ? sr : 0, n, pos);
    if (!src->stereo)
        return;
    if (s)
        for (int k = 0; k < n; k++) {
            float l = m[k], r = sr[k];
            m[k] = 0.5f * (l + r);
            s[k] = 0.5f * (l - r);
        }
    else
        for (int k = 0; k < n; k++)
            m[k] = 0.5f * (m[k] + sr[k]);
}

static float sqrt_(float x)
{
#ifdef STR_HOST
    return __builtin_sqrtf(x);
#else
    float r;
    __asm__("vsqrt.f32 %0, %1" : "=t"(r) : "t"(x));
    return r;
#endif
}

/* normalised correlation of the side windows xs and (ym - yr) (= (L - R) / 2) over n points of stride 2, clamped
   to 0..1 (an anti-phase join counts as none) */
static float side_match(const float *xs, const float *ym, const float *yr, int n)
{
    float xy = 0.0f, xx = 1e-9f, yy = 1e-9f;
    for (int k = 0; k < 2 * n; k += 2) {
        float v = ym[k] - yr[k];
        xy += xs[k] * v;
        xx += xs[k] * xs[k];
        yy += v * v;
    }
    float c = xy / sqrt_(xx * yy);
    return c < 0.0f ? 0.0f : c > 1.0f ? 1.0f : c;
}

/* x . y and y . y over n points of stride S (n a multiple of 4): unrolled, the stride a constant */
#define DOT(NAME, S)                                                                                                   \
    static void NAME(const float *x, const float *y, int n, float *xy, float *ee)                                     \
    {                                                                                                                  \
        float a0 = 0.0f, a1 = 0.0f, e0 = 1e-9f, e1 = 0.0f;                                                            \
        for (int k = 0; k < n * (S); k += 4 * (S)) {                                                                   \
            float v0 = y[k], v1 = y[k + (S)], v2 = y[k + 2 * (S)], v3 = y[k + 3 * (S)];                                \
            a0 += x[k] * v0 + x[k + 2 * (S)] * v2;                                                                     \
            a1 += x[k + (S)] * v1 + x[k + 3 * (S)] * v3;                                                               \
            e0 += v0 * v0 + v2 * v2;                                                                                   \
            e1 += v1 * v1 + v3 * v3;                                                                                   \
        }                                                                                                              \
        *xy = a0 + a1;                                                                                                 \
        *ee = e0 + e1;                                                                                                 \
    }
DOT(dot_coarse, SM_DEC)
DOT(dot_fine, SM_DEC2)

/*
 * The best grain start within +-SM_D of target, matched against the natural continuation at nat: normalised
 * cross-correlation on (L + R) / 2. Lags every SM_STEP frames on every SM_DEC-th frame of the window, then every 4
 * around the best, then every 1 on every SM_DEC2-th frame. Settings from a sweep against the Signalsmith renders
 * (host/lsd.py, 10-24): a coarse lag step of 16 misses the match; 1-in-16 frames in the coarse passes costs nothing.
 * SM_D 640 (was 256): a 41-55 Hz cycle is longer than +-256, so past ~-5 BPM the joins landed off phase (tester
 * clicks, 10-25). Searching +-256 first and widening only on a poor match does NOT fix it: a near, slightly off-phase
 * match still scores > 0.95 and still clicks (host, 10-26).
 */
static int32_t wsola_search(struct str_seg *g, const struct str_src *src, int32_t nat, int32_t target, float *scratch)
{
    enum { W = SM_F, SPAN = 2 * SM_D + W };
    _Static_assert(SPAN <= HALF, "y's R channel stays in the fetch area's second half");
    float *x = scratch + 2 * HALF, *y = x + W;           /* behind the fetch area (STR_SCRATCH_ALL) */
    float *xs = scratch, *yr = scratch + HALF;           /* x's side; y's R (left there by the fetch) */
    fetch_ms(src, x, xs, W, nat, scratch);
    fetch_ms(src, y, 0, SPAN, target - SM_D, scratch);
    float best = -1e30f;
    int bl = SM_D;
    for (int l = 0; l <= 2 * SM_D; l += SM_STEP) {      /* coarse */
        float xy, ee;
        dot_coarse(x, y + l, W / SM_DEC, &xy, &ee);
        float c = xy * (xy < 0.0f ? -xy : xy) / ee;
        if (c > best) { best = c; bl = l; }
    }
    static const int8_t steps[2] = {4, 1}, reach[2] = {SM_STEP - 4, 3};
    for (int pass = 0; pass < 2; pass++) {
        int st = steps[pass], lo = bl - reach[pass], hi = bl + reach[pass];
        if (lo < 0) lo = 0;
        if (hi > 2 * SM_D) hi = 2 * SM_D;
        if (pass == 1) best = -1e30f;                    /* finer points: a new scale for the scores */
        for (int l = lo; l <= hi; l += st) {
            float xy, ee;
            if (pass == 0) dot_coarse(x, y + l, W / SM_DEC, &xy, &ee);
            else           dot_fine(x, y + l, W / SM_DEC2, &xy, &ee);
            float c = xy * (xy < 0.0f ? -xy : xy) / ee;
            if (c > best) { best = c; bl = l; }
        }
    }
    g->cs = src->stereo ? side_match(xs, y + bl, yr + bl, W / 2) : 1.0f;
    return target - SM_D + bl;
}

/* Smooth's side gain for a join whose side matched c: incoming a, outgoing 1 - a, scaled so the power holds (c 1 =
   1). Side only: lifting the mid the same way overshot drum peaks by up to 1.4 dB for 0.1 dB (host, 10-26). */
static float join_gain(float a, float c)
{
    float b = 1.0f - a;
    return 1.0f / sqrt_(a * a + b * b + 2.0f * a * b * c);
}

static void grain_render(struct str_seg *g, int model, const struct str_src *src, float rate, float ref_rate,
                         float *ol, float *orr, int n, float *scratch)
{
    const int N = model == STR_CYCLIC ? CY_N : SM_N, F = model == STR_CYCLIC ? CY_F : SM_F, hop = N - F;
    if (g->fresh) {
        g->cur.i = g->start;                             /* the first grain fades against itself: plain */
        g->cur.f = 0.0f;
        g->old = g->cur;
        /* Smooth: every synced clip starts its slices on the same frame, so without this all their searches land in
           the same engine block (tester peaks 10-25); about half the slices (by where they start in their file) run
           half a hop ahead. The first grain is plain, so nothing is heard. */
        g->age = model == STR_SMOOTH && (((uint32_t)g->start >> 6) & 1) ? hop / 2 : 0;
        g->cs = 1.0f;
        g->fresh = 0;
    }
    int o = 0;
    while (o < n) {
        if (g->age >= hop) {                             /* next grain */
            float r = (float)g->start + (float)g->t * ref_rate;
            int32_t target = (int32_t)r;
            if (model == STR_CYCLIC)
                target -= (int32_t)((float)(F / 2) * rate);   /* centre the join on the grain's nominal start */
            g->old = g->cur;
            if (model == STR_SMOOTH)
                target = wsola_search(g, src, g->cur.i, target, scratch);
            g->cur.i = target;
            g->cur.f = model == STR_SMOOTH ? g->cur.f : r - (float)(int32_t)r;   /* Smooth: keep the matched phase */
            g->age = 0;
        }
        int c = n - o;
        if (c > CHUNK) c = CHUNK;
        if (c > hop - g->age) c = hop - g->age;
        float *dl = ol + o, *dr = orr ? orr + o : 0;
        if (g->age < F) {
            int cf = F - g->age < c ? F - g->age : c;
            float a0 = fade_in(model, g->age, F), a1 = fade_in(model, g->age + cf, F);
            float dg = (a1 - a0) / (float)cf;
            /* a linear segment of the fade per chunk: Smooth's sin^2 over <= 240 of 512 frames, < 0.5 % off */
            head_read(src, &g->cur, rate, cf, dl, dr, a0, dg, 0, scratch);
            head_read(src, &g->old, rate, cf, dl, dr, 1.0f - a0, -dg, 1, scratch);
            if (model == STR_SMOOTH && dr && g->cs < 0.9f) {   /* above 0.9 the lift is < 0.2 dB: skip */
                /* the search aligns the mid; the side's unmatched part adds as power, not amplitude (tester: "the
                   stereo field becomes more constricted", 10-25): lift the side by its own match */
                float s0 = join_gain(a0, g->cs), ds = (join_gain(a1, g->cs) - s0) / (float)cf;
                for (int k = 0; k < cf; k++) {
                    float m = 0.5f * (dl[k] + dr[k]), s = 0.5f * (dl[k] - dr[k]) * (s0 + ds * (float)k);
                    dl[k] = m + s;
                    dr[k] = m - s;
                }
            }
            if (cf < c)
                head_read(src, &g->cur, rate, c - cf, dl + cf, dr ? dr + cf : 0, 1.0f, 0.0f, 0, scratch);
        } else {
            head_read(src, &g->cur, rate, c, dl, dr, 1.0f, 0.0f, 0, scratch);
        }
        g->age += c;
        g->t += (uint32_t)c;
        o += c;
    }
}

/* ---------------------------------------------------------------- keyframe engine */

#define KF_K 64
#define KF_EPS 0.001f
#define KF_GAP 512
#define KF_LMIN 128.0f
#define KF_LMAX 4800.0f
#define KF_DMAX 9600.0f
#define KF_RADIUS 8
#define KF_MAXSHIFT 480.0f
#define KF_LOOK 1200             /* frames analysed ahead of the furthest head when there is time */
#define KF_CHECK 16              /* frames between leash checks */
#define KF_BUDGET 3              /* analysis frames per output frame when catching up */
#define MASK (STR_KF_RING - 1)
#define FX_INV (1.0f / 256.0f)
#define SL 0
#define SR 1
#define ST SL                    /* the set the timing decisions read */

static void copy_words(void *dst, const void *src, unsigned bytes)
{
    uint32_t *d = dst;
    const uint32_t *q = src;
    for (unsigned i = 0; i < bytes / 4; i++)
        d[i] = q[i];
}

static int sgnf(float v) { return (v > 0.0f) - (v < 0.0f); }
static float fabsf_(float v) { return v < 0.0f ? -v : v; }

/* The extremum's value: Catmull-Rom between p0 and p1 at t. The paper's cubic B-spline APPROXIMATES (it shrinks
   sample-rate peaks: -1.5..-2.2 dB above 4 kHz on drum loops, tester 10-25); this passes through the samples. */
static float bspline(float pm1, float p0, float p1, float p2, float t)
{
    float c1 = 0.5f * (p1 - pm1), c3 = 1.5f * (p0 - p1) + 0.5f * (p2 - pm1), c2 = pm1 - p0 + c1 - c3;
    return ((c3 * t + c2) * t + c1) * t + p0;
}

static uint32_t *kcount(struct str_seg *g, int s) { return s == SL ? &g->kf.m_l : &g->kf.m_r; }

static void kf_put(struct str_seg *g, int s, uint32_t p, float v)
{
    uint32_t *m = kcount(g, s);
    g->set[s].pos[*m & MASK] = p;
    g->set[s].val[*m & MASK] = v;
    (*m)++;
    g->kf.last[s] = p;
    g->kf.vprev[s] = v;
}

/* Algorithm 1 for frames n in [n0, n1) of set s. x[k] = source frame base + k; needs x[n - 2 .. n + 1]. */
static void kf_analyse(struct str_seg *g, int s, const float *x, int32_t base, int32_t n0, int32_t n1, int32_t len)
{
    float vprev = g->kf.vprev[s], dprev = g->kf.dprev[s];
    int sprev = g->kf.sprev[s];
    int32_t last_n = g->kf.last_n[s];
    const float *q = x + (n0 - base);
    for (int32_t n = n0; n < n1; n++, q++) {
        float x1 = q[-1], x3 = q[1];
        float d = 0.5f * (x3 - x1);
        int sn = (d > 0.0f) - (d < 0.0f);
        if (sn == 0 || sn == sprev || sprev == 0) {      /* the common case: no turn of the slope */
            if (sn != 0)
                sprev = sn;
            dprev = d;
            if (n - last_n >= KF_GAP && n < len - 1) {   /* gap keyframe */
                uint32_t p = (uint32_t)n << 8;
                if (p > g->kf.last[s]) {
                    vprev = q[0];                       /* the sample itself (was B-spline smoothed) */
                    kf_put(g, s, p, vprev);
                    last_n = n;
                }
            }
            continue;
        }
        float x0 = q[-2], x2 = q[0];
        int saved = 0;
        if (fabsf_(x2 - vprev) > KF_EPS) {
            float den = fabsf_(dprev) + fabsf_(d);
            float al = den > 0.0f ? fabsf_(dprev) / den : 0.0f;
            uint32_t p = ((uint32_t)(n - 1) << 8) + (uint32_t)(al * 256.0f + 0.5f);
            if (p <= g->kf.last[s])
                p = g->kf.last[s] + 1;
            vprev = bspline(x0, x1, x2, x3, al);
            kf_put(g, s, p, vprev);
            last_n = n;
            saved = 1;
        }
        sprev = sn;
        dprev = d;
        if (!saved && n - last_n >= KF_GAP && n < len - 1) {
            uint32_t p = (uint32_t)n << 8;
            if (p > g->kf.last[s]) {
                vprev = x2;
                kf_put(g, s, p, vprev);
                last_n = n;
            }
        }
    }
    g->kf.vprev[s] = vprev;
    g->kf.dprev[s] = dprev;
    g->kf.sprev[s] = sprev;
    g->kf.last_n[s] = last_n;
}

/* Analyse frames [an, an + cnt): fetch n - 2 .. n + 1 around them, all sets. */
static void kf_piece(struct str_seg *g, const struct str_src *src, int32_t cnt, float *scratch)
{
    int32_t n0 = g->kf.an, n1 = n0 + cnt;
    if (n1 > src->len) n1 = src->len;
    if (n1 <= n0) return;
    int got = n1 - n0 + 3;                               /* frames n0 - 2 .. n1 */
    float *l = scratch, *r = scratch + HALF;
    src->fetch(src, l, src->stereo ? r : 0, got, n0 - 2);
    int32_t base = n0 - 2;
    kf_analyse(g, SL, l, base, n0, n1, src->len);
    if (src->stereo)
        kf_analyse(g, SR, r, base, n0, n1, src->len);
    g->kf.an = n1;
    if (g->kf.an >= src->len && src->len > 1) {          /* the final anchor */
        float v[1], rr[1];
        uint32_t p = (uint32_t)(src->len - 1) << 8;
        src->fetch(src, v, src->stereo ? rr : 0, 1, src->len - 1);
        for (int s = 0; s < (src->stereo ? 2 : 1); s++)
            if (p > g->kf.last[s])
                kf_put(g, s, p, s == SL ? v[0] : rr[0]);
    }
}

#define KF_PIECE 64

/* Keyframes set s may still need: from the oldest reader in it (less the alignment's reach) */
static uint32_t kf_oldest(struct str_seg *g, const struct str_src *src, int s)
{
    struct str_kfph *a = &g->kf.ph[0], *b = &g->kf.ph[1];
    uint32_t m;
    (void)src;
    if (s == SL) m = a->l.m < b->l.m ? a->l.m : b->l.m;
    else m = a->r.m < b->r.m ? a->r.m : b->r.m;
    if (s == ST && g->kf.ref.m < m) m = g->kf.ref.m;
    return m > KF_RADIUS + 2 ? m - (KF_RADIUS + 2) : 0;
}

/* Room for one more piece in every set's ring? (a piece writes at most KF_PIECE keyframes a set) */
static int kf_room(struct str_seg *g, const struct str_src *src)
{
    for (int s = 0; s < (src->stereo ? 2 : 1); s++)
        if (*kcount(g, s) - kf_oldest(g, src, s) + KF_PIECE + 1 > STR_KF_RING)
            return 0;
    return 1;
}

/*
 * MUST: every set has a keyframe past frame `need` (so a reader reaching need still has its window's far end).
 * Then, as budget allows and the rings have room, on towards `want`. Returns 1 when it stopped for lack of room.
 */
static int kf_analyse_to(struct str_seg *g, const struct str_src *src, int32_t need, int32_t want, int32_t budget,
                         float *scratch)
{
    uint32_t q = need < 0 ? 0 : (uint32_t)need << 8;
    int sets = src->stereo ? 2 : 1;
    for (;;) {
        int ok = g->kf.an >= src->len;
        if (!ok) {
            ok = 1;
            for (int s = 0; s < sets; s++)
                if (g->kf.last[s] <= q) ok = 0;
        }
        if (ok) break;
        kf_piece(g, src, KF_PIECE, scratch);
    }
    while (budget > 0 && g->kf.an < want && g->kf.an < src->len) {
        if (!kf_room(g, src))
            return 1;
        kf_piece(g, src, KF_PIECE, scratch);
        budget -= KF_PIECE;
    }
    return 0;
}

static void rd_load(struct str_seg *g, int s, struct str_kfrd *r)
{
    uint32_t M = *kcount(g, s);
    const struct str_kfset *k = &g->set[s];
    if (r->m + 1 >= M) {                                 /* past the last keyframe: hold */
        r->m = M - 1;
        r->len = 1e30f; r->inv = 0.0f; r->v0 = k->val[r->m & MASK]; r->dv = 0.0f;
        return;
    }
    uint32_t d = k->pos[(r->m + 1) & MASK] - k->pos[r->m & MASK];
    r->len = (float)d * FX_INV;
    r->inv = 256.0f / (float)d;
    r->v0 = k->val[r->m & MASK];
    r->dv = k->val[(r->m + 1) & MASK] - r->v0;
}

/* the largest m with pos[m] <= q, among the keyframes still in the ring */
static uint32_t kf_find(struct str_seg *g, int s, uint32_t q)
{
    uint32_t M = *kcount(g, s), lo = M > STR_KF_RING ? M - STR_KF_RING : 0, hi = M - 1;
    const uint32_t *pos = g->set[s].pos;
    while (lo < hi) {
        uint32_t mid = (lo + hi + 1) >> 1;
        if (pos[mid & MASK] <= q) lo = mid; else hi = mid - 1;
    }
    return lo;
}

static uint32_t fx_of(int32_t i, float f) { return i < 0 ? 0 : ((uint32_t)i << 8) + (uint32_t)(f * 256.0f); }

static void rd_seek(struct str_seg *g, int s, struct str_kfrd *r, int32_t i, float f)
{
    r->m = kf_find(g, s, fx_of(i, f));
    rd_load(g, s, r);
    uint32_t p = g->set[s].pos[r->m & MASK];
    r->u = (float)(i - (int32_t)(p >> 8)) + (f - (float)(p & 255u) * FX_INV);
    if (r->u < 0.0f) r->u = 0.0f;
}

static inline float rd_val(const struct str_kfrd *r)
{
    float t = r->u * r->inv;
    return r->v0 + r->dv * (t * t * (3.0f - 2.0f * t));
}

static inline __attribute__((always_inline)) void rd_adv(struct str_seg *g, int s, struct str_kfrd *r, float step)
{
    r->u += step;
    while (r->u >= r->len) { r->u -= r->len; r->m++; rd_load(g, s, r); }
}

static void ph_seek(struct str_seg *g, const struct str_src *src, struct str_kfph *p, int32_t i, float f)
{
    if (i < 0) { i = 0; f = 0.0f; }
    p->i = i; p->f = f;
    rd_seek(g, SL, &p->l, i, f);
    if (src->stereo) rd_seek(g, SR, &p->r, i, f);
}

static inline __attribute__((always_inline)) void ph_adv(struct str_seg *g, const struct str_src *src,
                                                          struct str_kfph *p, float step)
{
    p->f += step;
    int a = (int)p->f;
    p->i += a; p->f -= (float)a;
    rd_adv(g, SL, &p->l, step);
    if (src->stereo) rd_adv(g, SR, &p->r, step);
}

static float span_len(struct str_seg *g, int s, uint32_t m)
{
    uint32_t M = *kcount(g, s), e = m + KF_K;
    if (e > M - 1) e = M - 1;
    if (m > M - 1) m = M - 1;
    float L = (float)(g->set[s].pos[e & MASK] - g->set[s].pos[m & MASK]) * FX_INV;
    return L < KF_LMIN ? KF_LMIN : L > KF_LMAX ? KF_LMAX : L;
}

static void align_target(struct str_seg *g, int s, const struct str_kfrd *pm, int32_t *ti, float *tf)
{
    const uint32_t *pos = g->set[s].pos;
    const float *v = g->set[s].val;
    uint32_t M = *kcount(g, s), lo = M > STR_KF_RING ? M - STR_KF_RING + 1 : 1;
    int64_t jp = pm->m;
    if (M < 5 || jp < (int64_t)lo || jp + 2 >= (int64_t)M) return;
#define V(j) v[(uint32_t)(j) & MASK]
#define P(j) pos[(uint32_t)(j) & MASK]
    float tp = pm->u * pm->inv;
    int pol = V(jp + 1) > V(jp);
    float amp = 0.25f * (fabsf_(V(jp - 1)) + fabsf_(V(jp)) + fabsf_(V(jp + 1)) + fabsf_(V(jp + 2))) + 1e-6f;
    uint32_t tq = fx_of(*ti, *tf);
    int64_t jx = kf_find(g, s, tq);
    float best = 1e30f, boff = 0.0f;
    int found = 0;
    for (int64_t j = jx - KF_RADIUS; j <= jx + KF_RADIUS; j++) {
        if (j < (int64_t)lo || j + 2 >= (int64_t)M) continue;
        if ((V(j + 1) > V(j)) != pol) continue;
        float lenj = (float)(P(j + 1) - P(j)) * FX_INV;
        float off = (float)(int32_t)(P(j) - tq) * FX_INV + tp * lenj;
        if (fabsf_(off) > KF_MAXSHIFT) continue;
        float e = 0.0f;
        for (int q = -1; q <= 2; q++) e += fabsf_(V(j + q) - V(jp + q));
        for (int q = -1; q <= 1; q++) {
            float a = (float)(P(j + q + 1) - P(j + q)), b = (float)(P(jp + q + 1) - P(jp + q));
            e += amp * fabsf_(a - b) / (a + b);
        }
        e += 0.25f * amp * fabsf_(off) / KF_MAXSHIFT;
        if (e < best) { best = e; boff = off; found = 1; }
    }
#undef V
#undef P
    if (found) {
        float t = *tf + boff;
        int32_t fl = (int32_t)t - (t < 0.0f && (float)(int32_t)t != t);
        *ti += fl; *tf = t - (float)fl;
    }
}

static void kf_render(struct str_seg *g, const struct str_src *src, float rate, float ref_rate, float *ol, float *orr,
                      int n, float *scratch)
{
    const int sm = ST;
    float maxr = rate > ref_rate ? rate : ref_rate;
    if (g->fresh) {
        float x[4], xr[4];
        int sets = src->stereo ? 2 : 1;
        src->fetch(src, x, src->stereo ? xr : 0, 3, g->start - 1);
        for (int s = 0; s < sets; s++) {
            const float *v = s == SL ? x : xr;
            float a = v[0], b = v[1], c = v[2];
            *kcount(g, s) = 0;
            g->kf.last[s] = 0;
            kf_put(g, s, (uint32_t)g->start << 8, b);     /* the anchor */
            g->kf.last_n[s] = g->start;
            g->kf.dprev[s] = 0.5f * (c - a);
            g->kf.sprev[s] = sgnf(g->kf.dprev[s]);
        }
        g->kf.an = g->start + 1;
        kf_analyse_to(g, src, g->start + (int32_t)((float)n * maxr) + 4, 0, 0, scratch);
        g->kf.cur = 0;
        ph_seek(g, src, &g->kf.ph[0], g->start, 0.0f);
        copy_words(&g->kf.ph[1], &g->kf.ph[0], sizeof g->kf.ph[0]);   /* no memcpy in bank 2 */
        g->kf.ref_i = g->start;
        g->kf.ref_f = 0.0f;
        rd_seek(g, sm, &g->kf.ref, g->start, 0.0f);
        g->splicing = 0;
        g->fresh = 0;
    }
    struct str_kfph *play = &g->kf.ph[g->kf.cur], *temp = &g->kf.ph[g->kf.cur ^ 1];
    /* keep the analysis ahead of every head: the must-have part, then catch up towards KF_LOOK within a budget */
    int32_t head = play->i > g->kf.ref_i ? play->i : g->kf.ref_i;
    if (g->splicing && temp->i > head) head = temp->i;
    /* the reference never passes the slice's end by more than the hand-over (256 frames x ref_rate): no further */
    int32_t want = head + KF_LOOK, reach = g->start + (int32_t)(g->span + 256.0f * ref_rate) + KF_GAP;
    if (want > reach) want = reach;
    int full = kf_analyse_to(g, src, head + (int32_t)((float)n * maxr) + 4, want, KF_BUDGET * n, scratch);
    int ahead = full || g->kf.an >= src->len || g->kf.an >= want || g->kf.an >= head + KF_LOOK / 2;  /* enough to plan a splice */

    int o = 0;
    while (o < n) {
        /* the reference head, brought up to this frame (it only matters to the leash check) */
        float r = ref_rate * (float)(g->t + (uint32_t)o);
        int32_t ri = g->start + (int32_t)r;
        float rf = r - (float)(int32_t)r;
        rd_adv(g, sm, &g->kf.ref, (float)(ri - g->kf.ref_i) + (rf - g->kf.ref_f));
        g->kf.ref_i = ri;
        g->kf.ref_f = rf;
        int run = n - o < KF_CHECK ? n - o : KF_CHECK;
        if (!g->splicing && ahead) {                     /* the leash, every KF_CHECK frames */
            float dist = (float)(play->i - ri) + (play->f - rf);
            int64_t d = (int64_t)play->l.m - (int64_t)g->kf.ref.m;
            if (d < 0) d = -d;
            if (d > KF_K || fabsf_(dist) > KF_DMAX) {
                int32_t ti = ri;
                float tf = rf;
                align_target(g, sm, &play->l, &ti, &tf);
                ph_seek(g, src, temp, ti, tf);
                float L = span_len(g, sm, temp->l.m);
                g->kf.w = 0.0f;
                g->kf.winc = 1.0f / L;
                g->splicing = 1;
            }
        }
        float *dl = ol + o, *dr = orr ? orr + o : 0;
        if (g->splicing) {
            float w = g->kf.w, winc = g->kf.winc;
            int k = 0;
            for (; k < run && w < 1.0f; k++) {
                float pl = rd_val(&play->l), pr = src->stereo ? rd_val(&play->r) : pl;
                float tl = rd_val(&temp->l), tr = src->stereo ? rd_val(&temp->r) : tl;
                dl[k] = pl + (tl - pl) * w;
                if (dr) dr[k] = pr + (tr - pr) * w;
                w += winc;
                ph_adv(g, src, temp, rate);
                ph_adv(g, src, play, rate);
            }
            g->kf.w = w;
            if (w >= 1.0f) {                             /* lines 19-21: the temporary head takes over */
                g->kf.cur ^= 1;
                play = &g->kf.ph[g->kf.cur];
                temp = &g->kf.ph[g->kf.cur ^ 1];
                g->splicing = 0;
            }
            run = k;
        } else {
            for (int k = 0; k < run; k++) {
                dl[k] = rd_val(&play->l);
                if (dr) dr[k] = src->stereo ? rd_val(&play->r) : dl[k];
                ph_adv(g, src, play, rate);
            }
        }
        o += run;
    }
    g->t += (uint32_t)n;
}

/* ---------------------------------------------------------------- */

int32_t str_render(struct str_seg *g, int model, const struct str_src *src, int32_t start, float span, float rate,
                   float ref_rate, float *out_l, float *out_r, int n, float *scratch)
{
    if (rate > RATE_MAX) rate = RATE_MAX;
    if (ref_rate > RATE_MAX) ref_rate = RATE_MAX;
    if (g->magic != STR_MAGIC || g->start != start || g->model != (uint8_t)model) {
        g->magic = STR_MAGIC;
        g->start = start;
        g->span = span;
        g->model = (uint8_t)model;
        g->stereo = (uint8_t)src->stereo;
        g->t = 0;
        g->splicing = 0;
        g->fresh = 1;
    }
    if (model == STR_KEYFRAME) {
        kf_render(g, src, rate, ref_rate, out_l, out_r, n, scratch);
        return g->kf.ph[g->kf.cur].i;
    }
    grain_render(g, model, src, rate, ref_rate, out_l, out_r, n, scratch);
    return g->cur.i;
}

#ifndef STR_HOST
/* ---------------------------------------------------------------- firmware: the clip reader's side (stretch.c) */

#define FN(addr) ((addr) | 1u)
typedef int (*src_int_fn)(void *src);
typedef void (*fetch_fn)(void *src, float *dst, int n, int32_t pos, int zero);
typedef void (*fetch2_fn)(void *src, float *left, float *right, int n, int32_t pos);
typedef float *(*buf_mono_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);
#define fw_src_len    ((src_int_fn)FN(0x080636f0))
#define fw_src_stereo ((src_int_fn)FN(0x08063790))
#define fw_fetch      ((fetch_fn)FN(0x08063634))
#define fw_fetch2     ((fetch2_fn)FN(0x08063608))
#define fw_buf_mono   ((buf_mono_fn)FN(0x0804d934))
#define fw_buf_pair   ((buf_chans_fn)FN(0x0804da0c))

/* class B pad (NOTES, TIME STRETCH; research stretch_re.md) */
#define PAD_SOURCE   0x24
#define PAD_SEG      0x30         /* + i x 0x70, i = 0..3 */
#define PAD_SYNC_ON  0x1f5        /* u8 */
#define PAD_SPS      0x1fc        /* f32: source frames per slice */
#define PAD_SLOT     0x204        /* f32: a slice's length on the grid, 48 kHz frames */
#define PAD_DIVS     0x210        /* s32: slices (> 1 = stretching) */
#define PAD_STEP     0x220        /* s32: Sync step in ticks; 0xf0000 = "Slice" (markers) */
#define PAD_SLICER   0x254        /* u8 */
#define PAD_SEL_S    0x238        /* clipsel.c: the selection's start / end (stock: 0 / the file length) */
#define PAD_SEL_E    0x23c
#define SEG_ACTIVE   0x00
#define SEG_POS      0x08         /* s64 */
#define SEG_END      0x10         /* s64, 0 = none (the last slice has one: stock plays it at its own speed) */
#define SEG_SLICE    0x34

#define DWT_CYCCNT (*(volatile uint32_t *)0xe0001004u)   /* cpu.c turns it on at boot, every build */

static void fw_src_fetch(const struct str_src *s, float *l, float *r, int n, int32_t pos)
{
    uint32_t t0 = DWT_CYCCNT;
    int lead = pos < s->lo ? s->lo - pos : 0;
    if (lead > n) lead = n;
    int32_t end = pos + n, tail = end > s->len ? end - (pos > s->len ? pos : s->len) : 0;
    if (tail > n - lead) tail = n - lead;
    int mid = n - lead - tail;
    for (int k = 0; k < lead; k++) { l[k] = 0.0f; if (r) r[k] = 0.0f; }
    for (int k = n - tail; k < n; k++) { l[k] = 0.0f; if (r) r[k] = 0.0f; }
    if (mid > 0) {
        if (r) fw_fetch2(s->obj, l + lead, r + lead, mid, pos + lead);
        else   fw_fetch(s->obj, l + lead, mid, pos + lead, 0);
    }
    if (s->prof) {
        s->prof[0] += DWT_CYCCNT - t0;
        s->prof[1] += (uint32_t)n;
    }
}

/* A folded marker slice (stretch.c mk_spawn) that falls back to stock past its source end: silence, as stock's own
   tail was, never the next slice's audio. Bookkeeping as stock's reader. */
static int str_quiet(void *out, void *obj, float rate, int n, int *used, float *frac, void **result)
{
    float *l, *r = 0;
    if (fw_src_stereo(obj)) fw_buf_pair(out, &l, &r);
    else l = fw_buf_mono(out);
    for (int k = 0; k < n; k++) { l[k] = 0.0f; if (r) r[k] = 0.0f; }
    float p = *frac + (float)n * rate;
    int u = (int)p;
    *used = u;
    *frac = p - (float)u;
    *result = out;
    return 1;
}

/*
 * One read of a clip segment through a model. Returns 1 = done (out, used, frac, result written as stock's reader
 * would), -1 = not ours: stock reads it. mem = this file's SDRAM area (stretch.h, struct str_bank).
 * Two kinds of slice: a Clip pad's grid slice (Sync on, n slices: sized from pad+0x1fc / 0x204), and a marker slice
 * (Slicer with Sync on, Clip on Sync = Slice: sized by stock at the spawn, recorded by stretch.c mk_spawn).
 */
int str_clip(uint8_t *mem, uint8_t *pad, int model, float rate, int32_t pos, int n, int *used, float *frac, void *out,
             void **result)
{
    struct str_bank *b = (struct str_bank *)mem;
    if (model <= STR_STOCK || model >= STR_MODELS || !(rate > 0.0f) || n <= 0)
        return -1;
    void *obj = *(void **)(pad + PAD_SOURCE);
    if (!obj)
        return -1;
    /* the segment stock is reading: frac is its seg + 0x1c (BL @0x08066622; SLICER_PLAYBACK_RE.md 2) */
    uint8_t *seg = (uint8_t *)frac - 0x1c;
    int32_t d = (int32_t)(seg - (pad + PAD_SEG));
    const struct str_mark *m = 0;
    if (d >= 0 && d < 4 * 0x70 && d % 0x70 == 0) {
        uint32_t id = *(const uint32_t *)(pad + 0x18);
        const struct str_mark *c = &b->mk[((id >> 8) & 3) * 4 + (id & 3)][d / 0x70];
        if (c->kind != MK_NONE)
            m = c;
    }
    int32_t len = fw_src_len(obj), lo, hi, start;
    int slice;
    float span, ref;
    if (m) {
        if (*(int64_t *)(seg + SEG_END) != 0)
            return -1;
        slice = *(int32_t *)(seg + SEG_SLICE);
        start = m->start;
        span = (float)m->span;
        ref = span / (float)m->slot;
        lo = 0;
        hi = len;
        if (m->kind == MK_CUT) {                         /* PlayThru off: nothing past the slice, as stock */
            lo = start;
            hi = start + m->span < len ? start + m->span : len;
        }
    } else {
        if (!pad[PAD_SYNC_ON] || pad[PAD_SLICER] || *(int32_t *)(pad + PAD_DIVS) <= 1 ||
            *(int32_t *)(pad + PAD_STEP) == 0xf0000)
            return -1;                                   /* not stretching, or a marker slice we did not record: stock */
        float sps = *(float *)(pad + PAD_SPS), slot = *(float *)(pad + PAD_SLOT);
        if (!(sps > 1.0f) || !(slot > 1.0f))
            return -1;
        /* Every pad sample streams from the card through 8192-frame cached blocks (stretch_re.md 8): a read that hits
           a block not yet loaded gets zeros and queues it, exactly as stock's own reads do. The models read forward
           near the slice's reference head (Smooth +-768 frames, Keyframe's analysis up to 2400 ahead; Keyframe's
           splices replay keyframes, not the source), and every read queues the block it ends in and the next two. */
        seg = 0;
        for (int i = 0; i < 4; i++) {
            uint8_t *s = pad + PAD_SEG + i * 0x70;
            if (s[SEG_ACTIVE] && *(int32_t *)(s + SEG_POS) == pos) { seg = s; break; }
        }
        if (!seg || *(int64_t *)(seg + SEG_END) != 0)
            return -1;
        slice = *(int32_t *)(seg + SEG_SLICE);
        /* the clip's selection (clipsel.c leaves it in 0x238 / 0x23c; stock's 0 / file length when there is none) */
        lo = *(int32_t *)(pad + PAD_SEL_S);
        hi = *(int32_t *)(pad + PAD_SEL_E);
        if (lo < 0 || hi > len || hi - lo < 2) { lo = 0; hi = len; }
        start = lo + (int32_t)((float)slice * sps + 0.5f);
        span = sps;
        ref = sps / slot;
    }
    int quiet = m && m->folded && pos >= m->start + m->span;   /* a fallback here plays silence, not the next slice */
    b->seq++;
    /* this segment's slot: the one that has it, else the stalest free one */
    int k = -1, oldest = -1;
    uint32_t age = 0;
    for (int i = 0; i < STR_SLOTS; i++) {
        struct str_own *o = &b->own[i];
        uint32_t a = o->seg ? b->seq - o->seq : 0xffffffffu;   /* never used = the stalest */
        if (o->seg == seg && a < STR_STALE) { k = i; break; }
        if (a >= STR_STALE && a >= age) { age = a; oldest = i; }
    }
    struct str_own *o;
    if (k >= 0 && b->own[k].next == pos && b->own[k].slice == slice) {
        o = &b->own[k];
        if (o->model != (uint8_t)model)
            o->stock = 1;                                /* another model picked mid-slice: stock until the next one */
        if (o->stock) {
            o->next = pos + (int32_t)(*frac + (float)n * rate);
            o->seq = b->seq;
            return quiet ? str_quiet(out, obj, rate, n, used, frac, result) : -1;
        }
    } else {
        if (k < 0) k = oldest;
        if (k < 0)
            return quiet ? str_quiet(out, obj, rate, n, used, frac, result) : -1;   /* every slot busy: stock */
        o = &b->own[k];
        o->seg = seg;
        o->slice = slice;
        o->model = (uint8_t)model;
        o->stock = (uint8_t)(pos - start > 2 || start - pos > 2);   /* joined mid-slice (model switched on): stock
                                                                       until the next slice */
        b->st[k].magic = 0;
        o->start = pos;
        if (o->stock) {
            o->next = pos + (int32_t)(*frac + (float)n * rate);
            o->seq = b->seq;
            return quiet ? str_quiet(out, obj, rate, n, used, frac, result) : -1;
        }
    }
    o->seq = b->seq;
    uint32_t t0 = DWT_CYCCNT;
    struct str_src src = { obj, lo, hi, fw_src_stereo(obj), fw_src_fetch, b->prof };
    float *ol, *orr = 0;
    if (src.stereo) fw_buf_pair(out, &ol, &orr);
    else ol = fw_buf_mono(out);
    str_render(&b->st[k], model, &src, o->start, span, rate, ref, ol, orr, n, b->scratch);
    b->prof[2] += DWT_CYCCNT - t0;
    b->prof[3] += (uint32_t)n;
    float p = *frac + (float)n * rate;                   /* the source stock would have used: same bookkeeping */
    int u = (int)p;
    *used = u;
    *frac = p - (float)u;
    o->next = pos + u;
    *result = out;
    return 1;
}
#endif
