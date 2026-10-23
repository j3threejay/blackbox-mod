/*
 * "Confetti": granular micro-looper / glitch for the delay slot (FX1, Type: Confetti). Original 1010music Blackbox, 3.1.9.
 *
 * Clean-room, after the Hologram Microcosm manual: the send is recorded into a memory (the stock delay's two long
 * lines as one 16-bit stereo loop, 8.0 s) and re-played as small pieces ("confetti") on the preset's tempo.
 *
 *   Mode      Loops    pieces of the last few steps come back at normal / half / double speed or reversed
 *             Cloud    a wash of short overlapping grains from the last moments, a few of them an octave off
 *             Slide    like Loops, but each piece slides in pitch while it plays
 *             Stutter  the last step is caught and ratcheted 2 .. 8 times, fading
 *             Arp      a slice of the last step is looped at stepped pitches: root, 5th, octave, octave + 5th, two octaves
 *             Taps     plain rhythmic repeats of the last step: 1 .. 5 taps, spread left / right
 *   Size      the step, as a note length at the preset tempo (shared with Relapse's Size)
 *   Density  how much happens: chance of a piece per step / grain density / number of taps
 *   Contour     the pieces' envelope: 0 = short plucks, 50 % = whole pieces, 100 % = slow swells
 *   Repeats   the delay's Feedback: how much of the output is written back into the memory
 *   Tone      darkens the output and what is written back (shared with Relapse's Tone)
 *   Space     a small reverb on the pieces
 *
 * No firmware calls in here, so host/ can compile the same file for the Mac and render audio with it.
 * munchi.cpp owns the slot and reads the settings.
 */
#include <stdint.h>

#include "rev4.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2: room to spare, so built for speed (3.3.l) */

#define CONFETTI_FS   48000.0f
#define MEM_GAIN   16384.0f          /* 16-bit store with 6 dB of headroom */
#define VOICES     12
#define EDGE       48                /* 1 ms fades at chunk edges */
#define GUARD      64.0f             /* frames a reader stays away from the write head */
#define CONFETTI_MAGIC 0x434e4632u      /* "CNF2": 3.3.y added quiet */
#ifndef REV_MIX
#define REV_MIX    0.45f
#endif
#define FB_HOLD    0.35f             /* the write-back is held to this level, so Repeats at 100 % sustains but cannot run away */
#define OUT_CEIL   1.25f

enum { M_LOOPS, M_CLOUD, M_SLIDE, M_STUTTER, M_ARP, M_TAPS, M_MODES };
#define SIZES 9
static const float size_beats[SIZES] = {0.125f, 0.25f, 1.0f / 3.0f, 0.5f, 0.75f, 1.0f, 1.5f, 2.0f, 4.0f};

struct confetti_params {
    uint32_t mode, size;
    float repeats, density, contour, tone, space;      /* 0..1 */
};

struct piece {
    uint32_t left, len, att, rel;    /* output frames left / in all, fade in, fade out */
    float pos, rate, glide;          /* read position in the memory, step per frame, change of the step per frame */
    float start;                     /* chunk loop: where each chunk starts */
    uint32_t chunk, cnt;             /* output frames per chunk (0 = no loop), frames into the chunk */
    float amp, fall;                 /* chunk gain, and what it is multiplied by at each repeat */
    float gl, gr;
};

#define CONFETTI_REV_FLOATS REV4_FLOATS  /* the reverb's lines (rev4.c) */

struct confetti {
    uint32_t magic;
    uint32_t w, filled;              /* write frame, frames recorded so far */
    uint32_t period, cloud;          /* frames to the next step / the next cloud grain */
    uint32_t steps, rng, mode;
    float lp[2];
    float fb_env;                    /* level of the output, for the write-back hold */
    struct rev4 rev;
    struct piece v[VOICES];
    uint32_t quiet;                  /* frames in a row with the send and the output both under QUIET (3.3.y) */
};

_Static_assert(sizeof(struct confetti) <= 0x1000, "munchi.cpp puts the wet blocks 0x1000 into the state line");

/*
 * IDLE BYPASS (3.3.y). Confetti ran at full cost with nothing going on: 11.4 % of the CPU since boot on the test unit at
 * 0.6 voices (profiler, 10-20). Once the send AND the output have stayed under QUIET (-90 dBFS) for longer than the
 * memory (+ 1 s), every sample in the memory is under it too (what is written back is the send plus the output, at
 * most a step of the 16-bit store), so nothing a piece can read, in any mode, at any Size, is above -90 dB. Then the
 * block is skipped: the output is exact silence and nothing moves. The first block with any send above QUIET runs
 * normally again from where it stopped. What changes against running on: the output under -90 dB becomes 0, and the
 * step clock and the random pieces carry on from where they were instead of where they would be.
 */
#define QUIET 3.1623e-5f             /* -90 dBFS */

static inline float m_rnd(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return (float)(*s >> 8) * (1.0f / 16777216.0f);
}

static inline float m_soft(float x)
{
    x = x < -3.0f ? -3.0f : x > 3.0f ? 3.0f : x;
    return x * (27.0f + x * x) / (27.0f + 9.0f * x * x);
}

static inline float m_unit(float v)
{
    return v < 0.0f ? 0.0f : v > 1.0f ? 1.0f : v;
}

/*
 * Start a piece `back` frames behind the write head. len: output frames. chunk: output frames per loop of the chunk
 * (0 = play straight through). Refused when the memory does not hold that much yet, or the reader would run into the
 * write head (from behind when it is faster, from the far side when it is slower or reversed).
 */
static __attribute__((noinline)) struct piece *spawn(struct confetti *m, uint32_t mem, float back, uint32_t len, float rate, float end_rate,
                          uint32_t chunk, float gain, float pan, float contour)
{
    if (len < 4 * EDGE)
        len = 4 * EDGE;
    if (chunk && chunk < 2 * EDGE)
        chunk = 2 * EDGE;
    uint32_t att = EDGE * 2, rel;
    if (contour < 0.5f) {              /* plucks: shorter, and all decay */
        len = (uint32_t)((float)len * (0.25f + 1.5f * contour));
        if (len < 4 * EDGE)
            len = 4 * EDGE;
        rel = len - att;
    } else {                         /* swells: the fade in grows to 85 % of the piece */
        att += (uint32_t)((contour - 0.5f) * 1.7f * (float)(len - 4 * EDGE));
        rel = len / 8 < 2 * EDGE ? 2 * EDGE : len / 8;
        if (att + rel > len)
            att = len - rel;
    }
    float top = rate > end_rate ? rate : end_rate, low = rate < end_rate ? rate : end_rate;
    float span = chunk ? (float)chunk * top : (float)len * top;         /* memory the reader covers, forwards */
    float need = chunk ? span + GUARD : (top > 1.0f ? (float)len * (top - 1.0f) : 0.0f) + GUARD;
    if (back < need)
        back = need;
    float behind = back;                                                /* furthest it gets from the write head */
    if (low < 0.0f)
        behind += (float)len * (1.0f - low);
    else if (!chunk && low < 1.0f)
        behind += (float)len * (1.0f - low);
    else if (chunk)
        behind += (float)len;
    if (behind + GUARD > (float)mem || back + (low < 0.0f ? (float)len * -low : 0.0f) > (float)m->filled)
        return 0;

    struct piece *v = &m->v[0];
    for (int i = 0; i < VOICES; i++) {
        if (!m->v[i].left) {
            v = &m->v[i];
            break;
        }
        if (m->v[i].left < v->left)
            v = &m->v[i];            /* all busy: the one closest to its end gives way */
    }
    float pos = (float)m->w - back;
    if (pos < 0.0f)
        pos += (float)mem;
    v->left = v->len = len;
    v->att = att;
    v->rel = rel;
    v->pos = v->start = pos;
    v->rate = rate;
    v->glide = (end_rate - rate) / (float)len;
    v->chunk = chunk;
    v->cnt = 0;
    v->amp = 1.0f;
    v->fall = 1.0f;
    gain *= contour < 0.5f ? 1.0f + 2.4f * (0.5f - contour) : 1.0f + 1.2f * (contour - 0.5f);   /* plucks and swells carry less */
    v->gl = gain * (pan > 0.5f ? 2.0f * (1.0f - pan) : 1.0f);
    v->gr = gain * (pan < 0.5f ? 2.0f * pan : 1.0f);
    return v;
}

/* one step of the clock: what the mode does with it */
static void step(struct confetti *m, uint32_t mem, const struct confetti_params *p, uint32_t d)
{
    static const float loop_rates[8] = {1.0f, 1.0f, 1.0f, 0.5f, 2.0f, 2.0f, -1.0f, 0.5f};
    static const float arp_rates[8] = {1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 3.0f, 2.0f, 1.5f};
    static const uint8_t ratchets[6] = {2, 3, 4, 4, 6, 8};
    static const uint8_t tap_at[5] = {1, 2, 3, 5, 8};
    static const float tap_gain[5] = {0.8f, 0.6f, 0.45f, 0.35f, 0.27f};
    float a = p->density, fd = (float)d;
    uint32_t k = m->steps++;

    switch (p->mode) {
    case M_LOOPS:
    case M_SLIDE:
        for (int twice = 0; twice < 2; twice++) {
            if (m_rnd(&m->rng) >= (twice ? a * a * 0.6f : 0.1f + 0.9f * a))
                continue;
            uint32_t len = d * (m_rnd(&m->rng) < 0.35f ? 2u : 1u);
            float back = fd * (float)(1 + (int)(m_rnd(&m->rng) * 3.99f)), pan = 0.2f + 0.6f * m_rnd(&m->rng);
            if (p->mode == M_SLIDE) {
                float r = m_rnd(&m->rng);
                float from = r < 0.5f ? 1.0f : r < 0.75f ? 2.0f : 0.5f, to = r < 0.25f ? 0.5f : r < 0.5f ? 2.0f : 1.0f;
                spawn(m, mem, back + (float)len, len, from, to, 0, 0.75f, pan, p->contour);
            } else {
                float rate = loop_rates[(int)(m_rnd(&m->rng) * 7.99f)];
                if (rate < 0.0f)
                    spawn(m, mem, GUARD, len, rate, rate, 0, 0.75f, pan, p->contour);
                else
                    spawn(m, mem, rate > 1.0f ? back + (float)len : back, len, rate, rate, 0, 0.75f, pan, p->contour);
            }
        }
        break;
    case M_STUTTER:
        if (m_rnd(&m->rng) < 0.1f + 0.9f * a) {
            uint32_t n = ratchets[(int)(m_rnd(&m->rng) * 5.99f)];
            struct piece *v = spawn(m, mem, fd, d, 1.0f, 1.0f, d / n, 0.7f, 0.5f, 0.5f);
            if (v) {
                v->att = EDGE;
                v->rel = EDGE * 2;
                v->fall = 1.0f - 0.9f * (1.0f - p->contour) / (float)n;     /* low Contour: each repeat quieter */
            }
        }
        break;
    case M_ARP:
        if (m_rnd(&m->rng) < 0.3f + 0.7f * a) {
            float rate = arp_rates[k & 7];
            uint32_t src = d / 2;
            spawn(m, mem, fd, d, rate, rate, (uint32_t)((float)src / rate), 0.9f, (k & 1) ? 0.3f : 0.7f, p->contour);
        }
        break;
    case M_TAPS: {
        int taps = 1 + (int)(a * 4.49f);
        for (int t = 0; t < taps; t++)
            spawn(m, mem, fd * (float)tap_at[t], d, 1.0f, 1.0f, 0, tap_gain[t], (t & 1) ? 0.15f : 0.85f, p->contour);
        break;
    }
    default:
        break;
    }
}

/*
 * One block. a / b: the two memory halves, `half` stereo frames each. rev: CONFETTI_REV_FLOATS floats for the reverb.
 * fresh: the lines were just cleared (type change).
 */
void confetti_block(struct confetti *m, float *rev, int16_t *a, int16_t *b, uint32_t half, const struct confetti_params *p,
                 float bpm, const float *il, const float *ir, float *ol, float *orr, int n, int fresh)
{
    uint32_t mem = half * 2;
    if (fresh || m->magic != CONFETTI_MAGIC) {
        for (unsigned i = 0; i < sizeof *m / 4; i++)
            ((volatile uint32_t *)m)[i] = 0;
        for (unsigned i = 0; i < CONFETTI_REV_FLOATS; i++)
            rev[i] = 0.0f;
        m->rng = 0x6d6f7465u;
        m->magic = CONFETTI_MAGIC;
    }
#define MEMP(i, c) (((i) < half ? a + (i) * 2 : b + ((i) - half) * 2)[c])

    if (m->quiet >= mem + 48000u) {  /* idle: skipped while the send stays quiet */
        float pk = 0.0f;
        for (int i = 0; i < n; i++) {
            float x = il[i] < 0.0f ? -il[i] : il[i], y = ir[i] < 0.0f ? -ir[i] : ir[i];
            pk = x > pk ? x : pk;
            pk = y > pk ? y : pk;
        }
        if (pk < QUIET) {
            for (int i = 0; i < n; i++)
                ol[i] = orr[i] = 0.0f;
            return;
        }
        m->quiet = 0;
    }
    float loud = 0.0f;               /* the block's peak, send and output: for the idle count */

    if (!(bpm > 20.0f))
        bpm = 120.0f;
    float df = size_beats[p->size < SIZES ? p->size : 5] * 60.0f / bpm * CONFETTI_FS;
    uint32_t d = df < 960.0f ? 960u : df > (float)(mem / 10) ? mem / 10 : (uint32_t)df;
    if (p->mode != m->mode) {        /* a mode change lets the pieces already playing finish */
        m->mode = p->mode;
        m->period = 0;
        m->cloud = 0;
    }
    if (m->period > d)
        m->period = d;

    static const float tap_sum[5] = {0.8f, 1.4f, 1.85f, 2.2f, 2.47f};
    float fb = m_unit(p->repeats) * 0.85f, lp_a = 1.0f - 0.92f * m_unit(p->tone), space = m_unit(p->space);
    if (p->mode == M_TAPS)
        fb /= tap_sum[(int)(p->density * 4.49f) > 4 ? 4 : (int)(p->density * 4.49f)] * 1.25f;   /* all taps together: under 1 */
    else if (p->mode == M_LOOPS || p->mode == M_SLIDE)
        fb *= 0.75f;
    float rev_g = 0.78f + 0.17f * space, rev_mix = space * REV_MIX;

    /* Cloud: grains per second, their length, and a gain that keeps the pile level as it gets denser */
    float density = 2.0f + 38.0f * p->density * p->density;
    uint32_t grain = d / 2 < 1440 ? 1440 : d / 2 > 24000 ? 24000 : d / 2;
    float pile = density * (float)grain * (p->contour < 0.5f ? 0.25f + 1.5f * p->contour : 1.0f) / CONFETTI_FS;
    float cloud_gain = 0.8f / (pile > 1.0f ? 1.0f + 0.25f * (pile - 1.0f) : 1.0f);

    for (int i = 0; i < n; i++) {
        if (p->mode == M_CLOUD) {
            if (!m->cloud) {
                m->cloud = (uint32_t)(CONFETTI_FS / density * (0.5f + m_rnd(&m->rng)));
                float r = m_rnd(&m->rng), rate = r < 0.12f ? 2.0f : r < 0.22f ? 0.5f : 0.997f + 0.006f * m_rnd(&m->rng);
                float back = (float)grain * rate + GUARD + m_rnd(&m->rng) * 4.0f * (float)d;
                spawn(m, mem, back, grain, rate, rate, 0, cloud_gain, m_rnd(&m->rng), p->contour < 0.5f ? p->contour : 0.75f);
            }
            m->cloud--;
        } else {
            if (!m->period) {
                m->period = d;
                step(m, mem, p, d);
            }
            m->period--;
        }

        float y[2] = {0.0f, 0.0f};
        for (int k = 0; k < VOICES; k++) {
            struct piece *v = &m->v[k];
            if (!v->left)
                continue;
            uint32_t done = v->len - v->left;
            float env = done < v->att ? (float)done / (float)v->att : v->left < v->rel ? (float)v->left / (float)v->rel : 1.0f;
            if (v->chunk) {
                uint32_t rest = v->chunk - v->cnt;
                if (v->cnt < EDGE)
                    env *= (float)v->cnt * (1.0f / EDGE);
                else if (rest < EDGE)
                    env *= (float)rest * (1.0f / EDGE);
                env *= v->amp;
            }
            uint32_t s0 = (uint32_t)v->pos;
            float frac = v->pos - (float)s0;
            if (s0 >= mem)
                s0 = 0;
            uint32_t s1 = s0 + 1 < mem ? s0 + 1 : 0;
            float pl = (float)MEMP(s0, 0), pr = (float)MEMP(s0, 1);
            y[0] += (pl + ((float)MEMP(s1, 0) - pl) * frac) * env * v->gl;
            y[1] += (pr + ((float)MEMP(s1, 1) - pr) * frac) * env * v->gr;
            v->pos += v->rate;
            v->rate += v->glide;
            if (v->pos >= (float)mem)
                v->pos -= (float)mem;
            else if (v->pos < 0.0f)
                v->pos += (float)mem;
            if (v->chunk && ++v->cnt >= v->chunk) {
                v->cnt = 0;
                v->pos = v->start;
                v->amp *= v->fall;
            }
            v->left--;
        }

        float wet[2];
        for (int c = 0; c < 2; c++) {
            m->lp[c] += (y[c] * (1.0f / MEM_GAIN) - m->lp[c]) * lp_a;
            wet[c] = m->lp[c];
        }
        const float in[2] = {il[i], ir[i]};
        float lvl = wet[0] < 0.0f ? -wet[0] : wet[0], lvr = wet[1] < 0.0f ? -wet[1] : wet[1];
        lvl = lvl > lvr ? lvl : lvr;
        m->fb_env = lvl > m->fb_env ? lvl : m->fb_env * 0.9999f;
        float back = m->fb_env > FB_HOLD ? fb * FB_HOLD / m->fb_env : fb;
        for (int c = 0; c < 2; c++) {
            float wr = 2.0f * m_soft(0.5f * (in[c] + back * wet[c])) * MEM_GAIN;
            MEMP(m->w, c) = (int16_t)(wr > 32767.0f ? 32767.0f : wr < -32767.0f ? -32767.0f : wr);
        }

        if (space > 0.0f) {
            float tail[2];
            rev4_step(&m->rev, rev, 0.5f * (wet[0] + wet[1]), rev_g, 0.45f, tail);
            wet[0] += rev_mix * tail[0];
            wet[1] += rev_mix * tail[1];
        }
        ol[i] = OUT_CEIL * m_soft(wet[0] * (1.0f / OUT_CEIL));
        orr[i] = OUT_CEIL * m_soft(wet[1] * (1.0f / OUT_CEIL));
        for (int c = 0; c < 2; c++) {
            float x = in[c] < 0.0f ? -in[c] : in[c], y = c ? orr[i] : ol[i];
            y = y < 0.0f ? -y : y;
            loud = x > loud ? x : loud;
            loud = y > loud ? y : loud;
        }

        if (++m->w >= mem)
            m->w = 0;
        if (m->filled < mem)
            m->filled++;
    }
    m->quiet = loud < QUIET ? m->quiet + (uint32_t)n : 0;
#undef MEMP
}
