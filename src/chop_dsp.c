/*
 * ChopShop's whole-file beat scan (flash bank 2; also built for the Mac): for every beat on a detected grid, how loud
 * the music is just after it and how hard the beat hits (the rise over the half-window before it). chop.c picks
 * Find / Random chops from these. A beat at a time from the card (CHOP_WIN frames around it), CHOP_PER beats a block,
 * so a 4-minute track at 100 BPM (~400 beats) takes ~100 blocks (~0.5 s). CPU: CHOP_PER x 1024 x ~6 instructions
 * per block (~25 instructions per frame, ~0.25 % while it runs); nothing otherwise.
 *
 * Calls out of bank 2: only job->fetch (stock's sample fetch, passed in).
 */
#include <stdint.h>
#include "chop.h"

#ifndef STR_HOST
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")
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

void chop_scan_start(struct chop_job *j, int pad, void *obj, int32_t len, int stereo, float anchor, float fpb)
{
    j->pad = pad;
    j->obj = obj;
    j->len = len;
    j->stereo = stereo;
    j->anchor = anchor;
    j->fpb = fpb;
    j->idx = 0;
    j->misses = 0;
    int n = 0;
    if (fpb >= 64.0f && len > 0 && anchor >= 0.0f)
        while (n < CHOP_BEATS && anchor + (float)n * fpb < (float)len)
            n++;
    j->n = n;
    j->state = n ? CHOP_SCAN : CHOP_FAILED;
}

int chop_scan_step(struct chop_job *j, float *scratch)
{
    if (j->state != CHOP_SCAN)
        return j->state;
    float *l = scratch, *r = scratch + CHOP_WIN;
    for (int c = 0; c < CHOP_PER && j->idx < j->n; c++) {
        int32_t b = (int32_t)(j->anchor + (float)j->idx * j->fpb + 0.5f), from = b - CHOP_WIN / 2;
        if (from < 0) from = 0;
        int count = b + CHOP_WIN / 2 > j->len ? j->len - from : b + CHOP_WIN / 2 - from;
        if (count < 64) { j->level[j->idx] = 0.0f; j->hit[j->idx] = 0.0f; j->idx++; continue; }
        if (!j->fetch(j, l, j->stereo ? r : 0, count, from))
            return j->state;                             /* not loaded yet: the same beat next block */
        float pre = 0.0f, post = 0.0f;
        int npre = 0, npost = 0;
        for (int k = 0; k < count; k++) {
            float a = l[k], v = j->stereo ? r[k] : a, e = a * a + v * v;
            if (from + k < b) { pre += e; npre++; } else { post += e; npost++; }
        }
        float lp = npre ? sqrt_(pre / (float)(2 * npre)) : 0.0f, lq = npost ? sqrt_(post / (float)(2 * npost)) : 0.0f;
        j->level[j->idx] = lq;
        j->hit[j->idx] = lq > lp ? lq - lp : 0.0f;
        j->idx++;
    }
    if (j->idx >= j->n)
        j->state = CHOP_DONE;
    return j->state;
}

#ifndef STR_HOST
#define FN(addr) ((addr) | 1u)
typedef int (*fetch_fn)(void *src, float *dst, int n, int32_t pos, int zero);
typedef int (*fetch2_fn)(void *src, float *left, float *right, int n, int32_t pos);
#define fw_fetch  ((fetch_fn)FN(0x08063634))
#define fw_fetch2 ((fetch2_fn)FN(0x08063608))

int chop_fw_fetch(struct chop_job *j, float *l, float *r, int n, int32_t pos)
{
    if (++j->misses > 4000) {                               /* ~20 s of a block that never arrives: give up */
        j->state = CHOP_FAILED;
        return 0;
    }
    int ok = r ? fw_fetch2(j->obj, l, r, n, pos) : fw_fetch(j->obj, l, n, pos, 0);
    if (ok)
        j->misses = 0;
    return ok;
}
#endif
