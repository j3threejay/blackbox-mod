/* Mac harness for tempo_dsp.c: run the job to completion over an array (host/tempo_check.py). */
#include <stdlib.h>
#include "../src/tempo.h"

struct arr { const float *l, *r; int n; int miss_every; int calls; };

static int fetch(struct tempo_job *j, float *l, float *r, int n, int32_t pos)
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

/* returns the steps taken (= blocks on the unit); bpm / phase out */
int tempo_run(const float *l, const float *r, int n, int frate, int miss_every, float *bpm, float *phase)
{
    static struct tempo_job j;
    struct arr a = { l, r, n, miss_every, 0 };
    float *scratch = malloc(sizeof(float) * 2 * TEMPO_READ);
    j.fetch = fetch;
    tempo_start(&j, 0, &a, n, (unsigned)frate, r != 0);
    int steps = 0;
    while (j.state != TEMPO_DONE && j.state != TEMPO_FAILED && steps < 100000) {
        tempo_step(&j, scratch);
        steps++;
    }
    free(scratch);
    *bpm = j.state == TEMPO_DONE ? j.bpm : 0.0f;
    *phase = j.phase;
    return steps;
}
