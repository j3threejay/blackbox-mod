/*
 * Per-pad insert effects: the Phaser and the Flanger. Original 1010music Blackbox, firmware 3.1.9.
 * No firmware calls in this file: host/build.sh compiles it for the Mac as well, so what is rendered there is this code.
 *
 * Six knobs for every effect, 0..1: Rate (0.03 .. 11 Hz), Depth, Manual (where the sweep sits), Feedback, Spread (the
 * right channel's oscillator ahead of the left's, up to half a cycle), Mix (50 % is the classic sum; 100 % is the wet
 * path alone: pitch vibrato). Each effect has a Model, which is where the character lives. All clean-room: written
 * from how the units are documented to behave, no code taken from anywhere.
 *
 * PHASER models (first-order all-pass stages, the notch count is half the stages)
 *   Stone   Electro-Harmonix Small Stone: 4 stages on one frequency, a wide smooth sweep even in octaves. Feedback
 *           is its Color switch turned into a knob.
 *   Ninety  MXR Phase 90: 4 stages, a narrower sweep that lingers at the bottom (the JFETs' curve), and a little grit:
 *           the input and the feedback go through a soft clip.
 *   Vibe    Shin-ei Uni-Vibe: 4 stages spread far apart (its four different capacitors: 0.04x, 0.6x, 2x and 20x the
 *           centre), driven by a lamp, which lights faster than it fades. A throb more than a notch sweep.
 *   Deep    Mu-Tron Bi-Phase with both halves in series: 12 stages, six notches, built to take a lot of Feedback.
 *   Steps   a sample-and-hold phaser (Maestro FSH-1 style): 6 stages jumping to a new random spot four times per
 *           Rate cycle, with a short glide so it does not click.
 *
 * FLANGER models (a modulated delay summed with the dry signal)
 *   Mistress  Electric Mistress: 1 .. 10 ms, a dark bucket-brigade wet path that clips softly. Depth at zero is its
 *             Filter Matrix: a fixed comb you tune with Manual.
 *   A/DA      A/DA Flanger: a 35:1 sweep, even in octaves, that gets darker as the delay gets longer (the bucket
 *             brigade's clock slowing down), and Feedback that goes to the edge.
 *   Tape      two tape machines: the dry signal sits 4 ms back and the wet one sweeps past it through zero. Clean
 *             and full-band, with the reel's eased turnaround.
 *   Metal     short delays (0.15 .. 3 ms) with inverted Feedback: hollow, odd-harmonic, robotic.
 *
 * GATE (his ask: "a good gate with attack hold release etc", listening to its own pad). An ordinary noise gate on
 * the pad's own signal: it opens when the pad gets louder than Thresh and closes again Hold after it falls back.
 *   Thresh   where it opens: 0 % is about -66 dB (almost anything opens it), 100 % is full scale (almost nothing does)
 *   Attack   how fast it opens, 0.1 ms .. 200 ms
 *   Hold     how long it stays open after the signal drops, 0 .. 500 ms
 *   Release  how fast it closes after that, 2 ms .. 2 s
 *   Floor    how far down "closed" is: 0 silences the pad, higher values duck it instead
 *   Mix      shares the other types' knob; 100 % is the gate alone, less blends the ungated pad back in
 * It keeps NO delay line, so unlike the Phaser and Flanger it costs no SDRAM traffic (see NOTES.md, the dropouts
 * of 2026-10-09).
 */
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2: room to spare, so built for speed (3.3.l) */
#include "insert.h"

#define FS   48000.0f
#define PI_F 3.14159265f

static inline float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : x > hi ? hi : x;
}

/* 2^x, within 0.3 % */
static float exp2_f(float x)
{
    if (x < -30.0f)
        return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v;
    v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}

/* soft clip: unity at zero, flat from |x| = 1.5, ceiling 1 */
static inline float sat(float x)
{
    x = clampf(x, -1.5f, 1.5f);
    return x * (1.0f - 0.148148f * x * x);
}

static float rnd(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return (float)(int32_t)*s * (1.0f / 2147483648.0f);
}

/* oscillator shapes over one cycle, -1 .. 1 */
static float tri(uint32_t phase)
{
    float x = (float)phase * (1.0f / 4294967296.0f);
    return x < 0.5f ? 4.0f * x - 1.0f : 3.0f - 4.0f * x;
}

static float sine(uint32_t phase)
{
    float y = (float)(int32_t)phase * (1.0f / 2147483648.0f);
    return 4.0f * y * (1.0f - (y < 0.0f ? -y : y));
}

enum { L_SINE, L_TRI, L_LOW, L_LAMP, L_STEPS, L_EASE };

struct ph_model {
    uint8_t stages, lfo, grit, spread;       /* spread: the stages sit on four different frequencies, wet inverted */
    float octaves;                           /* each way from the centre at full Depth */
    float fb;                                /* Feedback knob at full */
};
static const struct ph_model ph_models[PH_MODELS] = {
    {4, L_SINE, 0, 0, 2.4f, 0.80f},          /* Stone */
    {4, L_LOW, 1, 0, 1.5f, 0.70f},           /* Ninety */
    {4, L_LAMP, 0, 1, 1.1f, 0.45f},          /* Vibe */
    {12, L_SINE, 0, 0, 2.0f, 0.90f},         /* Deep */
    {6, L_STEPS, 0, 0, 2.2f, 0.75f},         /* Steps */
};
static const float vibe_ratio[4] = {0.042f, 0.61f, 1.96f, 19.6f};

struct fl_model {
    uint8_t lfo, through, _r[2];
    float min_ms, manual_oct;                /* Manual: the centre delay, from min_ms up over this many octaves */
    float octaves;                           /* each way at full Depth */
    float fb;                                /* Feedback knob at full; negative = inverted */
    float tone, track;                       /* wet low-pass: Hz, and how much longer delays darken it */
};
static const struct fl_model fl_models[FL_MODELS] = {
    {L_TRI, 0, {0, 0}, 1.0f, 3.32f, 1.3f, 0.80f, 6500.0f, 0.0f},      /* Mistress: centre 1 .. 10 ms */
    {L_TRI, 0, {0, 0}, 0.4f, 3.91f, 2.5f, 0.93f, 15000.0f, 1.0f},     /* A/DA: centre 0.4 .. 6 ms */
    {L_EASE, 1, {0, 0}, 4.0f, 0.0f, 0.0f, 0.35f, 0.0f, 0.0f},         /* Tape: its own sweep, below */
    {L_SINE, 0, {0, 0}, 0.15f, 4.32f, 2.0f, -0.92f, 0.0f, 0.0f},      /* Metal: centre 0.15 .. 3 ms */
};

/* Where the sweep is for channel c at the end of this block, -1 .. 1. phase = that channel's oscillator. */
static float sweep(struct ins_state *s, int c, int shape, uint32_t phase, uint32_t before, float rate_hz, int n)
{
    float v;
    switch (shape) {
    case L_TRI:
        return tri(phase);
    case L_LOW:                              /* a triangle bent so it spends longer at the bottom */
        v = tri(phase);
        return v - 0.35f * (1.0f - v * v);
    case L_EASE:                             /* a sine pushed toward its ends: the reel slows as it turns round */
        v = sine(phase);
        return v * (1.5f - 0.5f * v * v);
    case L_LAMP: {                           /* a bulb: brightens quickly, cools slowly */
        float want = 0.5f + 0.5f * sine(phase), t = (float)n / FS;
        float k = t * (want > s->lamp[c] ? 60.0f : 14.0f) * (0.4f + rate_hz * 0.25f);
        s->lamp[c] += clampf(k, 0.0f, 1.0f) * (want - s->lamp[c]);
        return 2.0f * s->lamp[c] * s->lamp[c] - 1.0f;
    }
    case L_STEPS: {                          /* a new random value four times a cycle, reached in about 4 ms */
        if ((phase >> 30) != (before >> 30) || !s->primed)
            s->held[c] = rnd(&s->rng);
        float k = (float)n * (1.0f / (0.004f * FS));
        s->glide[c] += clampf(k, 0.0f, 1.0f) * (s->held[c] - s->glide[c]);
        return s->glide[c];
    }
    default:
        return sine(phase);
    }
}

static void phaser(struct ins_state *s, const struct ph_model *m, float **ch, int n, const float lfo[2], float dry,
                   float wet)
{
    float centre = 150.0f * exp2_f(4.5f * s->manual), fb = s->fb * m->fb, inv_n = 1.0f / (float)n;
    /* Vibe: its lowest stage sits near 20 Hz and turns everything above it over, so the wet path goes in upside
       down: the bass stays in phase with the dry signal and the moving cancellation is in the mids */
    if (m->spread) {
        wet = -wet;
        fb = -fb;
    }
    int freqs = m->spread ? 4 : 1;
    for (int c = 0; c < 2; c++) {
        float *x = ch[c];
        if (!x)
            continue;
        float a[4], da[4];
        for (int k = 0; k < freqs; k++) {
            float f = centre * exp2_f(m->octaves * s->depth * lfo[c]) * (m->spread ? vibe_ratio[k] : 1.0f);
            float t = PI_F * clampf(f, 20.0f, 10000.0f) / FS;
            t = t * (15.0f - t * t) / (15.0f - 6.0f * t * t);                /* tan */
            float to = (t - 1.0f) / (t + 1.0f);
            a[k] = s->primed ? s->cur[c][k] : to;
            da[k] = (to - a[k]) * inv_n;
            s->cur[c][k] = to;
        }
        float *z = s->ap[c], loop = s->loop[c];
        for (int i = 0; i < n; i++) {
            float in = x[i], v = in + fb * loop;
            if (m->grit)
                v = sat(v * 1.3f) * (1.0f / 1.3f);
            for (int k = 0; k < freqs; k++)
                a[k] += da[k];
            for (int k = 0; k < m->stages; k++) {
                float ak = a[k & (freqs - 1)], y = ak * v + z[k];
                z[k] = v - ak * y;
                v = y;
            }
            loop = sat(v);
            x[i] = dry * in + wet * v;
        }
        s->loop[c] = loop;
    }
}

static void flanger(struct ins_state *s, const struct fl_model *m, float **ch, int n, const float lfo[2], float dry,
                    float wet)
{
    float inv_n = 1.0f / (float)n, fb = s->fb * m->fb;
    float base = m->min_ms * exp2_f(m->manual_oct * s->manual);     /* Manual: the delay the sweep is centred on */
    uint32_t w0 = s->w;
    for (int c = 0; c < 2; c++) {
        float *x = ch[c];
        if (!x)
            continue;
        float ms = m->through ? 4.0f * (1.0f + s->depth * lfo[c]) + (s->manual - 0.5f) * 3.0f
                              : base * exp2_f(m->octaves * s->depth * lfo[c]);
        float to = clampf(ms * (FS / 1000.0f), 1.0f, (float)(INS_LINE - 4));
        float d = s->primed ? s->cur[c][0] : to, dd = (to - d) * inv_n;
        s->cur[c][0] = to;
        /* the wet path's low-pass: fixed, or closing as the delay grows (a bucket brigade's clock) */
        float hz = m->tone > 0.0f ? m->tone / (1.0f + m->track * ms * 0.35f) : 0.0f;
        float k = hz > 0.0f ? clampf(2.0f * PI_F * hz / FS, 0.0f, 1.0f) : 1.0f;
        float *line = s->line[c], loop = s->loop[c], tone = s->tone[c];
        uint32_t w = w0;
        for (int i = 0; i < n; i++) {
            float in = x[i];
            line[w & (INS_LINE - 1)] = hz > 0.0f ? sat(in + fb * loop) : in + fb * sat(loop);
            d += dd;
            int whole = (int)d;
            float frac = d - (float)whole;
            float y0 = line[(w - (uint32_t)whole) & (INS_LINE - 1)], y1 = line[(w - (uint32_t)whole - 1u) & (INS_LINE - 1)];
            float y = y0 + frac * (y1 - y0);
            tone += k * (y - tone);
            loop = tone;
            float direct = m->through ? line[(w - 192u) & (INS_LINE - 1)] : in;
            x[i] = dry * direct + wet * tone;
            w++;
        }
        s->loop[c] = loop;
        s->tone[c] = tone;
    }
    s->w = w0 + (uint32_t)n;
}

static void gate(struct ins_state *s, const struct ins_set *p, float **ch, int n)
{
    /* the knobs, worked out once a block */
    float thresh = exp2_f(-11.0f * (1.0f - clampf(p->thresh, 0.0f, 1.0f)));     /* full scale down to about -66 dB */
    float att_ms = 0.1f * exp2_f(11.0f * clampf(p->attack, 0.0f, 1.0f));        /* 0.1 .. 205 ms */
    float rel_ms = 2.0f * exp2_f(9.97f * clampf(p->release, 0.0f, 1.0f));       /* 2 ms .. 2 s */
    float hold_ms = 500.0f * clampf(p->hold, 0.0f, 1.0f);
    float floor_g = clampf(p->floor, 0.0f, 1.0f);
    float mix = clampf(p->mix, 0.0f, 1.0f);
    /* one-pole per sample: about 63 % of the way in the stated time */
    float ka = clampf(1000.0f / (att_ms * FS), 0.0f, 1.0f);
    float kr = clampf(1000.0f / (rel_ms * FS), 0.0f, 1.0f);
    float per_sample_ms = 1000.0f / FS;
    float env = s->env, g = s->gain, hold_left = s->hold_left;
    int open = s->open;

    for (int i = 0; i < n; i++) {
        float a = ch[0][i] < 0.0f ? -ch[0][i] : ch[0][i];
        if (ch[1]) {
            float b = ch[1][i] < 0.0f ? -ch[1][i] : ch[1][i];
            if (b > a)
                a = b;
        }
        env = a > env ? a : env + 0.004f * (a - env);        /* rises at once, falls back over about 5 ms, so the
                                                                gate can actually shut on a quick drop */
        if (env >= thresh) {
            open = 1;
            hold_left = hold_ms;
        } else if (open) {
            hold_left -= per_sample_ms;
            if (hold_left <= 0.0f)
                open = 0;
        }
        float target = open ? 1.0f : floor_g;
        g += (target > g ? ka : kr) * (target - g);
        float gain = 1.0f - mix + mix * g;                   /* Mix blends the ungated pad back in */
        ch[0][i] *= gain;
        if (ch[1])
            ch[1][i] *= gain;
    }
    s->env = env;
    s->gain = g;
    s->hold_left = hold_left;
    s->open = (uint8_t)open;
}

void ins_render(struct ins_state *s, const struct ins_set *p, float *l, float *r, int n)
{
    if (n <= 0 || p->type == INS_OFF || p->type >= INS_TYPES)
        return;
    if (p->type == INS_TRANS) {                              /* transient.c: its own state, no delay line */
        ts_block(&s->ts, &p->ts, l, r, n);
        s->primed = 1;
        return;
    }
    if (p->type == INS_GATE) {                               /* no oscillator, no delay line, no smoothed knobs */
        float *gch[2] = {l, r};
        gate(s, p, gch, n);
        s->primed = 1;
        return;
    }
    if (!s->primed) {
        s->depth = p->depth;
        s->manual = p->manual;
        s->fb = p->fb;
        s->mix = p->mix;
        s->rng = 0x1f0c0de5u;
    } else {
        s->depth += 0.3f * (p->depth - s->depth);
        s->manual += 0.3f * (p->manual - s->manual);
        s->fb += 0.3f * (p->fb - s->fb);
        s->mix += 0.3f * (p->mix - s->mix);
    }
    float hz = 0.03f * exp2_f(8.5f * clampf(p->rate, 0.0f, 1.0f));
    uint32_t before = s->phase, offset = (uint32_t)(clampf(p->spread, 0.0f, 1.0f) * 2147483648.0f);
    s->phase += (uint32_t)(hz * (4294967296.0f / FS) * (float)n);

    int shape = p->type == INS_PHASER ? ph_models[p->model < PH_MODELS ? p->model : 0].lfo
                                      : fl_models[p->model < FL_MODELS ? p->model : 0].lfo;
    float lfo[2];
    lfo[0] = sweep(s, 0, shape, s->phase, before, hz, n);
    lfo[1] = offset ? sweep(s, 1, shape, s->phase + offset, before + offset, hz, n) : lfo[0];

    /* Mix: both paths at full level in the middle, one fading out toward each end; 4.4 dB off there, which keeps a
       drum loop near its dry loudness on every model (host/render_insert.py prints it) */
    float m = clampf(s->mix, 0.0f, 1.0f), edge = m < 0.5f ? 2.0f * m : 2.0f * (1.0f - m);
    float level = 1.0f - 0.4f * edge, dry = (m < 0.5f ? 1.0f : edge) * level, wet = (m < 0.5f ? edge : 1.0f) * level;

    float *ch[2] = {l, r};
    if (p->type == INS_PHASER)
        phaser(s, &ph_models[p->model < PH_MODELS ? p->model : 0], ch, n, lfo, dry, wet);
    else
        flanger(s, &fl_models[p->model < FL_MODELS ? p->model : 0], ch, n, lfo, dry, wet);
    s->primed = 1;
}
