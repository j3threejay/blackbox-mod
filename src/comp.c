/*
 * Master compressor models. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: Tools "Compressor: On / Off" (param 0xb4, global, saved in settings.tml) compresses Out 1. The engine runs it
 * once per 256-frame block (FUN_0804eddc): the gain is decided once per block from the block level, ramped, then a
 * 0 dB block limiter. This turns the switch into a list:
 *   Off, Stock, Glue, Punch, Opto, Squash, Limit, Smash
 * Off and Stock keep their stock meaning (0 and 1, as already saved). The five models are fixed presets of one
 * per-sample, stereo-linked feed-forward compressor (soft-knee gain computer, attack / release smoothing of the gain
 * reduction in dB, optional two-stage "auto" release, optional parallel blend, optional 1.5 ms look-ahead), modelled
 * loosely on: SSL bus (Glue), slow-attack drum comp (Punch), LA-2A (Opto), 1176 all-buttons in parallel (Squash),
 * a mastering limiter (Limit). State lives in the backup SRAM at 0x38800400.
 * Smash (3.1.y) is its own engine, smash.c: three bands, each squashed from above and lifted from below. It has two knobs
 * of its own on the Compressor page, "Depth:" (0x1ea) and "Time:" (0x1eb), and uses the same state block.
 *
 * Plus one setting, "Comp Thresh:" (new global parameter 0x1d0, -24..+12 dB, default 0, xml "compthresh"): moves the
 * models' threshold by that much (for Limit, it raises or lowers the input push instead; the ceiling stays).
 * The Tools Main page is reordered so Compressor and Comp Thresh sit right under Headphone.
 *
 * The clipper (3.1.Z, clip.c) is the last stage on Out 1, after whichever compressor is picked, also with the
 * compressor Off: "Clipper:" Off / Clean / Diode (0x1b4), "Clip:" (0x1b2), "Shape:" (0x1b3), on the Compressor page.
 * Order on Out 1: Master FX, compressor, clipper. Its state is in the SDRAM block master.c takes at boot.
 */
#include <stdint.h>
#include "clip.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef int (*stock_fn)(int *obj, void *bufs);
typedef void *(*buf_of_fn)(void *bufs, unsigned idx);
typedef int (*frames_fn)(void *buf);
typedef void (*chans_fn)(void *buf, float **l, float **r);
typedef unsigned (*index_fn)(int *obj);
typedef int (*chain_fn)(int *next, void *bufs);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);

#define fw_register_list ((register_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_stock_comp    ((stock_fn)FN(0x0804eddc))
#define fw_buf_of        ((buf_of_fn)FN(0x0805f37c))
#define fw_frames        ((frames_fn)FN(0x0804d8e8))
#define fw_stereo        ((chans_fn)FN(0x0804d9c0))      /* forces stereo: returns left and right */
#define DEFAULT_INDEX_FN 0x08046a15u                     /* stock "output index" method: reads obj +0x1e */

#define SETTINGS ((const void *)(0x24020088u + 0x8c90u)) /* app: global settings store */
#define PARAM_COMP 0xb4
#define PARAM_THRESH 0x1d0       /* unregistered in stock; ids < 500 are table slots */
#define TYPE_DB    7             /* value in milli-dB, shown as dB (the Metro Gain style) */
#define TYPE_PCT   8
#define PARAM_SMASH_DEPTH 0x1ea
#define PARAM_SMASH_TIME  0x1eb
#define PARAM_CLIP     0x1b2     /* how hard the mix is pushed into the clipper */
#define PARAM_SHAPE    0x1b3     /* soft .. hard */
#define PARAM_CLIPPER  0x1b4     /* Off, Clean, Diode */
#define CLIP_OFFSET    (0x56800u + 0x2d000u)                 /* in master.c's block, behind insert.c's bank */
uint8_t *master_block(void);

void bkp_enable(void);
void master_register(void *table);
void master_defaults(void *store);
void preroll_register(void *table);
void preroll_defaults(void *store);
void theme_register(void *table);
void theme_defaults(void *store);
void groove_register(void *table);
void groove_defaults(void *store);
void live_register(void *table);
void live_defaults(void *store);
void master_fx(float bpm, float *l, float *r, int n);
int master_on(void);
void lfo_tempo(float bpm);

struct smash_state;
void smash_reset(struct smash_state *s, uint32_t magic);
void smash_block(struct smash_state *s, float depth, float time, float push, float *l, float *r, int n);

#define MODELS 5
#define MODEL_SMASH (2 + MODELS)   /* list value 7 */
const char *const comp_names[3 + MODELS] = {"Off", "Stock", "Glue", "Punch", "Opto", "Squash", "Limit", "Smash"};
/* Smash's DSP is in bank 2 since 3.3.o, the five models' since 3.3.y (room in bank 1): without the payload their places
   read "---"; a model then runs as Stock, Smash passes dry */
static const char *const comp_names_none[3 + MODELS] = {"Off", "Stock", "---", "---", "---", "---", "---", "---"};
int b2_present(void);
int b2_live(void);

/* Replaces the Compressor registration (FUN_0808c12c, an On/Off): same parameter, now a 7-entry list. */
void comp_register(void *table, int param, int type, const char *label, int min, int max, const char *xml)
{
    (void)type;
    (void)min;
    (void)max;
    fw_register_list(table, param, label, b2_present() ? comp_names : comp_names_none, 3 + MODELS, xml);
    fw_register_num(table, PARAM_THRESH, TYPE_DB, "Comp Thresh:", -24000, 12000, "compthresh");
    fw_register_num(table, PARAM_SMASH_DEPTH, TYPE_PCT, "Depth:", 0, 1000, "smashdepth");
    fw_register_num(table, PARAM_SMASH_TIME, TYPE_PCT, "Time:", 0, 1000, "smashtime");
    master_register(table);
    preroll_register(table);
    groove_register(table);
    theme_register(table);
    live_register(table);
    static const char *const clip_names[CLIP_TYPES] = {"Off", "Clean", "Diode"};
    static const char *const clip_names_none[CLIP_TYPES] = {"Off", "---", "---"};   /* clip.c is in bank 2 (3.3.y) */
    fw_register_list(table, PARAM_CLIPPER, "Clipper:", b2_present() ? clip_names : clip_names_none, CLIP_TYPES, "clipper");
    fw_register_num(table, PARAM_CLIP, TYPE_PCT, "Clip:", 0, 1000, "clipamount");
    fw_register_num(table, PARAM_SHAPE, TYPE_PCT, "Shape:", 0, 1000, "clipshape");
}

/* Replaces the "Compressor defaults to 1" entry of the global settings defaults (bl @0x08094886): add ours after it. */
void comp_defaults(void *store, int param, int value)
{
    fw_store_add(store, param, value);
    fw_store_add(store, PARAM_THRESH, 0);
    fw_store_add(store, PARAM_SMASH_DEPTH, 500);
    fw_store_add(store, PARAM_SMASH_TIME, 500);
    master_defaults(store);
    preroll_defaults(store);
    groove_defaults(store);
    theme_defaults(store);
    live_defaults(store);
    fw_store_add(store, PARAM_CLIPPER, CLIP_OFF);
    fw_store_add(store, PARAM_CLIP, 300);                    /* +5.4 dB into it once it is switched on */
    fw_store_add(store, PARAM_SHAPE, 800);                   /* mostly hard: rounded over the last fifth */
}

/* Pad Overdrive is now a different circuit (od.c): its label on the pad page. */
const char od_label[] = "Saturation:";

/* exp2, bit trick with quadratic correction (~0.3 %): Smash's push. The models' own copy is in compm.c. */
static inline __attribute__((always_inline)) float exp2f_fast(float x)
{
    if (x < -30.0f)
        return 0.0f;
    if (x > 30.0f)
        x = 30.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i;
    float p = 1.0f + f * (0.6565f + f * 0.3435f);           /* 2^f on [0, 1) */
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

#define SMASH_MAGIC 0x534d5331u    /* "SMS1": switching between Smash and a model re-starts whichever comes next */
/* compm.c (bank 2): Glue .. Limit, one block, its state at 0x38800400 (the block Smash uses: one runs at a time) */
void comp_model_block(unsigned model, float off, float *l, float *r, int n);

/*
 * Replaces the engine's call to the stock compressor (bl @0x08053ca0). Stock only gets here when the setting is not Off
 * (engine flag +0x28d60, bne.w @0x0805352e); that branch is now unconditional so the Master FX insert (master.c) runs
 * with the compressor Off too. Order on Out 1: Master FX, then the compressor.
 */
/* Out 1's block as two channels (fw_stereo turns a mono buffer into stereo, so only call it when something will run) */
static int out1(int *obj, void *bufs, float **l, float **r)
{
    index_fn index = *(index_fn *)(*obj + 0x54);
    unsigned out = (uint32_t)index == DEFAULT_INDEX_FN ? *(uint16_t *)((uint8_t *)obj + 0x1e) : index(obj);
    void *buf = fw_buf_of(bufs, out);
    int n = fw_frames(buf);
    *l = *r = 0;
    fw_stereo(buf, l, r);
    return *l && *r ? n : 0;
}

/* The last stage on Out 1. */
static void clip_stage(int *obj, void *bufs)
{
    int type = fw_setting(SETTINGS, PARAM_CLIPPER);
    uint8_t *mem = master_block();
    if (!mem)
        return;
    struct clip_state *s = (struct clip_state *)(mem + CLIP_OFFSET);
    float *l, *r;
    int n;
    if (type <= CLIP_OFF || type >= CLIP_TYPES || !b2_live()) {   /* clip_block is in bank 2 (3.3.y): off without it */
        s->magic = 0;                                        /* starts clean when it is switched on */
        return;
    }
    if ((n = out1(obj, bufs, &l, &r)) > 0)
        clip_block(s, type, (float)fw_setting(SETTINGS, PARAM_CLIP) * 0.001f,
                   (float)fw_setting(SETTINGS, PARAM_SHAPE) * 0.001f, l, r, n);
}

#ifdef CPU_PROF
#define comp_process comp_process_body   /* prof.c times it under the hooked name */
#endif
void rta_tap(int *obj, void *bufs);                        /* rta.c: the EQ screen's analyser, Out 1 after the EQ */
int comp_process(int *obj, void *bufs)
{
    rta_tap(obj, bufs);
    unsigned model = (unsigned)fw_setting(SETTINGS, PARAM_COMP);
    float *l, *r;
    int n;
    /* the preset tempo, where the delay reads it: float at (*bufs) + 0x18; only believed if *bufs points into RAM */
    uint32_t ctx = *(uint32_t *)bufs, top = ctx >> 28;
    float bpm = top == 2 || top == 3 || top == 0xc ? *(float *)(ctx + 0x18) : 0.0f;
    bpm = bpm > 20.0f && bpm < 400.0f ? bpm : 0.0f;
    lfo_tempo(bpm);
    if (master_on() && (n = out1(obj, bufs, &l, &r)) > 0)
        master_fx(bpm, l, r, n);
    if (model >= 2 && model < MODEL_SMASH && !b2_live())
        model = 1;                                           /* the models' DSP is in bank 2 (3.3.y): Stock without it */
    if (model == 0) {
        clip_stage(obj, bufs);
        return 1;                                            /* Off: stock would not have called the stage at all */
    }
    if (model < 2 || model > MODEL_SMASH) {
        /* Stock passes the buffers on down its chain itself (obj[2]): hold the chain back so the clipper comes first */
        int *after = (int *)obj[2];
        obj[2] = 0;
        int ok = fw_stock_comp(obj, bufs);
        obj[2] = (int)after;
        clip_stage(obj, bufs);
        return after ? (*(chain_fn *)(*after + 0xc))(after, bufs) : ok;
    }
    bkp_enable();
    if (model == MODEL_SMASH) {
        struct smash_state *o = (struct smash_state *)0x38800400u;   /* the models' block: one compressor runs at a time */
        if (*(volatile uint32_t *)o != SMASH_MAGIC && b2_live())   /* smash_reset is in bank 2 too */
            smash_reset(o, SMASH_MAGIC);
        n = out1(obj, bufs, &l, &r);
        if (n > 0 && b2_live()) {                     /* smash_block is in bank 2: dry rather than fault */
            float off = (float)fw_setting(SETTINGS, PARAM_THRESH) * 0.001f;
            off = off < -24.0f ? -24.0f : off > 12.0f ? 12.0f : off;
            smash_block(o, (float)fw_setting(SETTINGS, PARAM_SMASH_DEPTH) * 0.001f,
                      (float)fw_setting(SETTINGS, PARAM_SMASH_TIME) * 0.001f, exp2f_fast(-off * 0.16610f), l, r, n);
        }
        clip_stage(obj, bufs);
        int *after = (int *)obj[2];
        return after ? (*(chain_fn *)(*after + 0xc))(after, bufs) : 1;
    }
    n = out1(obj, bufs, &l, &r);
    float off = 0.0f;
    if (n > 0) {
        off = (float)fw_setting(SETTINGS, PARAM_THRESH) * 0.001f;
        off = off < -24.0f ? -24.0f : off > 12.0f ? 12.0f : off;
    }
    comp_model_block(model, off, l, r, n);
    clip_stage(obj, bufs);
    int *next = (int *)obj[2];                               /* stock passes the buffers on down a chain */
    if (!next)
        return 1;
    return (*(chain_fn *)(*next + 0xc))(next, bufs);
}
