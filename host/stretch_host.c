/*
 * Mac harness for stretch_dsp.c (host/render_stretch.py): stock's slicing as NOTES describes it (equal slices, each
 * started on the new grid at its own source position, 256-frame linear fades, a slice running on until the next one
 * has faded in), with each slice's segment rendered by a model. Block size 64, like a firmware block.
 */
#include <stdlib.h>
#include <string.h>
#include "../src/stretch.h"

struct arr { const float *l, *r; int n; };

static void fetch(const struct str_src *s, float *l, float *r, int n, int32_t pos)
{
    const struct arr *a = s->obj;
    for (int k = 0; k < n; k++) {
        int32_t i = pos + k;
        int in = i >= s->lo && i < a->n;
        l[k] = in ? a->l[i] : 0.0f;
        if (r) r[k] = in ? a->r[i] : 0.0f;
    }
}

#define FADE 256
#define BLOCK 64
#define SEGS 4

int render_sliced(const float *l, const float *r, int n_in, float speed, double slice_in, int model, int pitch_cents,
                  float *ol, float *orr, int n_out)
{
    struct arr a = { l, r, n_in };
    struct str_src src = { &a, 0, n_in, r != 0, fetch };
    struct str_seg *seg = calloc(SEGS, sizeof *seg);
    int32_t sstart[SEGS], s_o0[SEGS], s_o1[SEGS];
    struct str_grain plain[SEGS];
    float *scratch = calloc(STR_SCRATCH_ALL, sizeof(float));
    float bl[BLOCK], br[BLOCK];
    float rate = 1.0f;
    for (int c = 0; c < pitch_cents; c++) rate *= 1.000577790f;
    for (int c = 0; c > pitch_cents; c--) rate /= 1.000577790f;
    double slice_out = slice_in / speed;
    for (int i = 0; i < SEGS; i++) s_o1[i] = -1;
    memset(ol, 0, sizeof(float) * n_out);
    if (orr) memset(orr, 0, sizeof(float) * n_out);
    int next = 0;
    for (int o = 0; o < n_out; o += BLOCK) {
        int nb = n_out - o < BLOCK ? n_out - o : BLOCK;
        /* slices starting in this block: give each a segment */
        while ((int)(next * slice_out) < o + nb && next * slice_in < n_in) {
            int k = next % SEGS;
            sstart[k] = (int32_t)(next * slice_in);
            s_o0[k] = (int)(next * slice_out);
            s_o1[k] = (int)((next + 1) * slice_out) + FADE;
            plain[k].i = sstart[k]; plain[k].f = 0;
            seg[k].magic = 0;
            next++;
        }
        for (int k = 0; k < SEGS; k++) {
            if (s_o1[k] <= o || s_o0[k] >= o + nb) continue;
            int a0 = s_o0[k] > o ? s_o0[k] - o : 0, a1 = s_o1[k] < o + nb ? s_o1[k] - o : nb;
            int m = a1 - a0;
            if (model == STR_STOCK) {
                /* stock: read the slice straight at the pitch */
                for (int j = 0; j < m; j++) {
                    float p = plain[k].i + plain[k].f;
                    int32_t i = (int32_t)p; float t = p - i;
                    float x0 = i < n_in && i >= 0 ? l[i] : 0, x1 = i + 1 < n_in && i + 1 >= 0 ? l[i + 1] : 0;
                    float y0 = r ? (i < n_in && i >= 0 ? r[i] : 0) : x0, y1 = r ? (i + 1 < n_in ? r[i + 1] : 0) : x1;
                    bl[j] = x0 + (x1 - x0) * t; br[j] = y0 + (y1 - y0) * t;
                    plain[k].f += rate; int ad = (int)plain[k].f; plain[k].i += ad; plain[k].f -= ad;
                }
            } else {
                str_render(&seg[k], model, &src, sstart[k], (float)slice_in, rate, (float)speed, bl, r ? br : 0, m, scratch);
                if (!r) memcpy(br, bl, sizeof(float) * m);
            }
            for (int j = 0; j < m; j++) {
                int oo = o + a0 + j, ki = oo - s_o0[k], left = s_o1[k] - oo;
                float g = 1.0f;
                if (ki < FADE && s_o0[k] > 0) g *= (float)ki / FADE;
                if (left < FADE) g *= (float)left / FADE;
                ol[oo] += g * bl[j];
                if (orr) orr[oo] += g * br[j];
            }
        }
    }
    free(seg); free(scratch);
    return 0;
}

/* One segment, read the way the firmware reads it: blocks of `block` frames from slice start `start` (test_stretch.py) */
int render_segment(const float *l, const float *r, int n_in, int32_t start, float span, float rate, float ref_rate, int model,
                   float *ol, float *orr, int n_out, int block)
{
    struct arr a = { l, r, n_in };
    struct str_src src = { &a, 0, n_in, r != 0, fetch };
    struct str_seg *seg = calloc(1, sizeof *seg);
    float *scratch = calloc(STR_SCRATCH_ALL, sizeof(float));
    for (int o = 0; o < n_out; o += block) {
        int nb = n_out - o < block ? n_out - o : block;
        str_render(seg, model, &src, start, span, rate, ref_rate, ol + o, r ? orr + o : 0, nb, scratch);
    }
    free(seg); free(scratch);
    return 0;
}
