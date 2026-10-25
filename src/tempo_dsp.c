/*
 * Clip tempo detection: the BPM and where beat one falls, from the audio (clipsel.c asks for it when a Clip pad with no
 * selection opens on the Waveform screen). Flash bank 2; also built for the Mac (host/tempo_host.c).
 *
 * Ported from Chop Shop's detector (the author's own Move module, ~/projects/schwung-chopshop src/dsp/analysis.h,
 * MIT): onset envelope = rise in RMS per 256-frame hop over a 512-frame window, whitened against a ~1 s moving
 * average; a comb of pulses scored at its best phase for each candidate tempo (coverage^1.5 x strength x fill x a
 * log-normal prior round 120); a 0.5-BPM sweep 60..200, the metrical relatives of the best eight, whole-beat loop
 * lengths (whole bars favoured), a 0.02-BPM refine, and a loop snap only when the length really is whole beats.
 * Changed for the Blackbox: the file's own rate (not 44.1 kHz), the first TEMPO_SECS seconds at most, and the work cut
 * into steps so the audio task does a little per block: reading TEMPO_READ frames, or TEMPO_CANDS candidates.
 *
 * Calls out of bank 2: only job->fetch (stock's sample fetch, passed in; 0 = that part of the file is not loaded yet,
 * try again next block).
 */
#include <stdint.h>
#include "tempo.h"

#ifndef STR_HOST
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")
#endif

#define HOP     256
#define BPM_LO  60.0f
#define BPM_HI  200.0f
#define BPM_MIN 40.0f
#define BPM_MAX 400.0f
#ifndef LOOP_SECS
#define LOOP_SECS  20.0f         /* a file shorter than this is taken for a loop: whole bars only (his loops at 123:
                                    the comb alone gave 72 / 104 / 129 / 161 on 2-bar loops; host/tempo_check.py) */
#endif
#ifndef PRIOR_LOOP
#define PRIOR_LOOP 0.5f          /* octaves: the prior when choosing a loop's bar count (0.8 picked half tempo on 3 of his 7 loops) */
#endif
#ifndef WHOLE_BAR
#define WHOLE_BAR  1.06f         /* Chop Shop's edge for a whole-bar loop length */
#endif
#ifndef WHOLE_HALF
#define WHOLE_HALF 1.03f
#endif

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

static float log2_(float x)                     /* error ~0.005: the prior only */
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xff) - 128);
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;
    float m = v.f;
    return e + (-0.34484843f * m + 2.02466578f) * m - 0.67487759f;
}

static float exp2_(float x)
{
    if (x < -30.0f) return 0.0f;
    if (x > 30.0f) x = 30.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i;
    float p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

static float floor_(float x) { int i = (int)x; return (float)(i - ((float)i > x)); }
static float fabs_(float x) { return x < 0.0f ? -x : x; }

/* How well a metronome at bpm explains the onsets (Chop Shop cs_score_tempo). */
static float score(const struct tempo_job *j, float bpm, float *phase_out)
{
    const float *flux = j->flux;
    int n = j->n_env;
    float period = 60.0f * j->fps / bpm;
    if (period < 2.0f || period > (float)n || (float)n / period < 3.0f || j->total <= 0.0f)
        return 0.0f;
    int steps = (int)period;
    if (steps > 32) steps = 32;
    if (steps < 1) steps = 1;
    float best = 0.0f, best_phase = 0.0f;
    for (int ps = 0; ps < steps; ps++) {
        float phase = (float)ps * period / (float)steps, sum = 0.0f;
        int cnt = 0, empty = 0;
        for (int i = 0; ; i++) {
            int idx = (int)(phase + (float)i * period + 0.5f);
            if (idx >= n) break;
            float v = flux[idx];
            if (idx > 0 && flux[idx - 1] > v) v = flux[idx - 1];
            if (idx + 1 < n && flux[idx + 1] > v) v = flux[idx + 1];
            sum += v;
            cnt++;
            if (v <= 1e-6f) empty++;
        }
        if (cnt < 3) continue;
        float strength = sum / (float)cnt, coverage = sum / j->total;
        if (coverage > 1.0f) coverage = 1.0f;
        float fill = 1.0f - (float)empty / (float)cnt;
        float sc = coverage * sqrt_(coverage) * strength * fill;
        if (sc > best) { best = sc; best_phase = phase; }
    }
    if (phase_out) *phase_out = best_phase;
    float lg = log2_(bpm / 120.0f) / (j->loop ? PRIOR_LOOP : 0.8f);
    return best * exp2_(-0.5f * lg * lg * 1.4426950f);
}

void tempo_start(struct tempo_job *j, int pad, void *obj, int32_t len, uint32_t frate, int stereo)
{
    j->pad = pad;
    j->obj = obj;
    j->len = len;
    j->frate = frate ? frate : 48000u;
    j->stereo = stereo;
    int32_t cap = (int32_t)(TEMPO_SECS * (float)j->frate);
    j->end = len < cap ? len : cap;
    if (j->end > (int32_t)(TEMPO_ENV + 1) * HOP) j->end = (int32_t)(TEMPO_ENV + 1) * HOP;
    j->pos = 0;
    j->n_env = 0;
    j->chunk_prev = -1.0f;
    j->rms_prev = 0.0f;
    j->fps = (float)j->frate / (float)HOP;
    j->bpm = 0.0f;
    j->phase = 0.0f;
    j->state = j->end >= (int32_t)j->frate ? TEMPO_READ_AUDIO : TEMPO_FAILED;   /* under a second: nothing to find */
}

static void consider(struct tempo_job *j, float b, float bonus)
{
    if (b < BPM_LO || b > BPM_HI) return;
    float sc = score(j, b, 0) * bonus;
    if (sc > j->best_score) { j->best_score = sc; j->best_bpm = b; }
}

/* One block's worth. scratch: 2 x TEMPO_READ floats. Returns the state. */
int tempo_step(struct tempo_job *j, float *scratch)
{
    switch (j->state) {
    case TEMPO_READ_AUDIO: {
        int32_t n = j->end - j->pos;
        if (n > TEMPO_READ) n = TEMPO_READ;
        n -= n % HOP;
        if (n <= 0) { j->state = TEMPO_WHITEN; break; }
        float *l = scratch, *r = scratch + TEMPO_READ;
        if (!j->fetch(j, l, j->stereo ? r : 0, n, j->pos))
            break;                                          /* not loaded yet: the read queued it, again next block */
        for (int c = 0; c < n; c += HOP) {
            float e = 0.0f;
            for (int k = 0; k < HOP; k++) {
                float a = l[c + k], b = j->stereo ? r[c + k] : a;
                e += a * a + b * b;
            }
            if (j->chunk_prev >= 0.0f && j->n_env < TEMPO_ENV) {
                float rms = sqrt_((j->chunk_prev + e) / (2.0f * HOP * 2.0f));
                j->env[j->n_env] = j->n_env > 0 && rms > j->rms_prev ? rms - j->rms_prev : 0.0f;
                j->rms_prev = rms;
                j->n_env++;
            }
            j->chunk_prev = e;
        }
        j->pos += n;
        break;
    }
    case TEMPO_WHITEN: {
        int n = j->n_env, w = (int)j->fps;
        if (n < 32) { j->state = TEMPO_FAILED; break; }
        if (w < 4) w = 4;
        float sum = 0.0f;
        int lo = 0, hi = 0;
        j->total = 0.0f;
        for (int i = 0; i < n; i++) {
            int a = i - w / 2, b = i + w / 2;
            if (a < 0) a = 0;
            if (b > n) b = n;
            while (hi < b) sum += j->env[hi++];
            while (lo < a) sum -= j->env[lo++];
            float mean = sum / (float)(b - a);
            j->flux[i] = j->env[i] > mean ? j->env[i] - mean : 0.0f;
            j->total += j->flux[i];
        }
        if (j->total <= 0.0f) { j->state = TEMPO_FAILED; break; }
        j->n_top = 0;
        j->cand = BPM_LO;
        j->state = TEMPO_SWEEP;
        break;
    }
    case TEMPO_SWEEP:
        for (int c = 0; c < TEMPO_CANDS && j->cand <= BPM_HI; c++, j->cand += 0.5f) {
            float sc = score(j, j->cand, 0);
            if (sc <= 0.0f) continue;
            if (j->n_top < 8) { j->top_bpm[j->n_top] = j->cand; j->top_score[j->n_top] = sc; j->n_top++; }
            else {
                int worst = 0;
                for (int i = 1; i < 8; i++) if (j->top_score[i] < j->top_score[worst]) worst = i;
                if (sc > j->top_score[worst]) { j->top_bpm[worst] = j->cand; j->top_score[worst] = sc; }
            }
        }
        if (j->cand > BPM_HI) {
            if (!j->n_top) { j->state = TEMPO_FAILED; break; }
            j->best_bpm = 0.0f;
            j->best_score = 0.0f;
            j->idx = 0;
            j->state = TEMPO_RELATIVES;
        }
        break;
    case TEMPO_RELATIVES: {
        static const float ratios[7] = {1.0f / 3, 0.5f, 2.0f / 3, 1.0f, 1.5f, 2.0f, 3.0f};
        for (int c = 0; c < TEMPO_CANDS && j->idx < j->n_top * 7; c++, j->idx++)
            consider(j, j->top_bpm[j->idx / 7] * ratios[j->idx % 7], 1.0f);
        if (j->idx >= j->n_top * 7) {
            j->idx = 1;
            j->cand = 0.0f;
            j->loop = j->end == j->len && (float)j->len < LOOP_SECS * (float)j->frate;
            if (j->loop) { j->best_bpm = 0.0f; j->best_score = 0.0f; }   /* a short file is a loop: whole bars only */
            j->state = j->end == j->len ? TEMPO_WHOLE : TEMPO_REFINE;
        }
        break;
    }
    case TEMPO_WHOLE: {                                     /* the whole file is a whole number of beats? (a loop) */
        float dur = (float)j->len / (float)j->frate;
        for (int c = 0; c < TEMPO_CANDS && j->idx <= 512; j->idx++) {
            float b = (float)j->idx * 60.0f / dur;
            if (b < BPM_LO) continue;
            if (b > BPM_HI) { j->idx = 513; break; }
            if (j->loop ? (j->idx & (j->idx - 1)) == 0 && j->idx >= 4 : 1)   /* loops: 1, 2, 4, 8.. bars */
                consider(j, b, j->idx % 4 == 0 ? WHOLE_BAR : j->idx % 2 == 0 ? WHOLE_HALF : 1.0f);
            c++;
        }
        if (j->idx > 512) {
            if (j->loop && j->best_bpm <= 0.0f) {         /* no whole bar in range: back to the open search */
                j->loop = 0;
                j->idx = 0;
                j->best_score = 0.0f;
                for (int i = 0; i < j->n_top; i++) consider(j, j->top_bpm[i], 1.0f);
            }
            j->state = j->loop ? TEMPO_FINISH : TEMPO_REFINE;   /* a whole-bar loop tempo is exact already */
            j->cand = 0.0f;
        }
        break;
    }
    case TEMPO_REFINE: {
        if (j->best_bpm <= 0.0f) { j->state = TEMPO_FAILED; break; }
        if (j->cand == 0.0f) { j->cand = j->best_bpm - 1.0f; j->refine_hi = j->best_bpm + 1.0f; }
        for (int c = 0; c < TEMPO_CANDS && j->cand <= j->refine_hi; c++, j->cand += 0.02f)
            consider(j, j->cand, 1.0f);
        if (j->cand > j->refine_hi) j->state = TEMPO_FINISH;
        break;
    }
    case TEMPO_FINISH: {
        float best = j->best_bpm;
        if (j->end == j->len) {                             /* loop snap, earned (Chop Shop step 4) */
            float dur = (float)j->len / (float)j->frate, beats = dur * best / 60.0f;
            float nb = floor_(beats + 0.5f), err = nb > 0.0f ? fabs_(beats - nb) / nb : 1.0f;
            int bars = ((int)nb % 4) == 0;
            float gate = bars ? (0.10f / nb > 0.004f ? 0.10f / nb : 0.004f) : 0.0015f;
            if (nb >= 4.0f && err < gate) {
                float snapped = nb * 60.0f / dur;
                if (snapped >= BPM_MIN && snapped <= BPM_MAX) best = snapped;
            }
        }
        float ph = 0.0f;
        score(j, best, &ph);
        j->bpm = best;
        j->phase = ph * (float)HOP;
        j->state = best >= BPM_MIN && best <= BPM_MAX ? TEMPO_DONE : TEMPO_FAILED;
        break;
    }
    default:
        break;
    }
    return j->state;
}

#ifndef STR_HOST
/* the firmware's fetch for a job (clipsel.c / stretch.c put its address in job->fetch): stock's sample read, whose
   result is the streamer's (1 = read, 0 = a block not loaded yet, which the read has just asked for) */
#define FN(addr) ((addr) | 1u)
typedef int (*fetch_fn)(void *src, float *dst, int n, int32_t pos, int zero);
typedef int (*fetch2_fn)(void *src, float *left, float *right, int n, int32_t pos);
#define fw_fetch  ((fetch_fn)FN(0x08063634))
#define fw_fetch2 ((fetch2_fn)FN(0x08063608))

int tempo_fw_fetch(struct tempo_job *j, float *l, float *r, int n, int32_t pos)
{
    if (++j->misses > 2000) {                               /* ~10 s of a block that never arrives: give up */
        j->state = TEMPO_FAILED;
        return 0;
    }
    int ok = r ? fw_fetch2(j->obj, l, r, n, pos) : fw_fetch(j->obj, l, n, pos, 0);
    if (ok)
        j->misses = 0;
    return ok;
}
#endif
