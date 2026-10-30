/*
 * LFO 2 and LFO 3 for every pad. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock gives a pad one LFO. These are two more, as modulation sources "LFO2" / "LFO3" (source codes 5 / 6, which the
 * preset format already calls lfo2 / lfo3), with four knobs each on a new "LFO+" tab of the pad parameter screen:
 *   Wave    Saw, RevSaw, Tri, Tri+, Sine, Sine+, Square, Sqr+, Random (stock's nine), ExpDn, ExpUp, Drift
 *           (+ = 0..1 instead of -1..1; ExpDn / ExpUp are front-loaded ramps, 0..1; Drift is a smooth random)
 *   Rate    always tempo-synced: 32 bars .. 1/32
 *   Trig    Free (runs on), Retrig (restarts with every note), Once (restarts, runs one cycle, holds its end)
 *   Offset  where in the cycle it starts (0..100 % = 0..360 degrees)
 *
 * One LFO per pad, not per note (stock's is per note). Values are worked out once per engine block (5.33 ms) in
 * duck_block's tick, for the pads that have one of them routed; routing is the ENV mechanism (envmod.c).
 * Sample, Multisample, Clip and Slicer pads (3.1.D added the last two: envmod.c's class B path). Not Granular pads.
 *
 * Memory: 0x1000 bytes behind Prism's block (master.c takes both from the firmware's permanent allocator at boot).
 * UI: the pad parameter screen has three tab bars (FUN_080b8c0c builds them): 0 = Main Pos LFO Conf, 1 = the granular
 * one with a fourth tab "Gran" for page 3, 2 = Main LFO Conf for multisamples. Page 3 is empty for Sample, Multi, Clip
 * and Slicer pads, so its eight slots hold these knobs, and those pads are given bar 1 with the tab relabelled "LFO+".
 * (A multisample pad therefore also shows the Pos tab, whose page is empty for it.)
 */
#include <stdint.h>

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef void (*tabs_fn)(uint8_t *view, int bar);
typedef void (*label_fn)(void *widget, const char *text);
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_tabs          ((tabs_fn)FN(0x080b8724))
#define fw_label         ((label_fn)FN(0x080a3dec))

#define TYPE_PCT 8
#define P_LFO     0x1a9          /* + 4 * (lfo - 2): Wave, Rate, Trig, Offset; 0x1a9..0x1b0 (0x1b5 is stock's) */
#define APP_PADS  (0x24020088u + 0x1840u)                /* app pad stores: + row * 0xf0 + col * 0x30 */

enum { W_SAW, W_REVSAW, W_TRI, W_TRIP, W_SINE, W_SINEP, W_SQUARE, W_SQRP, W_RANDOM, W_EXPDN, W_EXPUP, W_DRIFT, WAVES };
static const char *const wave_names[WAVES] = {"Saw", "RevSaw", "Tri", "Tri+", "Sine", "Sine+", "Square", "Sqr+", "Random",
                                              "ExpDn", "ExpUp", "Drift"};
#define RATES 15
static const char *const rate_names[RATES] = {"32 bar", "16 bar", "8 bar", "4 bar", "2 bar", "1 bar", "1/2", "1/2T", "1/4",
                                              "1/4T", "1/8", "1/8T", "1/16", "1/16T", "1/32"};
static const float rate_beats[RATES] = {128.0f, 64.0f, 32.0f, 16.0f, 8.0f, 4.0f, 2.0f, 4.0f / 3.0f, 1.0f,
                                        2.0f / 3.0f, 0.5f, 1.0f / 3.0f, 0.25f, 1.0f / 6.0f, 0.125f};
enum { T_FREE, T_RETRIG, T_ONCE };
static const char *const trig_names[3] = {"Free", "Retrig", "Once"};

/* ---- settings ---- */

void stretch_defaults(void *store);   /* stretch.c: the pad's Stretch model */
void insert_defaults(void *store);   /* insert.c: the pad's insert effect, nine more */

void lfo_register(void *table)
{
    static const char *const label[2][4] = {{"2 Wave:", "2 Rate:", "2 Trig:", "2 Offset:"}, {"3 Wave:", "3 Rate:", "3 Trig:", "3 Offset:"}};
    static const char *const xml[2][4] = {{"lfo2wave", "lfo2rate", "lfo2trig", "lfo2offset"}, {"lfo3wave", "lfo3rate", "lfo3trig", "lfo3offset"}};
    for (int k = 0; k < 2; k++) {
        fw_register_list(table, P_LFO + 4 * k, label[k][0], wave_names, WAVES, xml[k][0]);
        fw_register_list(table, P_LFO + 4 * k + 1, label[k][1], rate_names, RATES, xml[k][1]);
        fw_register_list(table, P_LFO + 4 * k + 2, label[k][2], trig_names, 3, xml[k][2]);
        fw_register_num(table, P_LFO + 4 * k + 3, TYPE_PCT, label[k][3], 0, 1000, xml[k][3]);
    }
}

/* Replaces the last entry of a pad's default settings (bl FUN_08093ef6 @0x0809423c, "0xdc = 0"): ours follow it.
   LFO 2 comes up as a one-bar sine that runs on, LFO 3 as a new random value on every quarter of a retriggered bar. */
void lfo_defaults(void *store, int param, int value)
{
    static const uint16_t first[8] = {W_SINE, 5, T_FREE, 0, W_RANDOM, 8, T_RETRIG, 0};
    fw_store_add(store, param, value);
    for (int i = 0; i < 8; i++)
        fw_store_add(store, P_LFO + i, first[i]);
    insert_defaults(store);
    stretch_defaults(store);
}

/* ---- the tab ---- */

#define VIEW_TAB_NEW 0x106d8     /* bar 1's fourth tab button: 0x103b8 (bar 0's last) + 0x3c0 - 0xa0 */

/* Replaces the two calls that pick the tab bar (bl FUN_080b8724 @0x080b8844, 0x080b8bcc). */
void lfo_tabs(uint8_t *view, int bar)
{
    int ours = bar != 1;         /* 1 = a granular pad, whose fourth tab is its own */
    fw_label(view + VIEW_TAB_NEW, ours ? "LFO+" : (const char *)0x080cf748 /* "Gran" */);
    fw_tabs(view, 1);
}

/* ---- the engine ---- */

struct lfo {
    uint32_t pad0;               /* a source is read at pointer + 4 */
    float value;
    uint32_t phase;
    float from, to;              /* Random / Drift: this cycle's value and the next */
    uint8_t wave, rate, trig, done;
    uint32_t offset;             /* as phase */
};
struct lfo_state {
    uint32_t magic;
    float bpm;
    uint32_t active;             /* bit pad * 2 + k: something is routed from it */
    uint32_t rng, scan, last;
    struct lfo l[16][2];
    struct route {
        uint16_t target;
        uint8_t slot, src;       /* src 5 / 6 = routed from LFO 2 / 3, 0 = a free record */
    } routes[16][8];             /* lfo_route: the pad's slots routed from an LFO */
    uint16_t full;               /* bit pad: more routes than records, its flags no longer clear */
};
_Static_assert(sizeof(struct lfo_state) <= 0x1000, "master.c gives the LFOs 0x1000 bytes");
#define LFO_MAGIC 0x4c464f73u    /* "LFOs" (3.5.m: slots added; was "LFO2") */
#define DUCK_TRIGS (*(volatile uint16_t *)(0x2405ff70u + 14))   /* duck_state's spare bytes: a bit per pad, set at voice start */

uint8_t *master_block(void);     /* master.c: the boot-time SDRAM block, or 0 */
#define LFO_OFFSET 0x56800u      /* behind Prism's */

static struct lfo_state *lfo_state(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct lfo_state *s = (struct lfo_state *)(mem + LFO_OFFSET);
    if (s->magic != LFO_MAGIC) {
        for (unsigned i = 0; i < sizeof *s / 4; i++)
            ((volatile uint32_t *)s)[i] = 0;
        s->rng = 0x1f0c0de5u;
        s->bpm = 120.0f;
        s->magic = LFO_MAGIC;
    }
    return s;
}

static inline float l_rnd(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return (float)(int32_t)*s * (1.0f / 2147483648.0f);     /* -1 .. 1 */
}

static inline float l_exp2(float x)
{
    if (x < -30.0f)
        return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v;
    v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}

static float shape(const struct lfo *l, uint32_t phase)
{
    float x = (float)phase * (1.0f / 4294967296.0f), y;     /* 0 .. 1 through the cycle */
    switch (l->wave) {
    case W_SAW:    return 2.0f * x - 1.0f;
    case W_REVSAW: return 1.0f - 2.0f * x;
    case W_TRI:    return x < 0.5f ? 4.0f * x - 1.0f : 3.0f - 4.0f * x;
    case W_TRIP:   return x < 0.5f ? 2.0f * x : 2.0f - 2.0f * x;
    case W_SINE:
    case W_SINEP:
        y = (float)(int32_t)phase * (1.0f / 2147483648.0f);
        y = 4.0f * y * (1.0f - (y < 0.0f ? -y : y));         /* parabola sine, starts at 0 going up */
        return l->wave == W_SINE ? y : 0.5f + 0.5f * y;
    case W_SQUARE: return x < 0.5f ? 1.0f : -1.0f;
    case W_SQRP:   return x < 0.5f ? 1.0f : 0.0f;
    case W_RANDOM: return l->from;
    case W_EXPDN:  return l_exp2(-7.2f * x);                 /* 1 -> 0, most of it early */
    case W_EXPUP:  return l_exp2(-7.2f * (1.0f - x));        /* 0 -> 1, most of it late */
    case W_DRIFT:  return l->from + (l->to - l->from) * x * x * (3.0f - 2.0f * x);
    default:       return 0.0f;
    }
}

/* comp.c tells us the tempo every block (the master stage is where it is readable). */
void lfo_tempo(float bpm)
{
    struct lfo_state *s = lfo_state();
    if (s && bpm > 20.0f)
        s->bpm = bpm;
}

/* envmod.c: the source a voice of this pad should read for LFO `k` (0 / 1), or 0 without memory. Marks it as in use. */
void *lfo_source(const uint8_t *pad, int k)
{
    struct lfo_state *s = lfo_state();
    if (!s)
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18), p = ((id >> 8) & 3) * 4 + (id & 3);
    s->active |= 1u << (p * 2 + (unsigned)k);
    return &s->l[p][k];
}

/* envmod.c: a mod slot (target, slot: stock keys a pad's entries by both) of this pad was set to `source`, any source,
   "none" included. Once the last slot routed from an LFO is set to something else, that LFO stops being worked on;
   before 3.5.m 'active' stayed set until a reboot (~0.3 % of the engine). Only a route recorded here can clear the flag:
   one set by a voice (lfo_source) without a recorded route, or a pad with more than 8 routes, keeps it, as before. */
void lfo_route(const uint8_t *pad, unsigned target, unsigned slot, unsigned source)
{
    struct lfo_state *s = lfo_state();
    if (!s)
        return;
    uint32_t id = *(const uint32_t *)(pad + 0x18), p = ((id >> 8) & 3) * 4 + (id & 3);
    struct route *r = s->routes[p], *hit = 0, *free_ = 0;
    for (unsigned i = 0; i < 8; i++) {
        if (r[i].src && r[i].target == target && r[i].slot == slot)
            hit = &r[i];
        else if (!r[i].src && !free_)
            free_ = &r[i];
    }
    unsigned old = hit ? hit->src : 0, ours = source == 5 || source == 6;   /* envmod.c's SRC_LFO2 / SRC_LFO3 */
    if (ours && !hit) {
        if (!free_) {
            s->full |= (uint16_t)(1u << p);
            return;
        }
        hit = free_;
        hit->target = (uint16_t)target;
        hit->slot = (uint8_t)slot;
    }
    if (hit)
        hit->src = (uint8_t)(ours ? source : 0);
    if (!old || old == source || (s->full >> p & 1))
        return;
    for (unsigned i = 0; i < 8; i++)
        if (r[i].src == old)
            return;
    s->active &= ~(1u << (p * 2 + (old - 5)));
}

/* duck_block calls this once per engine block. now: the engine's sample clock. */
void lfo_tick(uint32_t now)
{
    struct lfo_state *s = lfo_state();
    uint16_t trigs = DUCK_TRIGS;
    DUCK_TRIGS = 0;
    if (!s)
        return;
    uint32_t step = now - s->last;
    s->last = now;
    if (step > 4800u)
        step = 0;
    if (!s->active)
        return;
    /* settings: one pad's worth per tick (all 16 within 85 ms), so the lookups stay cheap */
    unsigned q = s->scan++ & 15;
    const void *store = (const void *)(APP_PADS + (q >> 2) * 0xf0u + (q & 3) * 0x30u);
    for (int k = 0; k < 2; k++) {
        struct lfo *l = &s->l[q][k];
        unsigned wave = (unsigned)fw_setting(store, P_LFO + 4 * k), rate = (unsigned)fw_setting(store, P_LFO + 4 * k + 1);
        unsigned trig = (unsigned)fw_setting(store, P_LFO + 4 * k + 2), off = (unsigned)fw_setting(store, P_LFO + 4 * k + 3);
        l->wave = (uint8_t)(wave < WAVES ? wave : W_SINE);
        l->rate = (uint8_t)(rate < RATES ? rate : 5);
        l->trig = (uint8_t)(trig < 3 ? trig : T_FREE);
        l->offset = (off > 1000 ? 1000u : off) * 4294967u;   /* 1000 -> just under a full turn */
    }
    float per_frame = s->bpm * (4294967296.0f / (60.0f * 48000.0f));   /* phase per frame for a one-beat cycle */
    for (unsigned p = 0; p < 16; p++) {
        if (!(s->active >> (p * 2) & 3))
            continue;
        for (int k = 0; k < 2; k++) {
            struct lfo *l = &s->l[p][k];
            if ((trigs >> p & 1) && l->trig != T_FREE) {
                l->phase = 0;
                l->done = 0;
                l->from = l->to;
                l->to = l_rnd(&s->rng);
            } else if (!l->done) {
                uint32_t inc = (uint32_t)(per_frame / rate_beats[l->rate] * (float)step), before = l->phase;
                l->phase += inc;
                if (l->phase < before) {                     /* a new cycle */
                    if (l->trig == T_ONCE) {
                        l->done = 1;
                        l->phase = 0xffffffffu;
                    } else {
                        l->from = l->to;
                        l->to = l_rnd(&s->rng);
                    }
                }
            }
            l->value = shape(l, l->phase + l->offset);       /* Once, finished: the phase stays at the cycle's last point */
        }
    }
}
