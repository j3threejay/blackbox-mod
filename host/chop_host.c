/* Mac harness for ChopShop's attack scan (chop_dsp.c) and placement (chop.c's pure functions): host/chop_check.py. */
#include <stdlib.h>
#include "../src/chop.h"

int chop_beats(int32_t *out, int max, int32_t len, int32_t anchor, float fpb, float unit_beats);
int chop_onto_hits(int32_t *pos, int n, float step, const struct chop_job *j);
int chop_find(int32_t *out, int want, const struct chop_job *j, uint32_t seed);
int chop_random(int32_t *out, int want, const struct chop_job *j, uint32_t seed);

struct arr { const float *l, *r; int n; int miss_every; int calls; };
static struct chop_job job;
static struct arr src;

static int fetch(struct chop_job *j, float *l, float *r, int n, int32_t pos)
{
    struct arr *a = j->obj;
    if (a->miss_every && ++a->calls % a->miss_every == 0)
        return 0;                                        /* pretend that block is not loaded yet */
    for (int k = 0; k < n; k++) {
        int i = pos + k, in = i >= 0 && i < a->n;
        l[k] = in ? a->l[i] : 0.0f;
        if (r) r[k] = in ? a->r[i] : 0.0f;
    }
    return 1;
}

/* scan frames [0, upto) of the array (resuming this array's scan if it has one); returns the steps (= audio blocks) */
int chop_host_scan(const float *l, const float *r, int n, int upto, int miss_every)
{
    static float scratch[2 * ON_CHUNK];
    if (job.obj == &src && src.l == l && (job.state == CHOP_DONE || job.state == CHOP_SCAN)) {
        if (job.len < upto) { job.len = upto; job.state = CHOP_SCAN; }
    } else {
        src = (struct arr){ l, r, n, miss_every, 0 };
        job.fetch = fetch;
        chop_scan_start(&job, 0, &src, upto, r != 0);
    }
    int steps = 0;
    while (job.state == CHOP_SCAN && steps < 10000000) {
        chop_scan_step(&job, scratch);
        steps++;
    }
    return steps;
}

int chop_host_hits(int32_t *at, float *score, float *level)
{
    for (int i = 0; i < job.n; i++) { at[i] = job.at[i]; score[i] = job.score[i]; level[i] = job.level[i]; }
    return job.n;
}

int chop_host_grid(int32_t *out, int32_t len, int32_t anchor, float fpb, float unit)
{
    int n = chop_beats(out, 128, len, anchor, fpb, unit);
    return chop_onto_hits(out, n, fpb * unit, &job);
}

int chop_host_pick(int find, int32_t *out, int want, uint32_t seed)
{
    return find ? chop_find(out, want, &job, seed) : chop_random(out, want, &job, seed);
}

/* chop.c's firmware-side references: never called here */
int chop_fw_fetch(struct chop_job *j, float *l, float *r, int n, int32_t pos) { (void)j; (void)l; (void)r; (void)n; (void)pos; return 0; }
void *stretch_bank(void) { return 0; }
void sel_ask_pad(int q) { (void)q; }
int sel_take_pad(int q, float *bpm, float *phase, unsigned *frate) { (void)q; (void)bpm; (void)phase; (void)frate; return 0; }
