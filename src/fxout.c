/*
 * FX OUT: a Level and a Low Cut on each send effect's output. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Asked for in testing (3.3.o3, using Smash): the send effects are not loud enough. Stock has no return level: each pad has a send
 * to FX1 (delay) and FX2 (reverb), and the wet comes back to Out 1 at a fixed level. Each effect now has
 *   Level    -12 .. +12 dB (param 0x149, TYPE_DB, milli-dB), default +4 dB (picked in testing)
 *   Low Cut  Off, 30 .. 600 Hz, a 12 dB/oct high-pass on the wet only (param 0x14a), default Off
 *   Output   Out 1 / Out 2 / Out 3: which output the return is mixed into (param 0x148, 3.3.x), default Out 1 = stock.
 *            The engine adds the delay's bus 10 and the reverb's bus 11 into Out 1's bus 0 (FUN_08053164 @0x08053506 /
 *            0x08053516, then the Master FX / compressor / clipper run on bus 0 only, then bus 0 / 1 / 2 go to
 *            Out 1 / 2 / 3 and all of them to Phones). fxret_mix adds it to bus 1 or 2 instead: such a return skips the
 *            Master FX, compressor and clipper, like any pad routed to Out 2 / 3. (A tester asked: their kick and snare
 *            are on Out 1 and the returns could not leave it.)
 * in its own cell's store, so both save with the preset. One pair of ids serves both cells: a setting is looked up in
 * the cell's own store, and the two cells' stores are separate.
 *
 * Where it runs: FX1 = the delay slot's own bus right after the slot has run (munchi.cpp: the bus holds the wet and
 * nothing else then, which is what Motion already relies on), so every Type is covered, stock Delay included.
 * FX2 = the reverb core's stereo out (fx2.c), before stock resamples it up and mixes it in, so Plate and Room both are.
 *
 * The page (from testing, photos 10-19): the knob screen's top bar has three empty tabs left of "DLY" / "RVB" (tabs with
 * an empty label and id 0, FUN_080aba84). On a delay or reverb page the one beside the header reads "OUT"; a tap shows
 * the OUT page (Level, Low Cut; header "DLY OUT" / "RVB OUT", the tab reads "FX"), another tap goes back. The tap
 * comes up as message 1 carrying the tab's id (button +0x14, FUN_080a3808), through the bar (its +0x30 returns 1) to
 * the knob screen's +0x30 handler FUN_080ab9b4, which stock turns into an app message whose TYPE is the id; with id 0
 * that is nothing, so the tabs did nothing. fx_screen_child catches our id first.
 * The OUT page is dropped when you LEAVE: BACK off the knob screen (master_back) or the screen opened on another cell
 * (GUI msg 0x9d: FUN_080ab880, hooked at 0x0808ba8a), so INFO on an effect lands on its knobs. Never on a rebuild, nor
 * on stock re-opening the same cell: 3.3.s / 3.3.t dropped it on any page build it had not asked for, and on the test unit
 * (10-19) the OUT page flashed up and fell straight back to the knobs - stock builds the page again after the tap.
 *
 * State: backup SRAM 0x38800a60 (free between fx2's state, which ends 0x38800a5c, and FX2_OBJ at 0x38800b00), behind
 * a magic word: backup SRAM survives a reflash, so anything else there is garbage, not ours.
 * CPU (estimate): Level ~3 instructions a sample per channel when not 0 dB (48 kHz; the reverb's at 29.8 kHz), Low Cut
 * ~12 more per sample per channel when on: FX1 ~30 instr / frame = 0.3 %, FX2 ~0.2 %; both 0 when Level 0 dB + Off.
 */
#include <stdint.h>

#include "fxout_coef.inc"

#define FN(addr) ((addr) | 1u)

typedef int (*setting_fn)(const void *store, unsigned param);
typedef void (*label_fn)(void *widget, const char *text);
typedef void (*list_clear_fn)(void *list);
typedef void (*list_add_fn)(void *list, int param, int value);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);

#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_label         ((label_fn)FN(0x080a3dec))
#define fw_list_clear    ((list_clear_fn)FN(0x080a4fc2))
#define fw_list_add      ((list_add_fn)FN(0x080a5038))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))

void bkp_enable(void);

#define P_OUT_LEVEL  0x149
#define P_OUT_CUT    0x14a
#define P_OUT_DEST   0x148           /* clean id (no stock compare, unregistered): test_param_ids.py checks it */
#define APP_FX       (0x24020088u + 0x2fc0u)    /* app: FX cell records, 0x18 each: row 0 delay, row 1 reverb */
#define TYPE_DB      7               /* milli-dB, shown as dB (comp.c's Comp Thresh) */
#define LEVEL_MIN    (-12000)
#define LEVEL_MAX    12000
#define LEVEL_DEF    4000

#define SCREEN_TAB    0x70           /* knob screen: the bar at +0x34, its first tab at bar +0x3c (FUN_080c4ff0) */
#define SCREEN_HEADER 0x3ac          /* knob screen: the header button ("DLY" / "RVB") */
#define BUTTON_ID     0x14           /* button: the id its taps carry (vtable +0x24 stores it here) */
#define OUT_TAB_ID    0x7e01u        /* ours; never reaches the app (fx_screen_child takes it) */

struct fxout_state {
    uint32_t magic;
    uint8_t page[2];                 /* 1 = the OUT page is up for that effect (0 delay, 1 reverb) */
    uint8_t built;                   /* the page being built: 0 none of ours, 1 delay, 2 reverb (GUI task) */
    uint8_t _r;
    float g[2];                      /* the gain each effect ended its last block at */
    int32_t cut[2];                  /* the Low Cut entry the filter state belongs to */
    float z[2][4];                   /* biquad state per effect: L z1, z2, R z1, z2 (transposed direct form II) */
};
#define S ((volatile struct fxout_state *)0x38800a60u)
#define MAGIC 0x46584f31u            /* "FXO1" */

static void start(void)
{
    bkp_enable();
    if (S->magic == MAGIC)
        return;
    S->page[0] = S->page[1] = 0;
    S->built = 0;
    for (int k = 0; k < 2; k++) {
        S->g[k] = 1.0f;
        S->cut[k] = 0;
        for (int i = 0; i < 4; i++)
            S->z[k][i] = 0.0f;
    }
    S->magic = MAGIC;
}

/* registration: called once, from munchi_register (the delay) */
static const char *const dest_names[3] = {"Out 1", "Out 2", "Out 3"};

void fxout_register(void *table)
{
    fw_register_num(table, P_OUT_LEVEL, TYPE_DB, "Level:", LEVEL_MIN, LEVEL_MAX, "fxoutlevel");
    fw_register_list(table, P_OUT_CUT, "Low Cut:", fxout_cut_names, FXOUT_CUTS + 1, "fxoutlowcut");
    fw_register_list(table, P_OUT_DEST, "Output:", dest_names, 3, "fxoutdest");
}

/* a delay / reverb cell's defaults: munchi_defaults_last, fx2_defaults_last */
void fxout_defaults(void *store)
{
    fw_store_add(store, P_OUT_LEVEL, LEVEL_DEF);
    fw_store_add(store, P_OUT_CUT, 0);
    fw_store_add(store, P_OUT_DEST, 0);
}

/* fxret_thunk.S: replaces the engine's "Out 1 += this return" (FUN_0804da6c(out1, ret)); which = 0 delay, 1 reverb.
   bufs = the bus table stock's FUN_0805f37c takes. Audio task. */
typedef void (*mix_fn)(void *dst, void *src);
typedef void *(*bus_fn)(void *bufs, int ch);
#define fw_mix ((mix_fn)FN(0x0804da6c))
#define fw_bus ((bus_fn)FN(0x0805f37c))
void fxret_mix(void *out1, void *ret, void *bufs, int which)
{
    int dest = fw_setting((const void *)(APP_FX + (unsigned)(which & 1) * 0x18u), P_OUT_DEST);
    void *to = out1;
    if ((dest == 1 || dest == 2) && bufs) {
        void *b = fw_bus(bufs, dest);
        if (b)
            to = b;
    }
    fw_mix(to, ret);
}

/* 2^x for |x| < 8, to ~1e-4: whole part by exponent bits, fraction by a cubic */
static float exp2f_(float x)
{
    int i = (int)(x < 0.0f ? x - 1.0f : x);
    float f = x - (float)i;
    float p = 1.0f + f * (0.6951786f + f * (0.2261961f + f * 0.0786253f));
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

static float level_gain(int mdb)
{
    if (mdb < LEVEL_MIN)
        mdb = LEVEL_MIN;
    if (mdb > LEVEL_MAX)
        mdb = LEVEL_MAX;
    return mdb == 0 ? 1.0f : exp2f_((float)mdb * 1.66096405e-4f);   /* 10^(dB / 20) = 2^(mdB x log2(10) / 20000) */
}

/*
 * One block of an effect's wet, in place. which: 0 = delay (48 kHz), 1 = reverb (29.8 kHz). store: that effect's
 * settings. Audio task. Level ramps from the last block's gain to this one's across the block (no zipper).
 */
void fxout_run(int which, const void *store, float *l, float *r, int n)
{
    if (which < 0 || which > 1 || n <= 0 || !l)
        return;
    start();
    float g1 = store ? level_gain(fw_setting(store, P_OUT_LEVEL)) : 1.0f;
    int cut = store ? fw_setting(store, P_OUT_CUT) : 0;
    if (cut < 0 || cut > FXOUT_CUTS)
        cut = 0;
    float g0 = S->g[which];
    if (!(g0 > 0.0f && g0 < 8.0f))   /* also catches a NaN left in the state */
        g0 = g1;
    S->g[which] = g1;
    if (cut != S->cut[which]) {      /* a different filter: start it from rest */
        S->cut[which] = cut;
        for (int i = 0; i < 4; i++)
            S->z[which][i] = 0.0f;
    }
    if (cut) {
        const float *c = fxout_coef[which][cut - 1];
        float b0 = c[0], b1 = c[1], b2 = c[2], a1 = c[3], a2 = c[4];
        float lz1 = S->z[which][0], lz2 = S->z[which][1], rz1 = S->z[which][2], rz2 = S->z[which][3];
        for (int i = 0; i < n; i++) {
            float x = l[i], y = b0 * x + lz1;
            lz1 = b1 * x - a1 * y + lz2;
            lz2 = b2 * x - a2 * y;
            l[i] = y;
            if (r && r != l) {
                x = r[i];
                y = b0 * x + rz1;
                rz1 = b1 * x - a1 * y + rz2;
                rz2 = b2 * x - a2 * y;
                r[i] = y;
            }
        }
        S->z[which][0] = lz1;
        S->z[which][1] = lz2;
        S->z[which][2] = rz1;
        S->z[which][3] = rz2;
    }
    if (g0 == 1.0f && g1 == 1.0f)
        return;
    float g = g0, dg = (g1 - g0) / (float)n;
    for (int i = 0; i < n; i++) {
        g += dg;
        l[i] *= g;
        if (r && r != l)
            r[i] *= g;
    }
}

/* ---- the page (GUI task) ---- */

/* munchi_list, once it knows the cell: 1 = delay, 2 = reverb, 0 = neither. Returns 1 when it built the OUT page. */
int fxout_list(void *list, const void *store, int which)
{
    start();
    S->built = (uint8_t)which;
    if (which < 1 || which > 2 || !S->page[which - 1])
        return 0;
    fw_list_clear(list);
    fw_list_add(list, P_OUT_LEVEL, fw_setting(store, P_OUT_LEVEL));
    fw_list_add(list, P_OUT_CUT, fw_setting(store, P_OUT_CUT));
    fw_list_add(list, P_OUT_DEST, fw_setting(store, P_OUT_DEST));
    return 1;
}

/* fx_screen_msg, before stock rebuilds the page (0x66 / 0x67): munchi_list will say what is being built */
void fxout_before_build(void)
{
    start();
    S->built = 0;
}

/* Replaces the knob screen's open (bl FUN_080ab880 @0x0808ba8a, GUI msg 0x9d: it stores the new cell id from msg +4
   at screen +0x367c, then stock rebuilds). Opened on another cell: that one's knobs, not an OUT page. GUI task. */
typedef void (*open_fn)(void *screen, const void *msg);
#define fw_screen_open ((open_fn)FN(0x080ab880))
void fxout_open(uint8_t *screen, const uint8_t *msg)
{
    start();
    if (screen && msg && *(const uint16_t *)(screen + 0x367c) != *(const uint16_t *)(msg + 4))
        S->page[0] = S->page[1] = 0;
    fw_screen_open(screen, msg);
}

/* master_back: BACK off the knob screen. App task (a byte write each: the GUI task only reads them). */
void fxout_leave(void)
{
    start();
    S->page[0] = S->page[1] = 0;
}

/* fx_screen_msg, after the rebuild: the tab (and, on the OUT page, the header) for what was built */
void master_after_build(uint8_t *screen);   /* master.c: a pad's insert page keeps its header to 8 characters */

void fxout_after_build(uint8_t *screen)
{
    master_after_build(screen);
    start();
    uint8_t *tab = screen + SCREEN_TAB;
    int which = S->built;
    if (which < 1 || which > 2) {    /* a master / insert page: the tab as the constructor left it */
        fw_label(tab, "");
        *(uint32_t *)(tab + BUTTON_ID) = 0;
        return;
    }
    int out = S->page[which - 1];
    fw_label(tab, out ? "FX" : "OUT");
    *(uint32_t *)(tab + BUTTON_ID) = OUT_TAB_ID;
    if (out)
        fw_label(screen + SCREEN_HEADER, which == 1 ? "DLY OUT" : "RVB OUT");
}

/* fx_screen_child: 1 when msg is a tap on our tab (the page is flipped and a rebuild is wanted), 0 otherwise */
int fxout_tap(const uint16_t *msg)
{
    if (!msg || msg[0] != 1 || *(const uint32_t *)((const uint8_t *)msg + 0xc) != OUT_TAB_ID)
        return 0;
    start();
    int which = S->built;
    if (which < 1 || which > 2)
        return 0;
    S->page[which - 1] ^= 1;
    return 1;
}
