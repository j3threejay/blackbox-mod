/*
 * TAPESCAM - tape saturation and degradation. A port of Charles Vestal's TAPESCAM for Schwung (Ableton Move),
 * github.com/charlesvestal/schwung-tapescam, src/dsp/tapescam.c, version 0.5.5.
 *
 * MIT License
 *
 * Copyright (c) 2025 Charles Vestal
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
 * documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
 * rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
 * persons to whom the Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
 * Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
 * WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
 * COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
 * OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 *
 * What changed for the Blackbox (bank 2, leaf DSP: it calls nothing outside this file):
 *  - The chain, its order, every constant and every smoothing step are his. GainStage -> TapeSat -> WowFlutter ->
 *    Hiss -> Dropout -> Tone -> Comp -> Width, then Output and the final tanh.
 *  - No heap: the instance and both 2048-sample wow / flutter lines live in a block the caller owns (Prism's memory:
 *    only one Master FX runs at a time). magic != TS_MAGIC = a fresh instance, set up exactly as his create.
 *  - No strings: the host hands the eleven settings as numbers every block; a setting that changed since the last
 *    block goes through the same setter his set_param calls, in his order.
 *  - No libm (the firmware has none): tanh, sin, cos, exp, pow, sqrt are local approximations (errors around 1e-6
 *    or better); test_tapescam.py holds the whole effect against his own code compiled on the Mac.
 *  - Processing runs in 128-frame chunks, his control-update granularity on Move.
 *  - Float in, float out (the Blackbox's mix bus, full scale 1.0): no int16 round trip.
 */
#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2 has room; speed matters here */
#include <stdint.h>
#include "tapescam.h"

#define SAMPLE_RATE 48000.0f
#define kTwoPi 6.283185307179586476925286766559f
#define kPi 3.14159265358979323846f
#define kMaxDelaySamples 2048
#define kBaseDelayMsL 5.0f
#define kBaseDelayMsR 5.5f
#define kMaxAgeDriftDepthSec 0.0015f
#define kMaxSpeedFlutterDepthSec 0.0006f
#define CHUNK 128
#define TS_MAGIC 0x54534331u   /* "1CST" */

/* ---- math without libm ---- */

static inline float ts_abs(float x) { return x < 0.0f ? -x : x; }
static inline float ts_min(float a, float b) { return a < b ? a : b; }
static inline float ts_max(float a, float b) { return a > b ? a : b; }
static inline float Clamp(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

static inline float ts_sqrt(float x)
{
    float r;
    __asm__("vsqrt.f32 %0, %1" : "=t"(r) : "t"(x));
    return r;
}

/* 2^x: the nearest integer into the exponent, 2^f on [-0.5, 0.5] by its Taylor series to f^7 (rel. error ~1e-7) */
static float ts_exp2(float x)
{
    if (x < -126.0f)
        return 0.0f;
    if (x > 127.0f)
        x = 127.0f;
    int i = (int)(x + (x >= 0.0f ? 0.5f : -0.5f));
    float f = x - (float)i;
    float p = 1.525273380405984e-5f;
    p = p * f + 1.540353039338161e-4f;
    p = p * f + 1.333355814642844e-3f;
    p = p * f + 9.618129107628477e-3f;
    p = p * f + 5.550410866482158e-2f;
    p = p * f + 2.402265069591007e-1f;
    p = p * f + 6.931471805599453e-1f;
    p = p * f + 1.0f;
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

/* log2(x), x > 0: exponent + a polynomial in the mantissa on [1, 2) (abs. error < 1e-6) */
static float ts_log2(float x)
{
    union { float f; uint32_t u; } v = {x};
    int e = (int)((v.u >> 23) & 0xff) - 127;
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;
    float m = v.f;                                       /* 1 .. 2 */
    float t = (m - 1.0f) / (m + 1.0f), t2 = t * t;       /* log2(m) = 2/ln2 * atanh(t) */
    float s = t * (2.885390081777927f + t2 * (0.961796693925976f + t2 * (0.577078016355585f
              + t2 * (0.412198583111132f + t2 * 0.320598898597912f))));
    return (float)e + s;
}

static inline float ts_exp(float x) { return ts_exp2(x * 1.4426950408889634f); }
static inline float ts_pow(float b, float e) { return b <= 0.0f ? 0.0f : ts_exp2(e * ts_log2(b)); }
static inline float dBToLin(float dB) { return ts_exp2(dB * 0.16609640474436813f); }   /* 10^(dB/20) */

/* sin(x) for any x: reduce to [-pi, pi], then fold to [-pi/2, pi/2] and a degree-11 odd polynomial */
static float ts_sin(float x)
{
    float k = x * (1.0f / kTwoPi);
    int n = (int)(k + (k >= 0.0f ? 0.5f : -0.5f));
    x -= (float)n * kTwoPi;
    if (x > 0.5f * kPi)
        x = kPi - x;
    else if (x < -0.5f * kPi)
        x = -kPi - x;
    float x2 = x * x;
    return x * (1.0f + x2 * (-1.666666666666e-1f + x2 * (8.333333333e-3f + x2 * (-1.984126984e-4f
           + x2 * (2.755731922e-6f + x2 * -2.505210838e-8f)))));
}

static inline float ts_cos(float x) { return ts_sin(x + 0.5f * kPi); }

/* sin(2 pi ph) for ph in [0, 1) (the wow / flutter phases): fold to [-1/4, 1/4] of a turn, same polynomial */
static inline float ts_sin_turn(float ph)
{
    float x = ph > 0.5f ? ph - 1.0f : ph;               /* -1/2 .. 1/2 */
    if (x > 0.25f)
        x = 0.5f - x;
    else if (x < -0.25f)
        x = -0.5f - x;
    x *= kTwoPi;
    float x2 = x * x;
    return x * (1.0f + x2 * (-1.666666666666e-1f + x2 * (8.333333333e-3f + x2 * (-1.984126984e-4f
           + x2 * (2.755731922e-6f + x2 * -2.505210838e-8f)))));
}

/* tanh: 1 - 2 / (e^2|x| + 1), odd, saturating. Its own e^2|x| (argument 0 .. 26, so no range checks; the series
   to f^6 on [-0.5, 0.5] is good to ~1.2e-7 relative): it runs six times a frame, the hottest code here. */
static inline float ts_tanh(float x)
{
    float a = x < 0.0f ? -x : x;
    if (a > 9.0f)
        return x < 0.0f ? -1.0f : 1.0f;
    float y = a * 2.8853900817779268f;                   /* 2a / ln 2 */
    int i = (int)(y + 0.5f);
    float f = y - (float)i;
    float p = ((((((1.540353039338161e-4f * f + 1.333355814642844e-3f) * f + 9.618129107628477e-3f) * f
              + 5.550410866482158e-2f) * f + 2.402265069591007e-1f) * f + 6.931471805599453e-1f) * f + 1.0f);
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    float t = 1.0f - 2.0f / (v.f + 1.0f);
    if (a < 0.004f)
        t = a * (1.0f - a * a * (1.0f / 3.0f));          /* small x: keep it exact to the last bits */
    return x < 0.0f ? -t : t;
}

#define tanhf ts_tanh
#define sinf ts_sin
#define cosf ts_cos
#define expf ts_exp
#define powf ts_pow
#define sqrtf ts_sqrt
#define fabsf ts_abs
#define fminf ts_min
#define fmaxf ts_max

static void zero(void *p, uint32_t bytes)
{
    uint32_t *w = (uint32_t *)p;
    for (uint32_t i = 0; i < bytes / 4; i++)
        w[i] = 0;
}

/* ============================================================================ his modules, unchanged */

typedef struct {
    float b0, b1, b2;
    float a1, a2;
    float z1, z2;
} GS_Biquad;

static void GS_BiquadSetHighpass(GS_Biquad *bq, float sampleRate, float freq, float q) {
    float w0 = kTwoPi * freq / sampleRate;
    float cosw0 = cosf(w0);
    float sinw0 = sinf(w0);
    float alpha = sinw0 / (2.0f * q);
    float b0 = (1.0f + cosw0) * 0.5f;
    float b1 = -(1.0f + cosw0);
    float b2 = (1.0f + cosw0) * 0.5f;
    float a0 = 1.0f + alpha;
    float a1 = -2.0f * cosw0;
    float a2 = 1.0f - alpha;
    bq->b0 = b0 / a0;
    bq->b1 = b1 / a0;
    bq->b2 = b2 / a0;
    bq->a1 = a1 / a0;
    bq->a2 = a2 / a0;
}

static void GS_BiquadSetLowpass(GS_Biquad *bq, float sampleRate, float freq, float q) {
    float w0 = kTwoPi * freq / sampleRate;
    float cosw0 = cosf(w0);
    float sinw0 = sinf(w0);
    float alpha = sinw0 / (2.0f * q);
    float b0 = (1.0f - cosw0) * 0.5f;
    float b1 = 1.0f - cosw0;
    float b2 = (1.0f - cosw0) * 0.5f;
    float a0 = 1.0f + alpha;
    float a1 = -2.0f * cosw0;
    float a2 = 1.0f - alpha;
    bq->b0 = b0 / a0;
    bq->b1 = b1 / a0;
    bq->b2 = b2 / a0;
    bq->a1 = a1 / a0;
    bq->a2 = a2 / a0;
}

static float GS_BiquadProcess(GS_Biquad *bq, float x) {
    float y = bq->b0 * x + bq->z1;
    bq->z1 = bq->b1 * x - bq->a1 * y + bq->z2;
    bq->z2 = bq->b2 * x - bq->a2 * y;
    return y;
}

static float WF_InterpolateCubic(const float *buf, int size, float index) {
    unsigned idx1 = (unsigned)index;                     /* index >= 0 here: the cast is floor; size is 2^11 */
    float frac = index - (float)idx1;
    unsigned m = (unsigned)size - 1u;
    float y0 = buf[(idx1 - 1u) & m], y1 = buf[idx1 & m], y2 = buf[(idx1 + 1u) & m], y3 = buf[(idx1 + 2u) & m];
    float c0 = y1;
    float c1 = 0.5f * (y2 - y0);
    float c2 = y0 - 2.5f * y1 + 2.0f * y2 - 0.5f * y3;
    float c3 = 0.5f * (y3 - y0) + 1.5f * (y1 - y2);
    return ((c3 * frac + c2) * frac + c1) * frac + c0;
}

typedef struct {
    float b0, b1, b2, a1, a2, z1, z2;
} ToneBiquad;

static void Tone_ComputeShelf(ToneBiquad *state, float gainDb, float cutoffHz, int highShelf, float sampleRate) {
    float A = powf(10.0f, gainDb / 40.0f);
    float w0 = kTwoPi * cutoffHz / sampleRate;
    float cosw0 = cosf(w0), sinw0 = sinf(w0);
    float sqrtA = sqrtf(A);
    float alpha = sinw0 / 2.0f * sqrtf(2.0f);
    float b0, b1, b2, a0, a1, a2;
    if (!highShelf) {
        b0 = A * ((A + 1.0f) - (A - 1.0f) * cosw0 + 2.0f * sqrtA * alpha);
        b1 = 2.0f * A * ((A - 1.0f) - (A + 1.0f) * cosw0);
        b2 = A * ((A + 1.0f) - (A - 1.0f) * cosw0 - 2.0f * sqrtA * alpha);
        a0 = (A + 1.0f) + (A - 1.0f) * cosw0 + 2.0f * sqrtA * alpha;
        a1 = -2.0f * ((A - 1.0f) + (A + 1.0f) * cosw0);
        a2 = (A + 1.0f) + (A - 1.0f) * cosw0 - 2.0f * sqrtA * alpha;
    } else {
        b0 = A * ((A + 1.0f) + (A - 1.0f) * cosw0 + 2.0f * sqrtA * alpha);
        b1 = -2.0f * A * ((A - 1.0f) + (A + 1.0f) * cosw0);
        b2 = A * ((A + 1.0f) + (A - 1.0f) * cosw0 - 2.0f * sqrtA * alpha);
        a0 = (A + 1.0f) - (A - 1.0f) * cosw0 + 2.0f * sqrtA * alpha;
        a1 = 2.0f * ((A - 1.0f) - (A + 1.0f) * cosw0);
        a2 = (A + 1.0f) - (A - 1.0f) * cosw0 - 2.0f * sqrtA * alpha;
    }
    float invA0 = 1.0f / a0;
    state->b0 = b0 * invA0;
    state->b1 = b1 * invA0;
    state->b2 = b2 * invA0;
    state->a1 = a1 * invA0;
    state->a2 = a2 * invA0;
}

static inline float Tone_ProcessBiquad(ToneBiquad *bq, float x) {
    float y = x * bq->b0 + bq->z1;
    bq->z1 = x * bq->b1 + bq->z2 - bq->a1 * y;
    bq->z2 = x * bq->b2 - bq->a2 * y;
    return y;
}

typedef struct {
    uint32_t magic;
    struct tapescam_params last;     /* what the setters were last run with */

    float param_input, param_drive, param_color, param_wobble, param_tone, param_output, param_outputLevelLin,
          param_noise;
    int param_age, param_speed, param_compression, param_widen;

    float gs_trimGainLin, gs_channelGainLin, gs_masterVolLin, gs_driveNorm, gs_character, gs_characterDriveScale,
          gs_stage1Softness, gs_stage2Softness, gs_stage2Asymmetry;
    GS_Biquad gs_preHP[2], gs_preLP[2], gs_postLP[2];

    float sat_targetDrive, sat_smoothedDrive, sat_factor;

    int writeIndex;
    float wf_targetAmount, wf_smoothedAmount, wf_activationRamp, wf_crossfadeGain, wf_depthShape, wf_slewAlpha,
          wf_wowAmount, wf_flutterAmount, wf_wowRateHz, wf_flutterRateHz, wf_wowPhaseL, wf_wowPhaseR, wf_fltPhaseL,
          wf_fltPhaseR, wf_readStateL, wf_readStateR, wf_baseDelaySamplesL, wf_baseDelaySamplesR, wf_wowNoiseStateL,
          wf_wowNoiseStateR, wf_flutterNoiseStateL, wf_flutterNoiseStateR;
    uint32_t randState;

    ToneBiquad tone_lowShelfL, tone_lowShelfR, tone_highShelfL, tone_highShelfR;
    float tone_targetAmount, tone_smoothedAmount, tone_bassGainDb, tone_trebleGainDb;

    float hiss_targetAmount, hiss_smoothedAmount, hiss_levelLin, hiss_noiseColorFactor;
    float hiss_pinkState[2][7];

    int comp_mode;
    float comp_envelopeL, comp_envelopeR, comp_smoothedGainL, comp_smoothedGainR, comp_attackCoeff, comp_releaseCoeff,
          comp_threshold, comp_ratio, comp_makeupGain, comp_maxBoost;

    float gs_headroomAdjDb, mod_saturationMul, mod_wowDepthScale, mod_flutterDepthScale;
    float gs_preHpCutHz, gs_preLpCutHz, gs_postLpCutHz;
    GS_Biquad sat_hfRolloff[2];
    float sat_hfRolloffCutoff;

    float wf_baseAgeDriftDepth, wf_baseSpeedFlutterDepth, wf_ageDriftAlpha, wf_flutterDriftAlpha, wf_driftL, wf_driftR,
          wf_flutterJitL, wf_flutterJitR, wf_depthMultiplier, wf_wowRandomness, wf_flutterTurbulence;
    float hiss_stereoBlend, wf_stereoBlend;

    struct {
        int active, stage, stage_samples, attack_samples, hold_samples, release_samples;
        float min_gain, env;
    } dropout_state[2];
    float dropout_rate_hz, dropout_depth_min_db, dropout_depth_max_db, dropout_dur_min_ms, dropout_dur_max_ms,
          dropout_cluster_prob, dropout_mono_link, dropout_min_rest_sec, dropout_rest_samples, dropout_cluster_window;

    float delayBufL[kMaxDelaySamples];
    float delayBufR[kMaxDelaySamples];
} tapescam_instance_t;

static void v2_GS_SetSpeedMode(tapescam_instance_t *inst, int speed, float sampleRate) {
    switch (speed) {
        case 0: inst->gs_preHpCutHz = 144.0f; inst->gs_preLpCutHz = 5720.0f; inst->gs_postLpCutHz = 17500.0f; break;
        case 1: inst->gs_preHpCutHz = 160.0f; inst->gs_preLpCutHz = 4680.0f; inst->gs_postLpCutHz = 14000.0f; break;
        case 2: inst->gs_preHpCutHz = 112.0f; inst->gs_preLpCutHz = 3380.0f; inst->gs_postLpCutHz = 9000.0f; break;
        default: inst->gs_preHpCutHz = 144.0f; inst->gs_preLpCutHz = 5720.0f; inst->gs_postLpCutHz = 17500.0f; break;
    }
    for (int ch = 0; ch < 2; ch++) {
        GS_BiquadSetHighpass(&inst->gs_preHP[ch], sampleRate, inst->gs_preHpCutHz, 0.7071f);
        GS_BiquadSetLowpass(&inst->gs_preLP[ch], sampleRate, inst->gs_preLpCutHz, 0.7071f);
        GS_BiquadSetLowpass(&inst->gs_postLP[ch], sampleRate, inst->gs_postLpCutHz, 0.7071f);
    }
}

static void v2_GS_Init(tapescam_instance_t *inst, float sampleRate) {
    inst->gs_trimGainLin = 1.0f;
    inst->gs_channelGainLin = 1.0f;
    inst->gs_masterVolLin = 1.0f;
    inst->gs_driveNorm = 0.0f;
    inst->gs_character = 0.0f;
    inst->gs_characterDriveScale = 1.0f;
    inst->gs_stage1Softness = 1.0f;
    inst->gs_stage2Softness = 1.2f;
    inst->gs_stage2Asymmetry = 0.05f;
    for (int ch = 0; ch < 2; ch++) {
        zero(&inst->gs_preHP[ch], sizeof(GS_Biquad));
        zero(&inst->gs_preLP[ch], sizeof(GS_Biquad));
        zero(&inst->gs_postLP[ch], sizeof(GS_Biquad));
        inst->gs_preHP[ch].b0 = 1.0f;
        inst->gs_preLP[ch].b0 = 1.0f;
        inst->gs_postLP[ch].b0 = 1.0f;
    }
    v2_GS_SetSpeedMode(inst, 0, sampleRate);
}

static void v2_GS_SetParams(tapescam_instance_t *inst, float drive, float color) {
    float driveNorm = Clamp(drive, 0.0f, 1.0f);
    float driveShaped = driveNorm * driveNorm;
    float colorNorm = Clamp(color, 0.0f, 1.0f);
    float trimDb = -2.0f + driveShaped * 34.0f;
    float channelDb = -2.0f + driveNorm * 26.0f;
    inst->gs_trimGainLin = dBToLin(trimDb + inst->gs_headroomAdjDb);
    inst->gs_channelGainLin = dBToLin(channelDb + inst->gs_headroomAdjDb);
    inst->gs_driveNorm = driveNorm;
    inst->gs_character = colorNorm;
    inst->gs_characterDriveScale = 0.8f + 1.2f * colorNorm;
    inst->gs_stage1Softness = 0.8f + 0.4f * (1.0f - colorNorm);
    inst->gs_stage2Softness = 1.05f + 1.1f * colorNorm;
    inst->gs_stage2Asymmetry = 0.02f + 0.08f * colorNorm;
}

static void v2_GS_SetOutputLevel(tapescam_instance_t *inst, float level) {
    float levelDb = -12.0f + level * 18.0f;
    inst->param_outputLevelLin = dBToLin(levelDb);
    inst->gs_masterVolLin = 1.0f;
}

static void v2_GS_AdjustHeadroom(tapescam_instance_t *inst, float headroomDb) {
    inst->gs_headroomAdjDb = Clamp(headroomDb, -12.0f, 6.0f);
}

static float v2_GS_ApplyClipping(tapescam_instance_t *inst, float x, float softness) {
    float drive = 1.0f + inst->gs_driveNorm * inst->gs_characterDriveScale;
    float v = x * drive;
    v = tanhf(v * softness);
    float asymBase = 0.01f + 0.03f * inst->gs_character;
    v += asymBase * v * v * (v >= 0.0f ? 1.0f : -1.0f);
    return v;
}

static void v2_GS_Process(tapescam_instance_t *inst, float *left, float *right, int size) {
    for (int i = 0; i < size; i++) {
        float stage1InL = left[i] * inst->gs_trimGainLin;
        float stage1InR = right[i] * inst->gs_trimGainLin;
        float stage1OutL = v2_GS_ApplyClipping(inst, stage1InL, inst->gs_stage1Softness);
        float stage1OutR = v2_GS_ApplyClipping(inst, stage1InR, inst->gs_stage1Softness);
        float preEqL = GS_BiquadProcess(&inst->gs_preLP[0], GS_BiquadProcess(&inst->gs_preHP[0], stage1OutL));
        float preEqR = GS_BiquadProcess(&inst->gs_preLP[1], GS_BiquadProcess(&inst->gs_preHP[1], stage1OutR));
        float stage2InL = preEqL * inst->gs_channelGainLin;
        float stage2InR = preEqR * inst->gs_channelGainLin;
        float stage2OutL = v2_GS_ApplyClipping(inst, stage2InL, inst->gs_stage2Softness);
        float stage2OutR = v2_GS_ApplyClipping(inst, stage2InR, inst->gs_stage2Softness);
        float asym0 = inst->gs_stage2Asymmetry;
        float asym1 = -inst->gs_stage2Asymmetry;
        stage2OutL += asym0 * stage2OutL * stage2OutL;
        stage2OutR += asym1 * stage2OutR * stage2OutR;
        float postL = GS_BiquadProcess(&inst->gs_postLP[0], stage2OutL);
        float postR = GS_BiquadProcess(&inst->gs_postLP[1], stage2OutR);
        left[i] = Clamp(postL * inst->gs_masterVolLin, -0.98f, 0.98f);
        right[i] = Clamp(postR * inst->gs_masterVolLin, -0.98f, 0.98f);
    }
}

static void v2_TapeSat_Init(tapescam_instance_t *inst, float sampleRate) {
    inst->sat_targetDrive = 0.0f;
    inst->sat_smoothedDrive = 0.0f;
    inst->sat_factor = 0.0f;
    inst->sat_hfRolloffCutoff = 18000.0f;
    for (int ch = 0; ch < 2; ch++) {
        zero(&inst->sat_hfRolloff[ch], sizeof(GS_Biquad));
        inst->sat_hfRolloff[ch].b0 = 1.0f;
        GS_BiquadSetLowpass(&inst->sat_hfRolloff[ch], sampleRate, inst->sat_hfRolloffCutoff, 0.7071f);
    }
}

static void v2_TapeSat_SetDrive(tapescam_instance_t *inst, float normalizedDrive) {
    float shaped = Clamp(normalizedDrive, 0.0f, 1.0f);
    shaped = powf(shaped, 0.8f);
    inst->sat_targetDrive = shaped;
}

static void v2_TapeSat_UpdateHFRolloff(tapescam_instance_t *inst, float sampleRate) {
    float drive = inst->sat_smoothedDrive;
    float cutoff = 18000.0f - drive * 8000.0f;
    if (inst->sat_hfRolloffCutoff > 0.0f && inst->sat_hfRolloffCutoff < cutoff)
        cutoff = inst->sat_hfRolloffCutoff;
    GS_BiquadSetLowpass(&inst->sat_hfRolloff[0], sampleRate, cutoff, 0.7071f);
    GS_BiquadSetLowpass(&inst->sat_hfRolloff[1], sampleRate, cutoff, 0.7071f);
}

static void v2_TapeSat_UpdateControls(tapescam_instance_t *inst) {
    float delta = inst->sat_targetDrive - inst->sat_smoothedDrive;
    inst->sat_smoothedDrive += delta * 0.3f;
    if (fabsf(inst->sat_targetDrive - inst->sat_smoothedDrive) < 1e-4f)
        inst->sat_smoothedDrive = inst->sat_targetDrive;
    inst->sat_factor = Clamp(inst->sat_smoothedDrive * 1.35f * inst->mod_saturationMul, 0.0f, 2.0f);
    v2_TapeSat_UpdateHFRolloff(inst, SAMPLE_RATE);
}

static void v2_TapeSat_Process(tapescam_instance_t *inst, float *left, float *right, int size) {
    if (inst->sat_smoothedDrive < 0.01f) return;
    float satAmount = inst->sat_factor;
    if (satAmount < 0.01f) return;
    float drive = 1.0f + satAmount * 2.5f;
    for (int i = 0; i < size; i++) {
        left[i] = tanhf(left[i] * drive);
        right[i] = tanhf(right[i] * drive);
        left[i] = GS_BiquadProcess(&inst->sat_hfRolloff[0], left[i]);
        right[i] = GS_BiquadProcess(&inst->sat_hfRolloff[1], right[i]);
    }
}

static float v2_WF_NextRand(tapescam_instance_t *inst) {
    inst->randState = inst->randState * 1664525u + 1013904223u;
    return (float)inst->randState * 2.3283064365386963e-10f;
}

static float v2_WF_NextRandCentered(tapescam_instance_t *inst) {
    return v2_WF_NextRand(inst) * 2.0f - 1.0f;
}

static void v2_WF_Init(tapescam_instance_t *inst, float sampleRate) {
    zero(inst->delayBufL, sizeof inst->delayBufL);
    zero(inst->delayBufR, sizeof inst->delayBufR);
    inst->writeIndex = 0;
    inst->wf_baseDelaySamplesL = fminf(sampleRate * (kBaseDelayMsL * 0.001f), (float)kMaxDelaySamples - 4.0f);
    inst->wf_baseDelaySamplesR = fminf(sampleRate * (kBaseDelayMsR * 0.001f), (float)kMaxDelaySamples - 4.0f);
    inst->wf_readStateL = inst->wf_baseDelaySamplesL;
    inst->wf_readStateR = inst->wf_baseDelaySamplesR;
    inst->wf_targetAmount = 0.0f;
    inst->wf_smoothedAmount = 0.0f;
    inst->wf_activationRamp = 0.0f;
    inst->wf_crossfadeGain = 0.0f;
    inst->wf_depthShape = 0.0f;
    inst->wf_slewAlpha = 0.9f;
    inst->wf_wowAmount = 0.0f;
    inst->wf_flutterAmount = 0.0f;
    inst->wf_wowRateHz = 0.3f;
    inst->wf_flutterRateHz = 4.0f;
    inst->wf_wowPhaseL = 0.0f;
    inst->wf_wowPhaseR = 0.25f;
    inst->wf_fltPhaseL = 0.0f;
    inst->wf_fltPhaseR = 0.33f;
    inst->wf_wowNoiseStateL = 0.0f;
    inst->wf_wowNoiseStateR = 0.0f;
    inst->wf_flutterNoiseStateL = 0.0f;
    inst->wf_flutterNoiseStateR = 0.0f;
    inst->wf_baseAgeDriftDepth = 0.0f;
    inst->wf_baseSpeedFlutterDepth = 0.0f;
    inst->wf_ageDriftAlpha = 0.0f;
    inst->wf_flutterDriftAlpha = 0.0f;
    inst->wf_driftL = 0.0f;
    inst->wf_driftR = 0.0f;
    inst->wf_flutterJitL = 0.0f;
    inst->wf_flutterJitR = 0.0f;
    inst->wf_depthMultiplier = 1.0f;
    inst->wf_wowRandomness = 0.4f;
    inst->wf_flutterTurbulence = 0.2f;
    inst->wf_stereoBlend = 1.0f;
    inst->randState ^= (uint32_t)sampleRate;
}

static void v2_WF_SetBaselineMotion(tapescam_instance_t *inst, float ageAmount, float speedAmount) {
    inst->wf_baseAgeDriftDepth = ageAmount * kMaxAgeDriftDepthSec;
    inst->wf_baseSpeedFlutterDepth = speedAmount * kMaxSpeedFlutterDepthSec;
    inst->wf_ageDriftAlpha = (inst->wf_baseAgeDriftDepth > 0.0f) ? (0.0002f + 0.0012f * ageAmount) : 0.0f;
    inst->wf_flutterDriftAlpha = (inst->wf_baseSpeedFlutterDepth > 0.0f) ? (0.0008f + 0.0025f * speedAmount) : 0.0f;
}

static void v2_WF_SetDepthMultiplier(tapescam_instance_t *inst, float multiplier) {
    inst->wf_depthMultiplier = Clamp(multiplier, 0.5f, 2.0f);
    if (multiplier <= 0.85f) {
        inst->wf_wowRandomness = 0.2f;
        inst->wf_flutterTurbulence = 0.1f;
    } else if (multiplier <= 1.15f) {
        inst->wf_wowRandomness = 0.4f;
        inst->wf_flutterTurbulence = 0.2f;
    } else {
        inst->wf_wowRandomness = 0.75f;
        inst->wf_flutterTurbulence = 0.45f;
    }
}

static void v2_WF_SetAmount(tapescam_instance_t *inst, float amount) {
    inst->wf_targetAmount = Clamp(amount, 0.0f, 1.0f);
}

static void v2_WF_UpdateControls(tapescam_instance_t *inst) {
    inst->wf_smoothedAmount += (inst->wf_targetAmount - inst->wf_smoothedAmount) * 0.3f;
    float targetActive = (inst->wf_targetAmount > 0.0005f) ? 1.0f : 0.0f;
    inst->wf_activationRamp += (targetActive - inst->wf_activationRamp) * 0.4f;
    float amt = inst->wf_smoothedAmount * inst->wf_activationRamp;
    inst->wf_depthShape = amt * amt;
    float depthBlendWow = 0.05f + 0.95f * inst->wf_depthShape;
    float depthBlendFlutter = 0.03f + 0.97f * inst->wf_depthShape;
    float targetSlew = (amt <= 0.0005f) ? 0.97f : Clamp(0.94f - 0.28f * inst->wf_depthShape, 0.7f, 0.95f);
    inst->wf_slewAlpha += (targetSlew - inst->wf_slewAlpha) * 0.2f;
    inst->wf_wowAmount = depthBlendWow * inst->wf_activationRamp;
    inst->wf_flutterAmount = depthBlendFlutter * inst->wf_activationRamp;
}

static void v2_WF_Process(tapescam_instance_t *inst, float *inL, float *inR, float *outL, float *outR, int size,
                          float sampleRate) {
    float wowAmt = inst->wf_wowAmount * inst->wf_depthMultiplier * inst->mod_wowDepthScale;
    float flutterAmt = inst->wf_flutterAmount * inst->wf_depthMultiplier * inst->mod_flutterDepthScale;
    float invSr = 1.0f / sampleRate;
    int hasBaselineDrift = (inst->wf_ageDriftAlpha > 0.0f || inst->wf_flutterDriftAlpha > 0.0f);
    int bypassDelay = (!hasBaselineDrift && inst->wf_activationRamp < 1.0e-4f && wowAmt <= 1.0e-5f && flutterAmt <= 1.0e-5f);
    if (bypassDelay) {
        for (int i = 0; i < size; i++) {
            outL[i] = inL[i];
            outR[i] = inR[i];
            inst->delayBufL[inst->writeIndex] = inL[i];
            inst->delayBufR[inst->writeIndex] = inR[i];
            inst->writeIndex++;
            if (inst->writeIndex >= kMaxDelaySamples) inst->writeIndex = 0;
        }
        return;
    }
    float crossfadeAlpha = 0.004f;
    float crossfadeGain = inst->wf_crossfadeGain;
    float maxWowDepthSec = 0.035f;
    float maxFlutterDepthSec = 0.002f;
    float maxDevSec = 0.0042f;
    float wowRandomness = inst->wf_wowRandomness;
    float flutterTurbulence = inst->wf_flutterTurbulence;
    for (int i = 0; i < size; i++) {
        float xL = inL[i], xR = inR[i];
        float targetCrossfade = (inst->wf_activationRamp > 0.001f || hasBaselineDrift) ? 1.0f : inst->wf_activationRamp;
        crossfadeGain += (targetCrossfade - crossfadeGain) * crossfadeAlpha;
        float wowNoiseAlpha = 0.00018f * (1.0f + wowRandomness);
        float flutterNoiseAlpha = 0.00025f * (1.0f + flutterTurbulence);
        inst->wf_wowNoiseStateL += (v2_WF_NextRandCentered(inst) - inst->wf_wowNoiseStateL) * wowNoiseAlpha;
        inst->wf_wowNoiseStateR += (v2_WF_NextRandCentered(inst) - inst->wf_wowNoiseStateR) * wowNoiseAlpha;
        inst->wf_flutterNoiseStateL += (v2_WF_NextRandCentered(inst) - inst->wf_flutterNoiseStateL) * flutterNoiseAlpha;
        inst->wf_flutterNoiseStateR += (v2_WF_NextRandCentered(inst) - inst->wf_flutterNoiseStateR) * flutterNoiseAlpha;
        if (inst->wf_ageDriftAlpha > 0.0f) {
            float targetL = v2_WF_NextRandCentered(inst) * inst->wf_baseAgeDriftDepth;
            float targetR = targetL + 0.12f * v2_WF_NextRandCentered(inst) * inst->wf_baseAgeDriftDepth;
            inst->wf_driftL += (targetL - inst->wf_driftL) * inst->wf_ageDriftAlpha;
            inst->wf_driftR += (targetR - inst->wf_driftR) * inst->wf_ageDriftAlpha;
        } else {
            inst->wf_driftL *= 0.9996f;
            inst->wf_driftR *= 0.9996f;
        }
        if (inst->wf_flutterDriftAlpha > 0.0f) {
            float targetL = v2_WF_NextRandCentered(inst) * inst->wf_baseSpeedFlutterDepth;
            float targetR = targetL + 0.08f * v2_WF_NextRandCentered(inst) * inst->wf_baseSpeedFlutterDepth;
            inst->wf_flutterJitL += (targetL - inst->wf_flutterJitL) * inst->wf_flutterDriftAlpha;
            inst->wf_flutterJitR += (targetR - inst->wf_flutterJitR) * inst->wf_flutterDriftAlpha;
        } else {
            inst->wf_flutterJitL *= 0.9996f;
            inst->wf_flutterJitR *= 0.9996f;
        }
        inst->wf_wowPhaseL += inst->wf_wowRateHz * invSr;
        if (inst->wf_wowPhaseL >= 1.0f) inst->wf_wowPhaseL -= 1.0f;
        inst->wf_fltPhaseL += inst->wf_flutterRateHz * invSr;
        if (inst->wf_fltPhaseL >= 1.0f) inst->wf_fltPhaseL -= 1.0f;
        inst->wf_wowPhaseR += inst->wf_wowRateHz * 1.03f * invSr;
        if (inst->wf_wowPhaseR >= 1.0f) inst->wf_wowPhaseR -= 1.0f;
        inst->wf_fltPhaseR += inst->wf_flutterRateHz * 0.97f * invSr;
        if (inst->wf_fltPhaseR >= 1.0f) inst->wf_fltPhaseR -= 1.0f;
        float depthSlow = sqrtf(fmaxf(inst->wf_depthShape, 0.0f));
        float wowNoiseMix = Clamp(wowRandomness * (0.10f + 0.45f * depthSlow), 0.0f, 0.65f);
        float flutterNoiseMix = Clamp(flutterTurbulence * (0.12f + 0.45f * depthSlow), 0.0f, 0.7f);
        float wowShapeL = (1.0f - wowNoiseMix) * ts_sin_turn(inst->wf_wowPhaseL) + wowNoiseMix * inst->wf_wowNoiseStateL;
        float flutterShapeL = (1.0f - flutterNoiseMix) * ts_sin_turn(inst->wf_fltPhaseL) + flutterNoiseMix * inst->wf_flutterNoiseStateL;
        float wowShapeR = (1.0f - wowNoiseMix) * ts_sin_turn(inst->wf_wowPhaseR) + wowNoiseMix * inst->wf_wowNoiseStateR;
        float flutterShapeR = (1.0f - flutterNoiseMix) * ts_sin_turn(inst->wf_fltPhaseR) + flutterNoiseMix * inst->wf_flutterNoiseStateR;
        float wowDepthL = maxWowDepthSec * wowAmt;
        float wowDepthR = maxWowDepthSec * wowAmt * 1.03f;
        float flutterDepthL = maxFlutterDepthSec * flutterAmt;
        float flutterDepthR = maxFlutterDepthSec * flutterAmt * 0.97f;
        float devSecL = inst->wf_driftL + inst->wf_flutterJitL + wowDepthL * wowShapeL + flutterDepthL * flutterShapeL;
        float devSecR = inst->wf_driftR + inst->wf_flutterJitR + wowDepthR * wowShapeR + flutterDepthR * flutterShapeR;
        float devSamplesL = devSecL * sampleRate;
        float devSamplesR = devSecR * sampleRate;
        float maxDevSamples = maxDevSec * sampleRate;
        devSamplesL = Clamp(devSamplesL, -maxDevSamples, maxDevSamples);
        devSamplesR = Clamp(devSamplesR, -maxDevSamples, maxDevSamples);
        float targetSamplesL = fmaxf(inst->wf_baseDelaySamplesL + devSamplesL, 0.0002f * sampleRate);
        float targetSamplesR = fmaxf(inst->wf_baseDelaySamplesR + devSamplesR, 0.0002f * sampleRate);
        inst->wf_readStateL = inst->wf_slewAlpha * inst->wf_readStateL + (1.0f - inst->wf_slewAlpha) * targetSamplesL;
        inst->wf_readStateR = inst->wf_slewAlpha * inst->wf_readStateR + (1.0f - inst->wf_slewAlpha) * targetSamplesR;
        float readIndexL = (float)inst->writeIndex - inst->wf_readStateL;
        float readIndexR = (float)inst->writeIndex - inst->wf_readStateR;
        if (readIndexL < 0.0f) readIndexL += (float)kMaxDelaySamples;
        if (readIndexR < 0.0f) readIndexR += (float)kMaxDelaySamples;
        float delayedL = WF_InterpolateCubic(inst->delayBufL, kMaxDelaySamples, readIndexL);
        float delayedR = WF_InterpolateCubic(inst->delayBufR, kMaxDelaySamples, readIndexR);
        inst->delayBufL[inst->writeIndex] = xL;
        inst->delayBufR[inst->writeIndex] = xR;
        inst->writeIndex++;
        if (inst->writeIndex >= kMaxDelaySamples) inst->writeIndex = 0;
        float wet = crossfadeGain, dry = 1.0f - wet;
        outL[i] = dry * xL + wet * delayedL;
        outR[i] = dry * xR + wet * delayedR;
    }
    inst->wf_crossfadeGain = crossfadeGain;
}

static void v2_Tone_Init(tapescam_instance_t *inst) {
    zero(&inst->tone_lowShelfL, sizeof(ToneBiquad));
    zero(&inst->tone_lowShelfR, sizeof(ToneBiquad));
    zero(&inst->tone_highShelfL, sizeof(ToneBiquad));
    zero(&inst->tone_highShelfR, sizeof(ToneBiquad));
    inst->tone_lowShelfL.b0 = inst->tone_lowShelfR.b0 = 1.0f;
    inst->tone_highShelfL.b0 = inst->tone_highShelfR.b0 = 1.0f;
    inst->tone_targetAmount = 0.5f;
    inst->tone_smoothedAmount = 0.5f;
}

static void v2_Tone_SetAmount(tapescam_instance_t *inst, float amount) {
    inst->tone_targetAmount = Clamp(amount, 0.0f, 1.0f);
}

static void v2_Tone_UpdateControls(tapescam_instance_t *inst, float sampleRate) {
    inst->tone_smoothedAmount += (inst->tone_targetAmount - inst->tone_smoothedAmount) * 0.5f;
    float normalized = inst->tone_smoothedAmount * 2.0f - 1.0f;
    float shaped = normalized * (1.0f + 0.9f * fabsf(normalized));
    inst->tone_bassGainDb = -shaped * 15.0f;
    inst->tone_trebleGainDb = shaped * 15.0f;
    Tone_ComputeShelf(&inst->tone_lowShelfL, inst->tone_bassGainDb, 120.0f, 0, sampleRate);
    Tone_ComputeShelf(&inst->tone_lowShelfR, inst->tone_bassGainDb, 120.0f, 0, sampleRate);
    Tone_ComputeShelf(&inst->tone_highShelfL, inst->tone_trebleGainDb, 6000.0f, 1, sampleRate);
    Tone_ComputeShelf(&inst->tone_highShelfR, inst->tone_trebleGainDb, 6000.0f, 1, sampleRate);
}

static void v2_Tone_Process(tapescam_instance_t *inst, float *bufL, float *bufR, int size) {
    for (int i = 0; i < size; i++) {
        float y = Tone_ProcessBiquad(&inst->tone_lowShelfL, bufL[i]);
        bufL[i] = Tone_ProcessBiquad(&inst->tone_highShelfL, y);
        y = Tone_ProcessBiquad(&inst->tone_lowShelfR, bufR[i]);
        bufR[i] = Tone_ProcessBiquad(&inst->tone_highShelfR, y);
    }
}

static void v2_Hiss_Init(tapescam_instance_t *inst) {
    inst->hiss_targetAmount = 0.0f;
    inst->hiss_smoothedAmount = 0.0f;
    inst->hiss_levelLin = 0.0f;
    inst->hiss_noiseColorFactor = 0.0f;
    inst->hiss_stereoBlend = 1.0f;
    zero(inst->hiss_pinkState, sizeof inst->hiss_pinkState);
}

static void v2_Hiss_SetAmount(tapescam_instance_t *inst, float amount) {
    inst->hiss_targetAmount = Clamp(amount, 0.0f, 1.0f);
}

static void v2_Hiss_UpdateControls(tapescam_instance_t *inst) {
    float delta = inst->hiss_targetAmount - inst->hiss_smoothedAmount;
    inst->hiss_smoothedAmount += delta * 0.5f;
    float amt = inst->hiss_smoothedAmount;
    if (amt < 0.0005f) {
        inst->hiss_levelLin = 0.0f;
        inst->hiss_noiseColorFactor = 0.0f;
        return;
    }
    float hissDb = -60.0f + amt * 54.0f;
    inst->hiss_levelLin = dBToLin(hissDb);
    inst->hiss_noiseColorFactor = amt;
}

static float v2_Hiss_ProcessPink(tapescam_instance_t *inst, int ch, float white) {
    float *s = inst->hiss_pinkState[ch];
    s[0] = 0.99886f * s[0] + white * 0.0555179f;
    s[1] = 0.99332f * s[1] + white * 0.0750759f;
    s[2] = 0.96900f * s[2] + white * 0.1538520f;
    s[3] = 0.86650f * s[3] + white * 0.3104856f;
    s[4] = 0.55000f * s[4] + white * 0.5329522f;
    s[5] = -0.7616f * s[5] - white * 0.0168980f;
    float pink = s[0] + s[1] + s[2] + s[3] + s[4] + s[5] + s[6] + white * 0.5362f;
    s[6] = white * 0.115926f;
    return pink * 0.11f;
}

static void v2_Hiss_Process(tapescam_instance_t *inst, float *left, float *right, int size) {
    if (inst->hiss_levelLin <= 0.0f) return;
    float colorFactor = inst->hiss_noiseColorFactor;
    float level = inst->hiss_levelLin;
    float blend = inst->hiss_stereoBlend;
    for (int i = 0; i < size; i++) {
        float whiteL = v2_WF_NextRandCentered(inst);
        float whiteR = v2_WF_NextRandCentered(inst);
        float noiseL = whiteL;
        float noiseR = whiteR;
        if (colorFactor >= 0.001f) {
            noiseL = (1.0f - colorFactor) * whiteL + colorFactor * v2_Hiss_ProcessPink(inst, 0, whiteL);
            noiseR = (1.0f - colorFactor) * whiteR + colorFactor * v2_Hiss_ProcessPink(inst, 1, whiteR);
        }
        float monoNoise = 0.5f * (noiseL + noiseR);
        noiseL = monoNoise + blend * (noiseL - monoNoise);
        noiseR = monoNoise + blend * (noiseR - monoNoise);
        left[i] += noiseL * level;
        right[i] += noiseR * level;
    }
}

static void v2_Comp_SetMode(tapescam_instance_t *inst, int mode, float sampleRate) {
    inst->comp_mode = mode < 0 ? 0 : (mode > 2 ? 2 : mode);
    float attackMs = inst->comp_mode == 2 ? 2.0f : 5.0f;
    float releaseMs = inst->comp_mode == 2 ? 800.0f : 400.0f;
    inst->comp_attackCoeff = expf(-1.0f / (sampleRate * attackMs * 0.001f));
    inst->comp_releaseCoeff = expf(-1.0f / (sampleRate * releaseMs * 0.001f));
    switch (inst->comp_mode) {
        case 0: inst->comp_threshold = 1.0f; inst->comp_ratio = 1.0f; inst->comp_makeupGain = 1.0f; inst->comp_maxBoost = 1.0f; break;
        case 1: inst->comp_threshold = 0.45f; inst->comp_ratio = 8.0f; inst->comp_makeupGain = 0.7f; inst->comp_maxBoost = 6.0f; break;
        case 2: inst->comp_threshold = 0.65f; inst->comp_ratio = 18.0f; inst->comp_makeupGain = 0.5f; inst->comp_maxBoost = 12.0f; break;
    }
}

static void v2_Comp_Init(tapescam_instance_t *inst, float sampleRate) {
    inst->comp_mode = 0;
    inst->comp_envelopeL = 0.0f;
    inst->comp_envelopeR = 0.0f;
    inst->comp_smoothedGainL = 1.0f;
    inst->comp_smoothedGainR = 1.0f;
    v2_Comp_SetMode(inst, 0, sampleRate);
}

static void v2_Comp_Process(tapescam_instance_t *inst, float *left, float *right, int size) {
    if (inst->comp_mode == 0) return;
    for (int i = 0; i < size; i++) {
        float inL = left[i];
        float inR = right[i];
        float absL = fabsf(inL);
        float absR = fabsf(inR);
        float envCoeffL = (absL > inst->comp_envelopeL) ? inst->comp_attackCoeff : inst->comp_releaseCoeff;
        float envCoeffR = (absR > inst->comp_envelopeR) ? inst->comp_attackCoeff : inst->comp_releaseCoeff;
        inst->comp_envelopeL = envCoeffL * inst->comp_envelopeL + (1.0f - envCoeffL) * absL;
        inst->comp_envelopeR = envCoeffR * inst->comp_envelopeR + (1.0f - envCoeffR) * absR;
        float targetGainL, targetGainR;
        if (inst->comp_envelopeL < inst->comp_threshold) {
            float reduction = inst->comp_threshold - inst->comp_envelopeL;
            float normalizedReduction = reduction / inst->comp_threshold;
            targetGainL = (1.0f + (inst->comp_maxBoost - 1.0f) * normalizedReduction) * inst->comp_makeupGain;
        } else {
            targetGainL = inst->comp_makeupGain;
        }
        if (inst->comp_envelopeR < inst->comp_threshold) {
            float reduction = inst->comp_threshold - inst->comp_envelopeR;
            float normalizedReduction = reduction / inst->comp_threshold;
            targetGainR = (1.0f + (inst->comp_maxBoost - 1.0f) * normalizedReduction) * inst->comp_makeupGain;
        } else {
            targetGainR = inst->comp_makeupGain;
        }
        float smoothCoeffL = (targetGainL < inst->comp_smoothedGainL) ? 0.2f : 0.000125f;
        float smoothCoeffR = (targetGainR < inst->comp_smoothedGainR) ? 0.2f : 0.000125f;
        inst->comp_smoothedGainL += (targetGainL - inst->comp_smoothedGainL) * smoothCoeffL;
        inst->comp_smoothedGainR += (targetGainR - inst->comp_smoothedGainR) * smoothCoeffR;
        float maxAllowedGain = inst->comp_mode == 2 ? 15.0f : 8.0f;
        float cappedGainL = fminf(inst->comp_smoothedGainL, maxAllowedGain);
        float cappedGainR = fminf(inst->comp_smoothedGainR, maxAllowedGain);
        float maxGainL = absL > 0.001f ? 0.9f / absL : cappedGainL;
        float maxGainR = absR > 0.001f ? 0.9f / absR : cappedGainR;
        left[i] = inL * fminf(cappedGainL, maxGainL);
        right[i] = inR * fminf(cappedGainR, maxGainR);
    }
}

static void v2_Dropout_Init(tapescam_instance_t *inst) {
    for (int ch = 0; ch < 2; ch++) {
        inst->dropout_state[ch].active = 0;
        inst->dropout_state[ch].stage = 0;
        inst->dropout_state[ch].stage_samples = 0;
        inst->dropout_state[ch].attack_samples = 0;
        inst->dropout_state[ch].hold_samples = 0;
        inst->dropout_state[ch].release_samples = 0;
        inst->dropout_state[ch].min_gain = 1.0f;
        inst->dropout_state[ch].env = 1.0f;
    }
    inst->dropout_rate_hz = 0.0f;
    inst->dropout_depth_min_db = 0.0f;
    inst->dropout_depth_max_db = 0.0f;
    inst->dropout_dur_min_ms = 0.0f;
    inst->dropout_dur_max_ms = 0.0f;
    inst->dropout_cluster_prob = 0.0f;
    inst->dropout_mono_link = 0.0f;
    inst->dropout_min_rest_sec = 0.0f;
    inst->dropout_rest_samples = 0.0f;
    inst->dropout_cluster_window = 0.0f;
}

static void v2_Dropout_SetParamsForAge(tapescam_instance_t *inst, int age) {
    switch (age) {
        case 0:
            inst->dropout_rate_hz = 0.0f; inst->dropout_depth_min_db = 0.0f; inst->dropout_depth_max_db = 0.0f;
            inst->dropout_dur_min_ms = 0.0f; inst->dropout_dur_max_ms = 0.0f; inst->dropout_cluster_prob = 0.0f;
            inst->dropout_mono_link = 1.0f; inst->dropout_min_rest_sec = 0.0f;
            break;
        case 1:
            inst->dropout_rate_hz = 0.08f; inst->dropout_depth_min_db = -2.5f; inst->dropout_depth_max_db = -0.8f;
            inst->dropout_dur_min_ms = 40.0f; inst->dropout_dur_max_ms = 120.0f; inst->dropout_cluster_prob = 0.10f;
            inst->dropout_mono_link = 0.9f; inst->dropout_min_rest_sec = 1.5f;
            break;
        case 2:
            inst->dropout_rate_hz = 0.18f; inst->dropout_depth_min_db = -6.0f; inst->dropout_depth_max_db = -2.5f;
            inst->dropout_dur_min_ms = 60.0f; inst->dropout_dur_max_ms = 220.0f; inst->dropout_cluster_prob = 0.15f;
            inst->dropout_mono_link = 0.7f; inst->dropout_min_rest_sec = 0.8f;
            break;
    }
    inst->dropout_rest_samples = inst->dropout_min_rest_sec * SAMPLE_RATE;
    inst->dropout_cluster_window = 0.0f;
}

static void v2_Dropout_TriggerEvent(tapescam_instance_t *inst, int ch) {
    float depthDb = inst->dropout_depth_min_db + v2_WF_NextRand(inst) * (inst->dropout_depth_max_db - inst->dropout_depth_min_db);
    float minGain = dBToLin(depthDb);
    float durMs = inst->dropout_dur_min_ms + v2_WF_NextRand(inst) * (inst->dropout_dur_max_ms - inst->dropout_dur_min_ms);
    int totalSamples = (int)(durMs * 0.001f * SAMPLE_RATE);
    int attackSamples = totalSamples / 5;
    int holdSamples = totalSamples / 2;
    int releaseSamples = totalSamples - attackSamples - holdSamples;
    inst->dropout_state[ch].active = 1;
    inst->dropout_state[ch].stage = 0;
    inst->dropout_state[ch].stage_samples = 0;
    inst->dropout_state[ch].attack_samples = attackSamples;
    inst->dropout_state[ch].hold_samples = holdSamples;
    inst->dropout_state[ch].release_samples = releaseSamples;
    inst->dropout_state[ch].min_gain = minGain;
    inst->dropout_state[ch].env = 1.0f;
}

static float v2_Dropout_AdvanceState(tapescam_instance_t *inst, int ch) {
    if (!inst->dropout_state[ch].active)
        return 1.0f;
    float env = inst->dropout_state[ch].env;
    float minGain = inst->dropout_state[ch].min_gain;
    int stage = inst->dropout_state[ch].stage;
    inst->dropout_state[ch].stage_samples++;
    if (stage == 0) {
        if (inst->dropout_state[ch].attack_samples > 0) {
            float t = (float)inst->dropout_state[ch].stage_samples / (float)inst->dropout_state[ch].attack_samples;
            env = 1.0f - t * (1.0f - minGain);
        }
        if (inst->dropout_state[ch].stage_samples >= inst->dropout_state[ch].attack_samples) {
            inst->dropout_state[ch].stage = 1;
            inst->dropout_state[ch].stage_samples = 0;
            env = minGain;
        }
    } else if (stage == 1) {
        env = minGain;
        if (inst->dropout_state[ch].stage_samples >= inst->dropout_state[ch].hold_samples) {
            inst->dropout_state[ch].stage = 2;
            inst->dropout_state[ch].stage_samples = 0;
        }
    } else {
        if (inst->dropout_state[ch].release_samples > 0) {
            float t = (float)inst->dropout_state[ch].stage_samples / (float)inst->dropout_state[ch].release_samples;
            env = minGain + t * (1.0f - minGain);
        }
        if (inst->dropout_state[ch].stage_samples >= inst->dropout_state[ch].release_samples) {
            inst->dropout_state[ch].active = 0;
            env = 1.0f;
        }
    }
    inst->dropout_state[ch].env = env;
    return env;
}

static void v2_Dropout_Process(tapescam_instance_t *inst, float *left, float *right, int size) {
    if (inst->dropout_rate_hz <= 0.0f) return;
    float triggerProb = inst->dropout_rate_hz / SAMPLE_RATE;
    for (int i = 0; i < size; i++) {
        if (inst->dropout_rest_samples > 0.0f)
            inst->dropout_rest_samples -= 1.0f;
        if (inst->dropout_cluster_window > 0.0f)
            inst->dropout_cluster_window -= 1.0f;
        if (inst->dropout_rest_samples <= 0.0f && !inst->dropout_state[0].active && !inst->dropout_state[1].active) {
            float effectiveProb = triggerProb;
            if (inst->dropout_cluster_window > 0.0f)
                effectiveProb *= (1.0f + inst->dropout_cluster_prob * 10.0f);
            if (v2_WF_NextRand(inst) < effectiveProb) {
                v2_Dropout_TriggerEvent(inst, 0);
                if (v2_WF_NextRand(inst) < inst->dropout_mono_link)
                    v2_Dropout_TriggerEvent(inst, 1);
                inst->dropout_rest_samples = inst->dropout_min_rest_sec * SAMPLE_RATE;
                inst->dropout_cluster_window = 0.3f * SAMPLE_RATE;
            }
        }
        float gainL = v2_Dropout_AdvanceState(inst, 0);
        float gainR = v2_Dropout_AdvanceState(inst, 1);
        left[i] *= gainL;
        right[i] *= gainR;
    }
}

static void v2_ApplyAgeSpeedModifiers(tapescam_instance_t *inst) {
    int age = inst->param_age;
    int speed = inst->param_speed;
    float ageNorm = Clamp(age / 2.0f, 0.0f, 1.0f);
    float ageHeadroomDb = (ageNorm - 0.5f) * 1.5f;
    float ageSatMul = 1.0f + 0.4f * ageNorm;
    float ageWowMul = 0.8f + 0.5f * ageNorm;
    v2_Dropout_SetParamsForAge(inst, age);
    float speedHeadroomDb = 0.0f, speedSatMul = 1.0f, wowDepthScale = 1.0f, flutterDepthScale = 1.0f;
    float hfRolloffCutoff = 18000.0f, speedDriftAmount = 0.3f;
    switch (speed) {
        case 0: speedHeadroomDb = 2.0f; speedSatMul = 0.9f; wowDepthScale = 0.85f; flutterDepthScale = 0.85f;
                hfRolloffCutoff = 18000.0f; speedDriftAmount = 0.15f; break;
        case 1: speedHeadroomDb = -0.5f; speedSatMul = 1.0f; wowDepthScale = 1.3f; flutterDepthScale = 1.0f;
                hfRolloffCutoff = 12000.0f; speedDriftAmount = 0.5f; break;
        case 2: speedHeadroomDb = -2.0f; speedSatMul = 1.25f; wowDepthScale = 1.8f; flutterDepthScale = 1.1f;
                hfRolloffCutoff = 8000.0f; speedDriftAmount = 1.0f; break;
    }
    float ageWowScale = 1.0f + 1.6f * ageNorm;
    float ageFlutterScale = 1.0f - 0.2f * ageNorm;
    v2_GS_AdjustHeadroom(inst, ageHeadroomDb + speedHeadroomDb);
    v2_GS_SetSpeedMode(inst, speed, SAMPLE_RATE);
    inst->mod_saturationMul = ageSatMul * speedSatMul;
    inst->sat_hfRolloffCutoff = hfRolloffCutoff;
    inst->mod_wowDepthScale = ageWowScale * wowDepthScale;
    inst->mod_flutterDepthScale = ageFlutterScale * flutterDepthScale;
    v2_WF_SetDepthMultiplier(inst, ageWowMul);
    v2_WF_SetBaselineMotion(inst, ageNorm, inst->param_wobble * speedDriftAmount);
    inst->hiss_stereoBlend = inst->param_widen ? 1.0f : 0.0f;
    inst->wf_stereoBlend = inst->param_widen ? 1.0f : 0.0f;
}

static void v2_Width_Process(tapescam_instance_t *inst, float *left, float *right, int size) {
    if (!inst->param_widen) return;
    const float width = 1.35f;
    for (int i = 0; i < size; i++) {
        float mid = 0.5f * (left[i] + right[i]);
        float side = 0.5f * (left[i] - right[i]);
        side *= width;
        left[i] = mid + side;
        right[i] = mid - side;
    }
}

/* ============================================================================ the Blackbox side */

/* his v2_create_instance, minus the heap and the log */
static void create(tapescam_instance_t *inst)
{
    zero(inst, sizeof *inst);
    inst->param_input = 0.7f;
    inst->param_drive = 0.0f;
    inst->param_color = 0.0f;
    inst->param_wobble = 0.0f;
    inst->param_tone = 0.5f;
    inst->param_output = 1.0f;
    inst->param_outputLevelLin = 1.0f;
    inst->param_noise = 0.0f;
    inst->param_age = 0;
    inst->param_speed = 0;
    inst->param_compression = 0;
    inst->param_widen = 1;
    inst->randState = 0x1234567u;
    v2_GS_Init(inst, SAMPLE_RATE);
    v2_GS_SetParams(inst, inst->param_drive, inst->param_color);
    v2_GS_SetOutputLevel(inst, inst->param_output);
    v2_TapeSat_Init(inst, SAMPLE_RATE);
    v2_TapeSat_SetDrive(inst, inst->param_color);
    v2_WF_Init(inst, SAMPLE_RATE);
    v2_WF_SetAmount(inst, inst->param_wobble);
    v2_Tone_Init(inst);
    v2_Tone_SetAmount(inst, inst->param_tone);
    v2_Hiss_Init(inst);
    v2_Hiss_SetAmount(inst, inst->param_noise);
    v2_Comp_Init(inst, SAMPLE_RATE);
    v2_Dropout_Init(inst);
    inst->gs_headroomAdjDb = 0.0f;
    inst->mod_saturationMul = 1.0f;
    inst->mod_wowDepthScale = 1.0f;
    inst->mod_flutterDepthScale = 1.0f;
    v2_ApplyAgeSpeedModifiers(inst);
    /* "last" = his defaults, so the first block runs a setter only for what differs from them */
    inst->last.input = 0.7f;
    inst->last.drive = 0.0f;
    inst->last.color = 0.0f;
    inst->last.wobble = 0.0f;
    inst->last.tone = 0.5f;
    inst->last.output = 1.0f;
    inst->last.noise = 0.0f;
    inst->last.comp = 0;
    inst->last.age = 0;
    inst->last.speed = 0;
    inst->last.widen = 1;
    inst->magic = TS_MAGIC;
}

/* his v2_set_param for every setting that changed, in the order of his set_param's branches */
static void apply(tapescam_instance_t *inst, const struct tapescam_params *p)
{
    struct tapescam_params *l = &inst->last;
    if (p->input != l->input)
        inst->param_input = Clamp(p->input, 0.0f, 1.0f);
    if (p->drive != l->drive) {
        inst->param_drive = Clamp(p->drive, 0.0f, 1.0f);
        v2_GS_SetParams(inst, inst->param_drive, inst->param_color);
    }
    if (p->color != l->color) {
        inst->param_color = Clamp(p->color, 0.0f, 1.0f);
        v2_GS_SetParams(inst, inst->param_drive, inst->param_color);
        v2_TapeSat_SetDrive(inst, inst->param_color);
    }
    if (p->wobble != l->wobble) {
        inst->param_wobble = Clamp(p->wobble, 0.0f, 1.0f);
        v2_WF_SetAmount(inst, inst->param_wobble);
    }
    if (p->tone != l->tone) {
        inst->param_tone = Clamp(p->tone, 0.0f, 1.0f);
        v2_Tone_SetAmount(inst, inst->param_tone);
    }
    if (p->output != l->output) {
        inst->param_output = Clamp(p->output, 0.0f, 1.0f);
        v2_GS_SetOutputLevel(inst, inst->param_output);
    }
    if (p->noise != l->noise) {
        inst->param_noise = Clamp(p->noise, 0.0f, 1.0f);
        v2_Hiss_SetAmount(inst, inst->param_noise);
    }
    if (p->comp != l->comp) {
        inst->param_compression = p->comp > 2u ? 2 : (int)p->comp;
        v2_Comp_SetMode(inst, inst->param_compression, SAMPLE_RATE);
    }
    if (p->age != l->age) {
        inst->param_age = p->age > 2u ? 2 : (int)p->age;
        v2_ApplyAgeSpeedModifiers(inst);
        v2_GS_SetParams(inst, inst->param_drive, inst->param_color);
    }
    if (p->speed != l->speed) {
        inst->param_speed = p->speed > 2u ? 2 : (int)p->speed;
        v2_ApplyAgeSpeedModifiers(inst);
        v2_GS_SetParams(inst, inst->param_drive, inst->param_color);
    }
    if (p->widen != l->widen) {
        inst->param_widen = p->widen ? 1 : 0;
        v2_ApplyAgeSpeedModifiers(inst);
    }
    *l = *p;
}

uint32_t tapescam_bytes(void)
{
    return sizeof(tapescam_instance_t);
}

/* l / r: n frames of the mix, full scale 1.0, processed in place. mem: tapescam_bytes() of the caller's memory. */
void tapescam_block(uint8_t *mem, const struct tapescam_params *p, float *l, float *r, int n)
{
    tapescam_instance_t *inst = (tapescam_instance_t *)mem;
    if (inst->magic != TS_MAGIC)
        create(inst);
    apply(inst, p);
    while (n > 0) {
        int chunk = n > CHUNK ? CHUNK : n;
        float inputGain = inst->param_input;
        for (int i = 0; i < chunk; i++) {
            l[i] *= inputGain;
            r[i] *= inputGain;
        }
        v2_TapeSat_UpdateControls(inst);
        v2_WF_UpdateControls(inst);
        v2_Tone_UpdateControls(inst, SAMPLE_RATE);
        v2_Hiss_UpdateControls(inst);
        v2_GS_Process(inst, l, r, chunk);
        v2_TapeSat_Process(inst, l, r, chunk);
        v2_WF_Process(inst, l, r, l, r, chunk, SAMPLE_RATE);
        v2_Hiss_Process(inst, l, r, chunk);
        v2_Dropout_Process(inst, l, r, chunk);
        v2_Tone_Process(inst, l, r, chunk);
        v2_Comp_Process(inst, l, r, chunk);
        v2_Width_Process(inst, l, r, chunk);
        for (int i = 0; i < chunk; i++) {
            float out_l = tanhf(l[i] * inst->param_outputLevelLin * 0.95f);
            float out_r = tanhf(r[i] * inst->param_outputLevelLin * 0.95f);
            l[i] = Clamp(out_l, -1.0f, 1.0f);
            r[i] = Clamp(out_r, -1.0f, 1.0f);
        }
        l += chunk;
        r += chunk;
        n -= chunk;
    }
}
