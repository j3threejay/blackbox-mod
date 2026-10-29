/*
 * ChopShop's whole-file attack scan (flash bank 2; also built for the Mac): every hit in the file, wherever it falls
 * (chop.h: the method). chop.c snaps the beat-grid chops onto these and picks Find / Random chops from them.
 * ON_PER x ON_CHUNK frames an audio block (128 frames, 375 a second) from the card: 16x real time, a 2-minute file in
 * ~7.5 s; chop.c stops it early for grid chops (only as far as the last of at most 128 points). CPU while it runs:
 * ~40k instructions a block (~19.7 a frame scanned, emulator count 10-27: 316 per output frame, ~3.1 %) + stock's
 * fetch of 2048 frames (not counted); nothing otherwise. 4096 frames a block measured ~630 per output frame (~6 %).
 *
 * Calls out of bank 2: only job->fetch (stock's sample fetch, passed in).
 */
#include <stdint.h>
#include "chop.h"

#ifndef STR_HOST
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")
#endif

void chop_scan_start(struct chop_job *j, int pad, void *obj, int32_t len, int stereo)
{
    j->state = CHOP_IDLE;                                /* the audio task may step a running scan mid-way: park it */
    __asm__ volatile("" ::: "memory");
    j->pad = pad;
    j->obj = obj;
    j->len = len;
    j->stereo = stereo;
    j->n = 0;
    j->next = 0;
    j->blocks = 0;
    j->misses = 0;
    j->pl = j->pr = j->dl = j->dr = 0.0f;
    j->acc = j->pacc = 0.0f;
    for (int i = 0; i < ON_RING; i++)
        j->e[i] = j->pe[i] = j->rise[i] = 0.0f;                     /* before the file: silence, no rise */
    for (int i = 0; i < ON_RING * (ON_H / ON_SUB); i++)
        j->sub[i] = 0.0f;
    j->state = obj && len >= ON_H * 4 ? CHOP_SCAN : CHOP_FAILED;
}

#define RM (ON_RING - 1)
#define SUBS (ON_H / ON_SUB)

/* keep a hit: append, or replace the weakest kept one if this one rises more */
static void keep(struct chop_job *j, int32_t at, float score, float level)
{
    int k = j->n;
    if (k >= ON_MAX) {
        k = 0;
        for (int i = 1; i < ON_MAX; i++)
            if (j->score[i] < j->score[k]) k = i;
        if (j->score[k] >= score)
            return;
    } else {
        j->n++;
    }
    j->at[k] = at;
    j->score[k] = score;
    j->level[k] = level;
}

/* block b's energy is in: its rise (block c = b - ON_R + 1 starts the "after" side), then whether block
   d = c - ON_P is a hit (its rise the largest within +-ON_P). Before the file start counts as silence (ring zeros), so
   a hit in the first blocks is found too. */
static void block_done(struct chop_job *j, int32_t b)
{
    int32_t c = b - ON_R + 1;
    if (c >= 1) {
        float before = 0.0f, after = 0.0f;
        for (int k = 0; k < ON_R; k++) {
            before += j->e[(c - 1 - k) & RM];
            after += j->e[(c + k) & RM];
        }
        j->rise[c & RM] = after / (before + 1e-7f * ON_R);
    }
    int32_t d = c - ON_P;
    if (d < 1)
        return;
    float r = j->rise[d & RM];
    if (r < ON_RISE)
        return;
    for (int k = 1; k <= ON_P; k++)
        if (j->rise[(d - k) & RM] >= r || j->rise[(d + k) & RM] > r)
            return;
    /* placement: over the whole rise (the block before to the end of the ON_R after: the rise can peak a few blocks
       ahead of the attack, and a 3-block search left chops up to ~14 ms early, host zooms 10-27), the sub-hop with the
       sharpest rise over the 4 before it, among those holding at least a tenth of the loudest */
    enum { SM = ON_RING * SUBS - 1 };
    float top = 0.0f;
    for (int h = (d - 1) * SUBS; h < (d + ON_R) * SUBS; h++)
        if (j->sub[h & SM] > top) top = j->sub[h & SM];
    int best = -1;
    float br = 0.0f;
    for (int h = (d - 1) * SUBS; h < (d + ON_R) * SUBS; h++) {
        float v = j->sub[h & SM];
        if (v < 0.1f * top)
            continue;
        float q = v / (0.25f * (j->sub[(h - 1) & SM] + j->sub[(h - 2) & SM] + j->sub[(h - 3) & SM] +
                                j->sub[(h - 4) & SM]) + 1e-8f);
        if (q > br) { br = q; best = h; }
    }
    int32_t at = (best >= 0 ? best * ON_SUB : d * ON_H) - ON_SUB / 2;
    float level = 0.0f;
    for (int k = 0; k < ON_R; k++)
        level += j->pe[(d + k) & RM];
    keep(j, at < 1 ? 1 : at, r, level / (float)ON_R);
}

int chop_scan_step(struct chop_job *j, float *scratch)
{
    if (j->state != CHOP_SCAN)
        return j->state;
    float *l = scratch, *r = scratch + ON_CHUNK;
    for (int c = 0; c < ON_PER; c++) {
        int32_t from = j->next, count = j->len - from;
        if (count > ON_CHUNK) count = ON_CHUNK;
        count -= count % ON_SUB;
        if (count < ON_SUB) {
            j->state = CHOP_DONE;                         /* the last partial sub-hop is dropped */
            return j->state;
        }
        if (!j->fetch(j, l, j->stereo ? r : 0, count, from))
            return j->state;                             /* not loaded yet: the same frames next block */
        const float *rr = j->stereo ? r : l;             /* mono counts its one channel twice: the same hits */
        float pl = j->pl, pr = j->pr, ql = j->dl, qr = j->dr, acc = j->acc, pacc = j->pacc;
        for (int s0 = 0; s0 < count; s0 += ON_SUB) {
            float sa = 0.0f, pa = 0.0f;
            for (int k = s0; k < s0 + ON_SUB; k++) {
                float a = l[k], v = rr[k], dl = a - pl, dr = v - pr, cl = dl - ql, cr = dr - qr;
                pl = a; pr = v;
                ql = dl; qr = dr;
                sa += cl * cl + cr * cr;
                pa += a * a + v * v;
            }
            pacc += pa;
            int32_t h = (from + s0) / ON_SUB;                /* sub-hop index in the file */
            j->sub[h & (ON_RING * SUBS - 1)] = sa;
            acc += sa;
            if ((h + 1) % SUBS == 0) {                       /* a block complete */
                int32_t b = h / SUBS;
                j->e[b & RM] = acc;
                j->pe[b & RM] = pacc;
                acc = pacc = 0.0f;
                block_done(j, b);
                j->blocks = b + 1;
            }
        }
        j->pl = pl; j->pr = pr; j->dl = ql; j->dr = qr; j->acc = acc; j->pacc = pacc;
        j->next = from + count;
    }
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
    if (++j->misses > 4000) {                               /* ~10 s of a block that never arrives: give up */
        j->state = CHOP_FAILED;
        return 0;
    }
    int ok = r ? fw_fetch2(j->obj, l, r, n, pos) : fw_fetch(j->obj, l, n, pos, 0);
    if (ok)
        j->misses = 0;
    return ok;
}
#endif
