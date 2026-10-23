/*
 * Munchi Delay's engine (delay slot Type 1): Charles Vestal's port of CHOMPI TEMPO's dual delay (src/munchi, MIT; see
 * munchi.cpp for what it does and where its memory comes from). munchi.cpp has the hooks and the settings; this is the
 * DSP, moved out in 3.3.y so it lives in flash bank 2 (build.sh BANK2_OBJS): bank 1 was down to ~1.8 KB. No calls out
 * of bank 2 except to stock firmware (the settings lookup); delay_slot only calls in when bank 2 is live, and plays the
 * stock delay without it.
 */
#include <stddef.h>
#include <stdint.h>
#include <new>

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* bank 2: built for speed (3.3.y: -5 % instructions measured) */

#ifndef MUNCHI_OFF
#include "munchi/tempo/granularDelay.h"
#include "munchi/tempo/reverb.h"
#include "munchi/tempo/SimpleCompressor.h"

#define FN(addr) ((addr) | 1u)
typedef int (*setting_fn)(const void *store, unsigned param);
#define fw_setting       ((setting_fn)FN(0x08093e9c))

#define LINE_LIVE    0x30        /* the stock delay's three lines (munchi.cpp) */
#define LINE_STATE   0x4c
#define LINE_FREEZE  0x68
#define P_FEEDBK 0x38
#define P_WAND   0x1d1
#define P_RANDOM 0x1d2
#define P_FREEZE 0x1d3
#define P_CLOCK  0x1d4
#define P_WIDTH  0x1d5
#define P_DUCK   0x1d6
static const float clock_mul[3] = {1.f, .5f, 2.f};
static const float width_mul[4] = {1.f, 0.f, 2.5f, 5.f};
#define MAGIC 0x4d554e31u                                 /* "MUN1" */
#define MAXN 128

struct Munchi {
    uint32_t magic;
    mbuf_t *live, *frozen;
    granularDelay delay;
    daisysp::Reverb reverb;
    SimpleCompressor comp;
    clockManager clock;
    float wet_amt, reverb_amt, reverb_amt_target, reverb_boost, reverb_boost_target;
    float pulse_phase;
    long pulses;
    int last_wand, last_random, last_feedback, last_freeze, last_duck;
    float clock_mul;
    float wl[MAXN], wr[MAXN];
};

static_assert(sizeof(Munchi) <= 96000 * 4, "Munchi's state must fit the stock delay's 2 s line");

static inline void *line_ptr(uint8_t *obj, int line)
{
    return *(void **)(obj + line);
}

static inline uint32_t line_floats(uint8_t *obj, int line)
{
    return *(uint32_t *)(obj + line + 0x14);
}

static void zero(void *p, uint32_t bytes)
{
    uint32_t *w = (uint32_t *)p;
    for (uint32_t i = 0; i < bytes / 4; i++)
        w[i] = 0;
}

static Munchi *start(uint8_t *obj, int cleared)
{
    void *live = line_ptr(obj, LINE_LIVE), *frozen = line_ptr(obj, LINE_FREEZE), *st = line_ptr(obj, LINE_STATE);
    if (!live || !frozen || !st || line_floats(obj, LINE_STATE) * 4 < sizeof(Munchi))
        return nullptr;
    uint32_t frames = line_floats(obj, LINE_LIVE);              /* floats -> 16-bit stereo frames: same count */
    if (line_floats(obj, LINE_FREEZE) < frames)
        frames = line_floats(obj, LINE_FREEZE);
    if (!cleared) {                 /* 3.3.y: after a type change the slot has just cleared the lines, block by block */
        zero(live, frames * 4);
        zero(frozen, frames * 4);
        zero(st, sizeof(Munchi));
    }
    /* TEMPO's classes expect zeroed memory. Value-initialising zeroes all of it again (byte by byte, the reverb's 64 KB
       included: ~0.8 ms); after the slot's own clear it already is, so the constructors alone do (3.3.y) */
    Munchi *m = cleared ? new (st) Munchi : new (st) Munchi();
    m->live = (mbuf_t *)live;
    m->frozen = (mbuf_t *)frozen;
    m->reverb.Init(48000.f);
    m->reverb.SetAmount(0.f);
    m->reverb.SetInputGain(.3f);
    m->reverb.SetLowpass(1.f);
    m->comp.Init();
    m->delay.Init(m->live, m->frozen, frames, &m->clock, false);
    m->wet_amt = 1.f;
    m->last_wand = m->last_random = m->last_feedback = m->last_freeze = m->last_duck = -1;
    m->clock_mul = 1.f;
    if (!MUNCHI_RNG)
        MUNCHI_RNG = 0x2545f491u;
    m->magic = MAGIC;
    return m;
}

/* FxEngine::setGranularMain / setGranularFeedback, as Munchi's wrapper has them */
static void set_main(Munchi *m, float val)
{
    m->delay.setMainControl(val);
    if (val > .55f) {
        float norm = (val - .55f) / (1.f - .55f);
        float r = chompi::fast_sqrt(norm);                     /* powf(norm, .5f) */
        m->reverb_amt_target = .25f + .65f * r;
        m->reverb_boost_target = val > .6f ? .3f : 0.f;
    } else {
        m->reverb_amt_target = 0.f;
        m->reverb_boost_target = 0.f;
    }
}

static void controls(Munchi *m, const void *store)
{
    int wand = fw_setting(store, P_WAND), random = fw_setting(store, P_RANDOM);
    int feedback = fw_setting(store, P_FEEDBK), freeze = fw_setting(store, P_FREEZE) != 0;
    unsigned clock = (unsigned)fw_setting(store, P_CLOCK), width = (unsigned)fw_setting(store, P_WIDTH);
    int duck = fw_setting(store, P_DUCK);
    m->clock_mul = clock_mul[clock < 3 ? clock : 0];
    MUNCHI_SPREAD = width_mul[width < 4 ? width : 0];
    if (wand != m->last_wand)
        set_main(m, daisysp::fclamp(wand * .001f, 0.f, 1.f));
    if (random != m->last_random)
        m->delay.setAltControl(daisysp::fclamp(random * .001f, 0.f, 1.f));
    if (feedback != m->last_feedback || duck != m->last_duck) {
        float v = daisysp::fclamp(feedback * .001f, 0.f, 1.f);
        m->delay.setFeedback(v);
        float amount = duck == 1 ? 0.f : duck == 2 ? .5f : duck == 3 ? 1.f : (v > .6f ? (v - .6f) / (1.f - .6f) : 0.f);
        m->comp.setAmount(amount);
    }
    if (m->last_freeze >= 0 && freeze != m->last_freeze && freeze != m->delay.getBufferLock())
        m->delay.toggleBufferLock();
    m->last_wand = wand;
    m->last_random = random;
    m->last_feedback = feedback;
    m->last_freeze = freeze;
    m->last_duck = duck;
}

static void run_clock(Munchi *m, float bpm, int frames)
{
    if (!(bpm > 0.f))
        bpm = 120.f;
    bpm *= m->clock_mul;            /* note lengths that would not fit the 4 s buffer are clamped in granularDelay.h */
    m->clock.setBpm(bpm);
    m->pulse_phase += bpm * (24.f / 60.f) * (float)frames * (1.f / 48000.f);
    while (m->pulse_phase >= 1.f) {
        m->pulse_phase -= 1.f;
        m->delay.setClockPulse();
        if (++m->pulses % 12 == 0)
            m->delay.setClockEdge();
    }
}

static inline void process48(Munchi *m, float xl, float xr, float *ol, float *orr)
{
    fonepole(m->wet_amt, 1.f, .001f);
    fonepole(m->reverb_amt, m->reverb_amt_target, .001f);
    fonepole(m->reverb_boost, m->reverb_boost_target, .001f);
    float wl = xl * m->wet_amt, wr = xr * m->wet_amt;
    float dl = xl, dr = xr;                         /* the ducking sidechain: the send itself */
    float yl = 0.f, yr = 0.f;
    m->delay.write(wl, wr);
    m->delay.read(&yl, &yr);
    m->reverb.SetAmount(m->reverb_amt * m->reverb_amt * .8f);
    m->reverb.SetTime(m->reverb_amt);
    m->reverb.SetLowpass(m->reverb_amt * .55f + .4f);
    m->reverb.SetDiffusion(m->reverb_amt * .6f);
    yl += wl * m->reverb_boost;
    yr += wr * m->reverb_boost;
    m->reverb.Process(&yl, &yr);
    m->comp.Process(&yl, &yr, &dl, &dr);
    *ol = yl;
    *orr = yr;
}


extern "C" {

/* The compiler's own zeroing (value-initialising Munchi) calls memset, and the one in munchi.cpp is in bank 1, which
   bank 2 must not call. This copy is made LOCAL to this object after the compile (build.sh: objcopy
   --localize-symbol), so the two never clash and the calls in here resolve to it. */
void *memset(void *d, int c, size_t n)
{
    uint8_t *p = (uint8_t *)d;
    while (n--)
        *p++ = (uint8_t)c;
    return d;
}

/* The state in the delay's second line, started afresh when it is not Munchi's (or the type just changed); 0 = the
   lines are not there or too small, and the slot plays the stock delay. */
void *munchi_ready(uint8_t *obj, int fresh)
{
    Munchi *m = (Munchi *)line_ptr(obj, LINE_STATE);
    if (fresh || !m || m->magic != MAGIC || m->live != line_ptr(obj, LINE_LIVE) ||
        m->frozen != line_ptr(obj, LINE_FREEZE))
        m = start(obj, fresh);
    return m;
}

/* One block: the knobs, the clock, the samples. The wet comes back in *wl / *wr (n frames, n <= MAXN). */
void munchi_run(void *state, const void *store, float bpm, const float *il, const float *ir, int n, float **wl,
                float **wr)
{
    Munchi *m = (Munchi *)state;
    controls(m, store);
    run_clock(m, bpm, n);
    for (int i = 0; i < n; i++)
        process48(m, il[i], ir[i], &m->wl[i], &m->wr[i]);
    *wl = m->wl;
    *wr = m->wr;
}

}
#endif
