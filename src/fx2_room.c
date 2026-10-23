/*
 * Room, the reverb slot's second algorithm (Type: Room). Original 1010music Blackbox, firmware 3.1.9.
 * Moved here from fx2.c in 3.3.v so it lives in flash bank 2 (build.sh BANK2_SRCS): bank 1 was down to ~2 KB and note
 * repeat needs room there. Leaf DSP: no calls out of bank 2. fx2_core (bank 1) only calls it when bank 2 is live.
 */
#include "fx2.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2: built for speed (3.3.y: -5.9 % instructions measured) */

/*
 * Room: early reflections, four input diffusers (the plate's own lengths), and an 8-line feedback delay network
 * (fast Hadamard 8x8) with a short allpass and a damping low-pass inside every line, so echoes thicken into a smooth
 * wash. (v1 in 3.1.i had 4 lines and 2 diffusers: it was heard as very metallic / resonant.)
 * Buffers: ER line = buffer 6; input diffusers = buffers 0-3; line allpasses = buffers 4-5 (8 x 128 floats);
 * lines = buffers 7-10, two per buffer (4096 floats each).
 */
#define ER_LEN   8192
static const uint16_t in_ap_len[4] = {142, 107, 379, 277};
static const uint16_t line_len[8] = {887, 1031, 1153, 1279, 1409, 1543, 1693, 1867};   /* 30..63 ms at 29.8 kHz */
static const uint8_t line_ap_len[8] = {37, 53, 67, 83, 97, 109, 113, 127};
/* early reflections: 8 irregular taps per side, alternating signs, falling off: dense enough not to comb-filter */
#define ER_TAPS 8
static const uint16_t er_tap_l[ER_TAPS] = {131, 197, 283, 359, 467, 571, 709, 853};
static const uint16_t er_tap_r[ER_TAPS] = {157, 233, 311, 421, 523, 647, 779, 929};
static const float er_gain[ER_TAPS] = {0.55f, -0.47f, 0.41f, -0.35f, 0.3f, -0.25f, 0.21f, -0.17f};
static const float out_sign_l[8] = {1, -1, 1, -1, 1, 1, -1, -1}, out_sign_r[8] = {1, 1, -1, -1, -1, 1, 1, -1};

static const uint8_t mod_line[4] = {0, 2, 5, 7};
static const uint32_t lfo_inc[4] = {41200u, 53900u, 67100u, 78800u};   /* 0.29 .. 0.55 Hz at 29.8 kHz */

/* triangle -1..1 from a 32-bit phase */
static inline __attribute__((always_inline)) float tri(uint32_t ph)
{
    int32_t v = (int32_t)(ph ^ (uint32_t)((int32_t)ph >> 31));      /* fold: 0..2^31 */
    return (float)v * (2.0f / 2147483648.0f) - 1.0f;
}

static inline __attribute__((always_inline)) float allpass(float *buf, unsigned *pos, unsigned len, float g, float x)
{
    float y = buf[*pos], w = x + g * y;
    buf[*pos] = w;
    *pos = *pos + 1 >= len ? 0 : *pos + 1;
    return y - g * w;
}

void room(float *state, const float *in, float *outl, float *outr, int n, const struct room_params *rp)
{
    float *er = BUF(state, 6);
    float *in_ap[4] = {BUF(state, 0), BUF(state, 1), BUF(state, 2), BUF(state, 3)};
    float *line[8], *lap[8];
    for (int k = 0; k < 8; k++) {
        line[k] = BUF(state, 7 + k / 2) + (k & 1) * 4096;
        lap[k] = BUF(state, 4 + k / 4) + (k & 3) * 128;
    }
    float decay = state[0] * (1.0f / 0.93f), damp = state[1];
    decay = decay < 0.0f ? 0.0f : decay > 1.0f ? 1.0f : decay;
    damp = damp < 0.0f ? 0.0f : damp > 1.0f ? 1.0f : damp;
    float rt60 = 0.25f + 2.25f * decay, lpc = 0.9f - 0.7f * damp, g[8];
    unsigned len[8];
    for (int k = 0; k < 8; k++) {
        float l = (float)line_len[k] * rp->size;
        len[k] = l < 64.0f ? 64u : l > 4000.0f ? 4000u : (unsigned)l;     /* each line has 4096 floats */
        g[k] = exp2_fast(-3.0f * 3.321928f * (float)(len[k] + line_ap_len[k]) / (rt60 * FS));
    }
    float depth = rp->mod, er_lvl = rp->early, side = rp->width;

    unsigned ep = S->er_pos, ip[4], lpos[8], apos[8];
    float lp[8];
    uint32_t lfo[4] = {S->lfo[0], S->lfo[1], S->lfo[2], S->lfo[3]};
    for (int k = 0; k < 4; k++)
        ip[k] = S->in_ap_pos[k];
    for (int k = 0; k < 8; k++) {
        lpos[k] = S->line_pos[k];
        if (lpos[k] >= len[k])
            lpos[k] = 0;                     /* Size turned down: wrap into the shorter line */
        apos[k] = S->line_ap_pos[k];
        lp[k] = S->lp[k];
    }
    for (int i = 0; i < n; i++) {
        float x = in[i];
        er[ep] = x;
        float el = 0.0f, erv = 0.0f;
        for (int t = 0; t < ER_TAPS; t++) {
            el += er_gain[t] * er[(ep - er_tap_l[t]) & (ER_LEN - 1)];
            erv += er_gain[t] * er[(ep - er_tap_r[t]) & (ER_LEN - 1)];
        }
        ep = (ep + 1) & (ER_LEN - 1);

        float d = 0.5f * (el + erv);
        for (int k = 0; k < 4; k++)
            d = allpass(in_ap[k], &ip[k], in_ap_len[k], k < 2 ? 0.75f : 0.625f, d);

        float o[8], rd[8];
        for (int k = 0; k < 8; k++)
            rd[k] = line[k][lpos[k]];
        for (int m = 0; m < 4; m++) {        /* modulated reads: delay = len - depth - wobble, interpolated */
            int k = mod_line[m];
            lfo[m] += lfo_inc[m];
            float off = depth * (1.0f + tri(lfo[m]));
            int io = (int)off;
            float fr = off - (float)io;
            unsigned a = lpos[k] + (unsigned)io, ln = len[k];
            a = a >= ln ? a - ln : a;
            unsigned b = a + 1 >= ln ? 0 : a + 1;
            rd[k] = line[k][a] + fr * (line[k][b] - line[k][a]);
        }
        for (int k = 0; k < 8; k++) {
            float v = rd[k];
            v = allpass(lap[k], &apos[k], line_ap_len[k], 0.5f, v);
            lp[k] += lpc * (v - lp[k]);
            o[k] = lp[k] * g[k];
        }
        /* fast Hadamard 8x8, scaled 1/sqrt(8) */
        float a0 = o[0] + o[1], a1 = o[0] - o[1], a2 = o[2] + o[3], a3 = o[2] - o[3];
        float a4 = o[4] + o[5], a5 = o[4] - o[5], a6 = o[6] + o[7], a7 = o[6] - o[7];
        float b0 = a0 + a2, b1 = a1 + a3, b2 = a0 - a2, b3 = a1 - a3;
        float b4 = a4 + a6, b5 = a5 + a7, b6 = a4 - a6, b7 = a5 - a7;
        const float sc = 0.35355339f;
        float h[8] = {(b0 + b4) * sc, (b1 + b5) * sc, (b2 + b6) * sc, (b3 + b7) * sc,
                      (b0 - b4) * sc, (b1 - b5) * sc, (b2 - b6) * sc, (b3 - b7) * sc};
        float sl = 0.0f, sr = 0.0f;
        for (int k = 0; k < 8; k++) {
            line[k][lpos[k]] = d + h[k];
            lpos[k] = lpos[k] + 1 >= len[k] ? 0 : lpos[k] + 1;
            sl += out_sign_l[k] * o[k];
            sr += out_sign_r[k] * o[k];
        }
        float mid = 0.5f * (sl + sr), sd = 0.5f * (sl - sr) * side;
        /* 1.78 = +5 dB: the 3.1.o report, Room sat about 5 dB under the Plate at the same send */
        outl[i] = 1.78f * (er_lvl * el + 0.3f * (mid + sd));
        outr[i] = 1.78f * (er_lvl * erv + 0.3f * (mid - sd));
    }
    S->er_pos = ep;
    for (int k = 0; k < 4; k++)
        S->in_ap_pos[k] = (uint16_t)ip[k];
    for (int m = 0; m < 4; m++)
        S->lfo[m] = lfo[m];
    for (int k = 0; k < 8; k++) {
        S->line_pos[k] = (uint16_t)lpos[k];
        S->line_ap_pos[k] = (uint8_t)apos[k];
        S->lp[k] = lp[k];
    }
}

