/*
 * Reverb slot (FX2) effect selector + Room. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock FX2 is a Dattorro plate (the 1997 paper's tank, with modulation) at 29.8 kHz: the reverb object (vtable
 * 0x080d0814, process 0x08062fe8) reads its settings, resamples the send down to 29.8 kHz, applies pre-delay, calls the
 * core FUN_08074f50(state, in, outL, outR, n), resamples back up and mixes in. Only the core call is replaced: stock
 * still does settings, the 60 s run-on, resampling, pre-delay and the wet level, so every new algorithm gets those for
 * free and only has to turn a mono block into a stereo block at 29.8 kHz.
 *
 * Selector: the firmware registers an unused list parameter 0x198 "FX2" (Delay, Reverb; xml "fx2algo"). It is
 * re-registered as "Type:" with this file's algorithm names and added (first) to the reverb cell's defaults, so it shows
 * at the top of the reverb's settings and saves with the preset. Stock firmware ignores it and plays its plate.
 *
 * Memory: every algorithm reuses the plate's own buffers (state +0x20 ..: 4 x 512, 2 x 1024, 6 x 8192 floats, ~208 KB of
 * DTCM). They are cleared when the algorithm changes so nothing from the old one bursts out. Small state for the new
 * algorithms lives in the backup SRAM at 0x38800a00.
 * Decay arrives in state[0] (= Decay x 0.93), damping in state[1] (0..1).
 */
#include <stdint.h>

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef void (*core_fn)(float *state, const float *in, float *l, float *r, int n);
typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);

#define fw_plate_core    ((core_fn)FN(0x08074f50))
#define fw_register_list ((register_fn)FN(0x0808c0d8))
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))

#define APP_FX       (0x24020088u + 0x2fc0u)    /* app: FX cell records, 0x18 each, by row */
#define OBJ_ID       0x18                       /* engine object id: 3 << 16 | row << 8 */
#define PARAM_TYPE   0x198

void bkp_enable(void);
void fxout_defaults(void *store);                                       /* fxout.c: Level + Low Cut */
void fxout_run(int which, const void *store, float *l, float *r, int n);

enum { ALG_PLATE, ALG_ROOM, ALGS };
const char *const fx2_names[ALGS] = {"Plate", "Room"};
static const char *const fx2_names_none[ALGS] = {"Plate", "---"};   /* Room is in bank 2 (fx2_room.c, 3.3.v) */
int b2_live(void);               /* cpu.c: the matching bank 2 is there, so room() may be called */
int b2_present(void);            /* cpu.c: the same, asked while the lists are registered */

/* Room's own settings (3.1.m), shown only when Type is Room (munchi_list filters the page): the knob screen has 8 slots,
   Type + Decay + Damping + Predelay leave four. All 0..100 %. */
#define P_SIZE  0x1d7            /* line lengths x 0.5 .. x 2 (50 % = as designed) */
#define P_MOD   0x1d8            /* wobble depth 0 .. 20 samples (30 % = 6, as designed) */
#define P_EARLY 0x1d9            /* early reflections 0 .. 0.5 (50 % = 0.25, as designed) */
#define P_WIDTH 0x1da            /* tail stereo width, mid/side 0 .. 1 (100 % = as designed) */
#define TYPE_PCT 8

/* Replaces the registration of 0x198 (bl @0x0808dea4). */
void fx2_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Type:", b2_present() ? fx2_names : fx2_names_none, ALGS, xml);
    fw_register_num(table, P_SIZE, TYPE_PCT, "Size:", 0, 1000, "roomsize");
    fw_register_num(table, P_MOD, TYPE_PCT, "Mod:", 0, 1000, "roommod");
    fw_register_num(table, P_EARLY, TYPE_PCT, "Early:", 0, 1000, "roomearly");
    fw_register_num(table, P_WIDTH, TYPE_PCT, "Width:", 0, 1000, "roomwidth");
}

/* Replaces the reverb cell default "Decay 600" (bl @0x080944a2): Type first, so it heads the settings page. */
void fx2_defaults(void *store, int param, int value)
{
    fw_store_add(store, PARAM_TYPE, ALG_PLATE);
    fw_store_add(store, param, value);
}

/* Replaces the reverb cell's last default, Damping 500 (bl @0x080944b8): Room's settings after it. */
void fx2_defaults_last(void *store, int param, int value)
{
    fw_store_add(store, param, value);
    fw_store_add(store, P_SIZE, 500);
    fw_store_add(store, P_MOD, 300);
    fw_store_add(store, P_EARLY, 500);
    fw_store_add(store, P_WIDTH, 1000);
    fxout_defaults(store);
}

#include "fx2.h"

static void clear(float *state)
{
    for (int i = 0; i < 12; i++) {
        float *b = BUF(state, i);
        if (b)
            for (int k = 0; k < bufs[i].len; k++)
                b[k] = 0.0f;
    }
    S->er_pos = 0;
    for (int k = 0; k < 4; k++)
        S->in_ap_pos[k] = 0;
    for (int k = 0; k < 8; k++) {
        S->line_pos[k] = 0;
        S->line_ap_pos[k] = 0;
        S->lp[k] = 0.0f;
    }
    for (int k = 0; k < 4; k++)
        S->lfo[k] = (uint32_t)k * 0x40000000u;
}

#define FX2_OBJ (*(uint8_t *volatile *)0x38800b00u)    /* set by fx2_core_thunk: the reverb object (r4 there) */

/* Replaces the core call in the reverb's process method (bl @0x0806318e), via fx2_core_thunk. */
#ifdef CPU_PROF
#define fx2_core fx2_core_body             /* prof.c times it under the hooked name */
#endif
void fx2_core(float *state, const float *in, float *outl, float *outr, int n)
{
    uint8_t *obj = FX2_OBJ;
    unsigned alg = ALG_PLATE;
    const void *store = 0;
    if (obj) {
        unsigned row = (*(uint32_t *)(obj + OBJ_ID) >> 8) & 0xff;
        if (row < 5) {
            store = (const void *)(APP_FX + row * 0x18u);
            alg = (unsigned)fw_setting(store, PARAM_TYPE);
        }
    }
    if (alg >= ALGS || (alg == ALG_ROOM && !b2_live()))
        alg = ALG_PLATE;         /* Room lives in bank 2: without it, the plate (never a call into erased flash) */
    bkp_enable();
    if (S->magic != MAGIC || S->alg != alg) {
        clear(state);
        S->alg = alg;
        S->magic = MAGIC;
    }
    if (alg == ALG_ROOM && store) {
        float v_size = (float)fw_setting(store, P_SIZE) * 0.001f;
        struct room_params rp = {
            exp2_fast((v_size - 0.5f) * 2.0f),
            (float)fw_setting(store, P_MOD) * 0.02f,
            (float)fw_setting(store, P_EARLY) * 0.0005f,
            (float)fw_setting(store, P_WIDTH) * 0.001f,
        };
        room(state, in, outl, outr, n, &rp);
    }
    else
        fw_plate_core(state, in, outl, outr, n);
    fxout_run(1, store, outl, outr, n);      /* the FX OUT page's Level + Low Cut, on the wet only (fxout.c) */
}
