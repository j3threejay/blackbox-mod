/*
 * Groove: the swing of the classic machines. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock (research/SWING_RE.md): Swing (song param 0xd7, 1..99) never moves events. It bends the sequencer clock inside
 * every 480-tick window (an 8th; 960 ticks to a beat): FUN_08069c94 maps a sample time to a "straight" tick, its
 * inverse FUN_08069e84 maps a straight tick to a sample time, with one break point per window. Called at three places
 * in the sequence player (0x0805d238, 0x0805dc90, 0x0805de58) and from seqfix.c.
 *
 * "Groove:" on Tools Main (global list 0x145, saved as "groove"): Stock, MPC, Linn/909, SP-1200.
 *  - Stock: the two calls go to stock's own functions - bit for bit what 3.1.9 does.
 *  - The machines (research/GROOVES.md): the Swing number is read as the classic percentage (the share of the pair
 *    taken by its first note; 50 = straight, 66.7 = triplet), clamped to the machine's range, and the swung note is
 *    put on the machine's own clock:
 *      MPC-60/3K 96 PPQN (10 of our ticks), 16ths (window 480), 50 .. 75 %   MPC60 / MPC3000 / MPC2000
 *      Linn/909  48 PPQN (20 ticks),        16ths (window 480), 50 .. 75 %   LM-1, LinnDrum, DMX, TR-909
 *      SP-1200   24 PPQN (40 ticks),        8ths  (window 960), 50 .. 71 %   SP-1200, SP-12, Drumulator
 *    So 54 % on the SP-1200 lands one of its ticks late, 58 two, ... 71 five: its six steps, exactly.
 *  - The map: straight -> real is piecewise linear with its break at the window's middle, so the note on the second
 *    16th (8th) lands exactly on the machine tick. The other direction is its inverse. Both in whole ticks, int32
 *    (the firmware has no 64-bit division; ticks stay far inside int32 for ~150 hours at 120 BPM, and anything
 *    outside falls back to stock's functions).
 * What it does not change: note lengths (stock never swings them), the note-on offset inside the audio block (stock
 * computes it from the straight time, research/SWING_RE.md "the trap"; a swung note can start up to one block early,
 * as on stock).
 * CPU: a few dozen instructions per call, a handful of calls per playing sequence per block: ~0 %.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef int64_t *(*s2t_fn)(int64_t *out, uint8_t *clock, uint32_t lo, int32_t hi);
typedef int64_t *(*t2s_fn)(int64_t *out, uint8_t *clock, const int64_t *ticks);
typedef void (*s2raw_fn)(int64_t *out, uint8_t *clk, uint32_t lo, int32_t hi);
typedef void (*raw2s_fn)(int64_t *out, uint8_t *clk, const int64_t *ticks);
typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, int param);

#define fw_stock_s2t     ((s2t_fn)FN(0x08069c94))
#define fw_stock_t2s     ((t2s_fn)FN(0x08069e84))
#define fw_s2raw         ((s2raw_fn)FN(0x0804d708))      /* samples -> clock ticks (clock + 8) */
#define fw_raw2s         ((raw2s_fn)FN(0x0804d798))      /* clock ticks -> samples (clock + 8) */
#define fw_register_list ((register_fn)FN(0x0808c0d8))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))

#define SETTINGS     ((const void *)(0x24020088u + 0x8c90u))     /* app: global settings store */
#define PARAM_GROOVE 0x145   /* not 0x1bb: that is the insert's Manual (P_INS_RATE + 2) */
#define CLOCK_SWING  0x148                                         /* clock: float swing = value / 100 */

enum { G_STOCK, G_MPC, G_LINN, G_SP, GROOVES };
static const char *const groove_names[GROOVES] = {"Stock", "MPC-60/3K", "Linn/909", "SP-1200"};

struct grid {
    int32_t window, tick, max_d;     /* ticks: the swing window, one machine tick, the latest the swung note may land */
};
static const struct grid grids[GROOVES] = {
    {0, 0, 0},
    {480, 10, 360},                  /* 75 % of 480 */
    {480, 20, 360},
    {960, 40, 680},                  /* 50 % + five ticks of 24 PPQN = 70.8 % */
};

void groove_register(void *table)
{
    fw_register_list(table, PARAM_GROOVE, "Groove:", groove_names, GROOVES, "groove");
}

void groove_defaults(void *store)
{
    fw_store_add(store, PARAM_GROOVE, G_STOCK);
}

/* Where the swung note lands in its window: the Swing number as the share of the pair, snapped to the machine's tick */
static int32_t landing(const struct grid *g, const uint8_t *clock)
{
    float s = *(const float *)(clock + CLOCK_SWING);           /* 0.01 .. 0.99 */
    int32_t d = (int32_t)(s * (float)(g->window / g->tick) + 0.5f) * g->tick;
    int32_t half = g->window / 2;
    return d < half ? half : d > g->max_d ? g->max_d : d;
}

static int32_t floor_div(int32_t a, int32_t b, int32_t *rem)
{
    int32_t q = a / b, r = a - q * b;
    if (r < 0) {
        r += b;
        q--;
    }
    *rem = r;
    return q;
}

static int32_t scale(int32_t x, int32_t num, int32_t den)      /* round(x * num / den), x >= 0 */
{
    return (x * num + den / 2) / den;
}

/* straight -> real (where the note sounds) */
static int32_t warp(int32_t t, int32_t w, int32_t d)
{
    int32_t u, h = w / 2;
    int32_t base = floor_div(t, w, &u) * w;
    return u <= h ? base + scale(u, d, h) : base + d + scale(u - h, w - d, w - h);
}

/* real -> straight: the FIRST straight tick that sounds at or after r. The player plays an event when its straight tick
   is below this of the segment's end, so an event is due exactly when its swung time has come - no tick early, none
   late. The formula lands within a tick; the two loops make it exact against warp(). */
static int32_t unwarp(int32_t r, int32_t w, int32_t d)
{
    int32_t v, h = w / 2;
    int32_t base = floor_div(r, w, &v) * w;
    int32_t t = v <= d ? base + scale(v, h, d) : base + h + scale(v - d, w - h, w - d);
    while (warp(t - 1, w, d) >= r)
        t--;
    while (warp(t, w, d) < r)
        t++;
    return t;
}

static const struct grid *active(void)
{
    unsigned k = (unsigned)fw_setting(SETTINGS, PARAM_GROOVE);
    return k > G_STOCK && k < GROOVES ? &grids[k] : 0;
}

static int fits(int64_t v)
{
    return v > -0x3fffffffLL && v < 0x3fffffffLL;
}

/* Replaces FUN_08069c94 at the player's calls and seqfix.c's: a sample time -> the straight tick. */
int64_t *groove_s2t(int64_t *out, uint8_t *clock, uint32_t lo, int32_t hi)
{
    const struct grid *g = active();
    if (!g)
        return fw_stock_s2t(out, clock, lo, hi);
    int64_t raw;
    fw_s2raw(&raw, clock + 8, lo, hi);
    if (!fits(raw))
        return fw_stock_s2t(out, clock, lo, hi);
    *out = unwarp((int32_t)raw, g->window, landing(g, clock));
    return out;
}

/* Replaces FUN_08069e84 at the player's call: a straight tick -> its sample time. */
int64_t *groove_t2s(int64_t *out, uint8_t *clock, const int64_t *ticks)
{
    const struct grid *g = active();
    if (!g || !fits(*ticks))
        return fw_stock_t2s(out, clock, ticks);
    int64_t real = warp((int32_t)*ticks, g->window, landing(g, clock));
    fw_raw2s(out, clock + 8, &real);
    return out;
}
