/*
 * Master FX slot + knob pages for the master section. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Audio: a second insert on Out 1, run from comp_process just before the compressor (same 256-frame block, same
 * buffers). "Master FX:" (new global list parameter 0x1db, xml "mfx") picks the effect: Off, VHS (VHS below),
 * Prism (3.1.A, prism.c: four blocks, Drive / Motion / Space / Texture).
 *
 * Prism's knobs (3.1.G; the first layout, with an "Edit:" selector, was "confusing and clunky" on the unit):
 *   page 1  Drive FX | Drive || Move FX | Motion || Space FX | Space || Tex FX | Texture
 *           (slots come in vertical pairs on the screen, so each block is one column: its effect over its amount)
 *   page 2  Tilt | Rate | Time | Mix
 * INFO steps Tools -> page 1 -> page 2 -> Tools; BACK always returns to Tools. The Master FX type itself is picked on
 * its Tools row. Nothing on a page changes what another knob is.
 * The header of these pages is the global cell's name: master_title supplies it (cpu.c's cpu_name asks).
 * Prism's memory (PRISM_BYTES of SDRAM) comes from the firmware's own permanent allocator, once, at boot: master_alloc.
 *
 * VHS (clean-room, after the Chase Bliss Generation Loss manual: a worn tape / VHS machine):
 *   Saturate -> short modulated delay (Wow slow + deep, Flutter fast + shallow) -> Dropout (random level dropouts, one
 *   or both channels) -> Hi Cut (12 dB) -> Lo Cut (6 dB) -> + Noise (hiss).
 * The delay line is 256 stereo 16-bit frames in the backup SRAM (all that is left there), so the wet path is 16-bit
 * with 6 dB of headroom, and the insert adds 2 frames of latency plus the wow / flutter depth (up to ~2.4 ms).
 *
 * UI: the 8-knob screen the delay and reverb use is generic: set_screen(0x23) posts GUI msg 0x9d with the cell id at
 * app+0x28, and the screen's 0x66 handler fills its slots from the page builder FUN_08098d40(app, cell, list, 0), which
 * already knows cell 0x40 = the global (Tools) settings. INFO on Tools only re-showed Tools, so:
 *   INFO on the Compressor or Master FX row of Tools -> that row's knob page; INFO or BACK there -> Tools.
 *   (3.1.q cycled Tools -> Compressor -> Master FX; the request was for the row that is selected.)
 * master_list supplies the page for cell 0x40; values go through the stock global path.
 */
#include <stdint.h>

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef int (*build_fn)(uint8_t *app, uint8_t *cell, void *list, int page);
typedef void (*list_clear_fn)(void *list);
typedef void (*list_add_fn)(void *list, int param, int value);
typedef void (*label_fn)(void *widget, const char *text);
typedef void (*set_screen_fn)(uint8_t *app, int screen, int a, int b);
typedef unsigned (*selected_fn)(uint8_t *rows);

#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_build         ((build_fn)FN(0x08098d40))
#define fw_list_clear    ((list_clear_fn)FN(0x080a4fc2))
#define fw_list_add      ((list_add_fn)FN(0x080a5038))
#define fw_label         ((label_fn)FN(0x080a3dec))
#define fw_set_screen    ((set_screen_fn)FN(0x0809eaec))
#define fw_selected      ((selected_fn)FN(0x080b9d20))

#define GUI_PTR    0x24002e6cu   /* the GUI task's object pointer (literal @0x08043e54) */
#define GUI_TOOLS  0x1fa58       /* GUI: the Tools view */
#define TOOLS_ROWS 0x218         /* Tools view: its settings row list */

void bkp_enable(void);
void instrument_boot(void);           /* fault.c: once per boot, from master_alloc */
void lfo_register(void *table);

#define SETTINGS ((const void *)(0x24020088u + 0x8c90u)) /* app: global settings store */
#define CELL_GLOBAL  0x40
#define APP_FX_CELL  0x28        /* app: u16 cell the FX knob screen opens on */
#define APP_SCREEN   0x8ca4
#define SCREEN_TOOLS 0x25
#define SCREEN_KNOBS 0x23
#define TYPE_PCT 8

#define P_COMP    0xb4
#define P_THRESH  0x1d0
#define P_MFX     0x1db
#define P_WOW     0x1dc
#define P_FLUTTER 0x1dd
#define P_SAT     0x1de
#define P_DROPOUT    0x1df
#define P_NOISE   0x1e0
#define P_HICUT   0x1e1
#define P_LOCUT   0x1e2

/* 0x19c..0x1a8: free in stock, none special-cased (0x1b5 is). 0x19c was 3.1.A's "Edit:" selector, unused since 3.1.G */
#define P_PR_FX   0x19d           /* + block: Drive FX, Move FX, Space FX, Tex FX */
#define P_PR_AMT  0x1a1           /* + block: Drive, Motion, Space, Texture */
#define P_PR_TILT 0x1a5
#define P_PR_RATE 0x1a6
#define P_PR_TIME 0x1a7
#define P_PR_MIX  0x1a8

enum { MFX_OFF, MFX_VHS, MFX_PRISM, MFX_COUNT };
const char *const mfx_names[MFX_COUNT] = {"Off", "VHS", "Prism"};
static const char *const mfx_names_none[MFX_COUNT] = {"Off", "VHS", "---"};   /* no bank 2 payload: cpu.c's b2_present */
int b2_present(void);
static const char *const pr_fx_names[4][5] = {
    {"Drive", "Sweet", "Fuzz", "Snarl", "Bloom"},
    {"Doubler", "Vibrato", "Phaser", "Tremolo", "Pitch"},
    {"PingPong", "Tape", "Hall", "Scatter", "Reverse"},
    {"Filter", "Clamp", "Cassette", "Glitch", "Static"},
};
static const char *const pr_time_names[8] = {"1/32", "1/16", "1/8T", "1/8", "1/8D", "1/4", "1/4D", "1/2"};

struct prism_params {
    uint32_t fx[4];
    float amt[4];
    float tilt, rate, mix;
    uint32_t time;
};
void prism_block(uint8_t *mem, const struct prism_params *p, float bpm, float *l, float *r, int n);
int b2_live(void);               /* cpu.c: is bank 2, where prism_block lives, the matching payload */
#define PRISM_BYTES 0x56800u
#define PRISM_MAGIC 0x50525331u
/* where Prism's memory is, and a check word (backup SRAM survives a reset; the block is re-allocated every boot) */
#define PRISM_MEM   (*(volatile uint32_t *)0x38800f70u)
#define PRISM_CHECK (*(volatile uint32_t *)0x38800f74u)
#define PRISM_KEY   0x5052534du
#define EXTRA_BYTES 0x2e100u      /* behind Prism's: lfo.c's state (0x1000), usbdev.c's audio ring (0x6000), filter.c's S950 bank (0x4000), insert.c's bank (0x22000), comp.c's clipper (0x100), clipwin.c's bank (0x1000 since Fit) */
_Static_assert(0x2d100u + 0x1000u <= EXTRA_BYTES, "clipwin.c's bank (0x1000 at PRISM_BYTES + 0x2d100) fits the block");

/* which master page the knob screen shows, and whether it is showing one (backup SRAM, next to munchi's words) */
struct master_ui {
    uint8_t page, active;
    uint16_t pad;                /* PAGE_INS: the pad cell whose insert the knob screen is showing */
};
#define UI ((volatile struct master_ui *)0x38800b1cu)
enum { PAGE_COMP, PAGE_MFX, PAGE_MFX2, PAGE_INS };

/* the per-pad insert (insert.c): its row on the pad's Conf tab and its knob page */
#define P_INS          0x1b6
#define P_INS_PH       0x1b7
#define P_INS_FL       0x1b8
#define P_INS_RATE     0x1b9     /* .. 0x1be: Rate, Depth, Manual, Feedback, Spread, Mix (Phaser and Flanger) */
#define P_INS_MIX      0x1be
#define P_INS_GATE     0x1c2     /* .. 0x1c6: Thresh, Attack, Hold, Release, Floor (the Gate; it borrows Mix) */
#define APP_PADS       (0x24020088u + 0x1840u)   /* app pad stores: + row * 0xf0 + col * 0x30 */
#define APP_PAD_CELL   0x14      /* app: u16 id of the pad the pad screens are on */
#define APP_CAN_MOD    0x8cc6    /* app: the selected pad parameter can be modulated (INFO opens its mod screen) */
#define SCREEN_PAD_CONF 0x1c     /* pad parameter screens are 0x18 + page; the Conf list is page 4 */
#define GUI_PADVIEW    0x732d8   /* GUI: the pad parameter view (FUN_0808b654 case 0xb7) */
#define PADVIEW_PAGE   0xf6cc    /* 0, 2, 3 = knob pages, 1 and 4 = lists */
#define PADVIEW_ROWS   0xd50     /* its list widget */
void insert_register(void *table);
void clipwin_register(void *table);

#define P_SMASH_DEPTH 0x1ea
#define P_SMASH_TIME  0x1eb
#define COMP_SMASH 7
/* slots come in vertical pairs, so the clipper has its own column(s) to the right of the compressor's */
#define P_CLIP    0x1b2
#define P_SHAPE   0x1b3
#define P_CLIPPER 0x1b4
static const uint16_t page_comp[] = {P_COMP, P_THRESH, P_CLIPPER, P_CLIP, P_SHAPE, 0};
static const uint16_t page_smash[] = {P_COMP, P_SMASH_DEPTH, P_SMASH_TIME, P_THRESH, P_CLIPPER, P_CLIP, P_SHAPE, 0};
static const uint16_t page_mfx[] = {P_MFX, P_WOW, P_FLUTTER, P_SAT, P_DROPOUT, P_NOISE, P_HICUT, P_LOCUT, 0};

/* Called from comp_register / comp_defaults (their hooks are already in the registration and defaults paths). */
void master_register(void *table)
{
    fw_register_list(table, P_MFX, "Master FX:", b2_present() ? mfx_names : mfx_names_none, MFX_COUNT, "mfx");
    fw_register_num(table, P_WOW, TYPE_PCT, "Wow:", 0, 1000, "mfxwow");
    fw_register_num(table, P_FLUTTER, TYPE_PCT, "Flutter:", 0, 1000, "mfxflutter");
    fw_register_num(table, P_SAT, TYPE_PCT, "Saturate:", 0, 1000, "mfxsat");
    fw_register_num(table, P_DROPOUT, TYPE_PCT, "Dropout:", 0, 1000, "mfxfail");
    fw_register_num(table, P_NOISE, TYPE_PCT, "Noise:", 0, 1000, "mfxnoise");
    fw_register_num(table, P_HICUT, TYPE_PCT, "Hi Cut:", 0, 1000, "mfxhicut");
    fw_register_num(table, P_LOCUT, TYPE_PCT, "Lo Cut:", 0, 1000, "mfxlocut");
    static const char *const fx_label[4] = {"Drive FX:", "Move FX:", "Space FX:", "Tex FX:"};
    static const char *const fx_xml[4] = {"prismdrivefx", "prismmovefx", "prismspacefx", "prismtexfx"};
    static const char *const amt_label[4] = {"Drive:", "Motion:", "Space:", "Texture:"};
    static const char *const amt_xml[4] = {"prismdrive", "prismmotion", "prismspace", "prismtexture"};
    for (int b = 0; b < 4; b++) {
        fw_register_list(table, P_PR_FX + b, fx_label[b], pr_fx_names[b], 5, fx_xml[b]);
        fw_register_num(table, P_PR_AMT + b, TYPE_PCT, amt_label[b], 0, 1000, amt_xml[b]);
    }
    fw_register_num(table, P_PR_TILT, TYPE_PCT, "Tilt:", 0, 1000, "prismtilt");
    fw_register_num(table, P_PR_RATE, TYPE_PCT, "Rate:", 0, 1000, "prismrate");
    fw_register_list(table, P_PR_TIME, "Time:", pr_time_names, 8, "prismtime");
    fw_register_num(table, P_PR_MIX, TYPE_PCT, "Mix:", 0, 1000, "prismmix");
    lfo_register(table);
    insert_register(table);
    clipwin_register(table);
}

void master_defaults(void *store)
{
    fw_store_add(store, P_MFX, MFX_OFF);
    fw_store_add(store, P_WOW, 300);
    fw_store_add(store, P_FLUTTER, 200);
    fw_store_add(store, P_SAT, 300);
    fw_store_add(store, P_DROPOUT, 0);
    fw_store_add(store, P_NOISE, 150);
    fw_store_add(store, P_HICUT, 350);
    fw_store_add(store, P_LOCUT, 100);
    /* Prism as it first comes up: a little Sweet and a little Cassette; Doubler and Tape picked but at 0 */
    static const uint16_t pr_fx[4] = {1, 0, 1, 2}, pr_amt[4] = {300, 0, 0, 250};
    for (int b = 0; b < 4; b++) {
        fw_store_add(store, P_PR_FX + b, pr_fx[b]);
        fw_store_add(store, P_PR_AMT + b, pr_amt[b]);
    }
    fw_store_add(store, P_PR_TILT, 500);
    fw_store_add(store, P_PR_RATE, 300);
    fw_store_add(store, P_PR_TIME, 3);
    fw_store_add(store, P_PR_MIX, 1000);
}

/* ---- knob pages ---- */

/* Replaces the page-builder call in the knob screen's 0x66 / 0x67 handler (bl FUN_08098d40 @0x080ab94a). GUI task. */
int master_list(uint8_t *app, uint8_t *cell, void *list, int page)
{
    bkp_enable();
    if (*(uint16_t *)(cell + 4) != CELL_GLOBAL) {
        if (UI->active && UI->page == PAGE_INS && *(uint16_t *)(cell + 4) == UI->pad) {
            /* a pad's insert: its Type, then that type's Model and the six shared knobs */
            unsigned id = UI->pad;
            const void *store = (const void *)(APP_PADS + ((id >> 4) & 3) * 0xf0u + (id & 3) * 0x30u);
            int type = fw_setting(store, P_INS);
            fw_list_clear(list);
            fw_list_add(list, P_INS, type);
            if (type == 1 || type == 2) {                    /* Phaser, Flanger: Model then the shared six */
                int model = type == 1 ? P_INS_PH : P_INS_FL;
                fw_list_add(list, model, fw_setting(store, (unsigned)model));
                for (int k = 0; k < 6; k++)
                    fw_list_add(list, P_INS_RATE + k, fw_setting(store, P_INS_RATE + (unsigned)k));
            } else if (type == 3) {                          /* Gate: its own five. No Model (one kind) and no Mix:
                                                                Floor already says how far down "closed" is */
                for (int k = 0; k < 5; k++)
                    fw_list_add(list, P_INS_GATE + k, fw_setting(store, P_INS_GATE + (unsigned)k));
            }
            return 1;
        }
        UI->active = 0;                  /* the knob screen is on a delay / reverb cell again */
        return fw_build(app, cell, list, page);
    }
    fw_list_clear(list);
    if (UI->page != PAGE_COMP && fw_setting(SETTINGS, P_MFX) == MFX_PRISM) {
        static const uint16_t page1[] = {P_PR_FX, P_PR_AMT, P_PR_FX + 1, P_PR_AMT + 1, P_PR_FX + 2, P_PR_AMT + 2, P_PR_FX + 3, P_PR_AMT + 3, 0};
        static const uint16_t page2[] = {P_PR_TILT, P_PR_RATE, P_PR_TIME, P_PR_MIX, 0};
        for (const uint16_t *id = UI->page == PAGE_MFX2 ? page2 : page1; *id; id++)
            fw_list_add(list, *id, fw_setting(SETTINGS, *id));
        return 1;
    }
    const uint16_t *id = UI->page != PAGE_COMP ? page_mfx : fw_setting(SETTINGS, P_COMP) == COMP_SMASH ? page_smash : page_comp;
    for (; *id; id++)
        fw_list_add(list, *id, fw_setting(SETTINGS, *id));
    return 1;
}

/* cpu.c: what the header of the knob screen should read while a master page is up (the global cell's name, which
   is the version text everywhere else), or 0 when none is. */
const char *master_title(void)
{
    bkp_enable();
    if (!UI->active || UI->page == PAGE_INS)
        return 0;
    if (UI->page == PAGE_COMP)
        return "Comp";
    int type = fw_setting(SETTINGS, P_MFX);                  /* 8 characters at most: longer wraps (cpu.c) */
    return type == MFX_PRISM ? (UI->page == PAGE_MFX2 ? "Prism 2" : "Prism 1") : type == MFX_VHS ? "VHS" : "MFX";
}

/* set_screen(0x23) posts msg 0x9d with the cell id at app+0x28; lend it the global cell for that one call, so the FX
   screen keeps its own selection. */
static void open_page(uint8_t *app, int page)
{
    uint16_t *cell = (uint16_t *)(app + APP_FX_CELL), keep = *cell;
    bkp_enable();
    UI->page = (uint8_t)page;
    UI->active = 1;
    *cell = CELL_GLOBAL;
    fw_set_screen(app, SCREEN_KNOBS, 0, 0);
    *cell = keep;
}

/*
 * Replaces the five set_screen calls of INFO on the Tools screens (0x25..0x29 -> next: all re-show the same view).
 * INFO opens the knob page of the selected row: Compressor or Master FX; on any other row it does what stock did.
 * The Tools view (GUI +0x1fa58, FUN_080c5180) lists its settings in the row widget at +0x218; FUN_080b9d20 returns the
 * selected row's parameter id.
 */
void master_tools_info(uint8_t *app, int screen, int a, int b)
{
    uint8_t *gui = *(uint8_t *volatile *)GUI_PTR;
    unsigned row = gui ? fw_selected(gui + GUI_TOOLS + TOOLS_ROWS) : 0;
    if (row == P_COMP)
        open_page(app, PAGE_COMP);
    else if (row == P_MFX)
        open_page(app, PAGE_MFX);
    else
        fw_set_screen(app, screen, a, b);
}

/* INFO on the knob screen (via master_info_thunk @0x080a3064): Prism's first page goes on to its second, any other
   master page back to Tools. Returns the cell id
   the stock code should judge: the global cell (which it ignores) when we handled the press. */
unsigned master_info_knob(uint8_t *app)
{
    bkp_enable();
    if (!UI->active || app[APP_SCREEN] != SCREEN_KNOBS)
        return *(uint16_t *)(app + APP_FX_CELL);
    if (UI->page == PAGE_INS) {          /* a pad's insert page: INFO goes back to the row it came from */
        UI->active = 0;
        fw_set_screen(app, SCREEN_PAD_CONF, 0, 0);
        return CELL_GLOBAL;
    }
    int more = UI->page == PAGE_MFX && fw_setting(SETTINGS, P_MFX) == MFX_PRISM;
    UI->active = 0;
    fw_set_screen(app, SCREEN_TOOLS, 0, 0);
    if (more)
        open_page(app, PAGE_MFX2);       /* by way of Tools: both are screen changes the unit already does */
    return CELL_GLOBAL;
}

/* Replaces BACK's set_screen(0x30) on the knob screen (bl @0x080a3220): a master page goes back to Tools. */
void master_back(uint8_t *app, int screen, int a, int b)
{
    bkp_enable();
    if (UI->active) {
        UI->active = 0;
        screen = UI->page == PAGE_INS ? SCREEN_PAD_CONF : SCREEN_TOOLS;
    }
    fw_set_screen(app, screen, a, b);
}

/*
 * INFO on a pad parameter screen (insert_info_thunk @0x080a2fd6). On the Insert row of the Conf list it opens the
 * eight-knob screen on that pad, the way open_page lends it the global cell, and answers 0 so stock does nothing
 * more. Anywhere else it answers what stock was about to read.
 */
unsigned insert_info(uint8_t *app)
{
    uint8_t *gui = *(uint8_t *volatile *)GUI_PTR;
    if (gui) {
        uint8_t *view = gui + GUI_PADVIEW;
        int32_t page = *(int32_t *)(view + PADVIEW_PAGE);
        if ((page == 1 || page == 4) && fw_selected(view + PADVIEW_ROWS) == P_INS) {
            uint16_t *cell = (uint16_t *)(app + APP_FX_CELL), keep = *cell;
            bkp_enable();
            UI->pad = *(uint16_t *)(app + APP_PAD_CELL);
            UI->page = PAGE_INS;
            UI->active = 1;
            *cell = UI->pad;
            fw_set_screen(app, SCREEN_KNOBS, 0, 0);
            *cell = keep;
            return 0;
        }
    }
    return app[APP_CAN_MOD];
}

/* ---- VHS ---- */

#define FS        48000.0f
#define LINE      256                    /* frames, power of two */
#define LINE_GAIN 16384.0f               /* 16-bit store with 6 dB of headroom */
#define WOW_MAX   100.0f                 /* frames of swing each way (2.1 ms) */
#define FLUT_MAX  14.0f                  /* 0.29 ms */
#define BASE_DLY  2.0f

struct gl_state {
    uint32_t magic;
    uint32_t wpos, ph_wow, ph_flut, rng, timer;
    float dw, df;                        /* smoothed swing depths, frames */
    float lp1[2], lp2[2], hp[2];
    float g[2], gt[2];                   /* dropout gain and its target, per channel */
};
#define GL   ((volatile struct gl_state *)0x38800f20u)
#define GLBUF ((int16_t *)0x38800b20u)   /* LINE x 2 int16 = 0x400 bytes, up to 0x38800f20 */
#define MAGIC 0x474c3031u                /* "GL01" */

static inline float exp2_fast(float x)
{
    if (x < -30.0f)
        return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v;
    v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}

static inline float unit(float v)
{
    return v < 0.0f ? 0.0f : v > 1.0f ? 1.0f : v;
}

static inline float pct(unsigned param)
{
    return unit((float)fw_setting(SETTINGS, param) * 0.001f);
}

/* sin(2 pi phase / 2^32), parabola */
static inline float lfo(uint32_t ph)
{
    float x = (float)(int32_t)ph * (1.0f / 2147483648.0f);
    return 4.0f * x * (1.0f - (x < 0.0f ? -x : x));
}

static inline float softclip(float x)
{
    x = x < -3.0f ? -3.0f : x > 3.0f ? 3.0f : x;
    return x * (27.0f + x * x) / (27.0f + 9.0f * x * x);
}

static inline float rnd(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return (float)(*s >> 8) * (1.0f / 16777216.0f);
}

static void vhs(float *l, float *r, int n)
{
    bkp_enable();
    if (GL->magic != MAGIC) {
        for (int i = 0; i < LINE * 2; i++)
            GLBUF[i] = 0;
        for (unsigned i = 0; i < sizeof(struct gl_state) / 4; i++)
            ((volatile uint32_t *)GL)[i] = 0;
        GL->rng = 0x2545f491u;
        GL->g[0] = GL->g[1] = GL->gt[0] = GL->gt[1] = 1.0f;
        GL->magic = MAGIC;
    }
    float wow = pct(P_WOW), flut = pct(P_FLUTTER), sat = pct(P_SAT), fail = pct(P_DROPOUT), noise = pct(P_NOISE);
    float hicut = pct(P_HICUT), locut = pct(P_LOCUT);

    float drive = 1.0f + 3.0f * sat, makeup = exp2_fast(-0.5f * 1.5850f * sat * (2.0f - sat));   /* ~1 / sqrt(drive) */
    float sat_mix = sat * 4.0f > 1.0f ? 1.0f : sat * 4.0f;
    float dw_t = wow * WOW_MAX, df_t = flut * FLUT_MAX;
    uint32_t inc_wow = (uint32_t)((0.4f + 1.6f * wow) * (4294967296.0f / FS));
    uint32_t inc_flut = (uint32_t)((6.0f + 8.0f * flut) * (4294967296.0f / FS));
    /* one-pole coefficients: 20 kHz .. 1 kHz, 20 Hz .. 800 Hz */
    float lp_a = 1.0f - exp2_fast(-1.4427f * 6.2832f * 20000.0f * exp2_fast(-4.32f * hicut) / FS);
    float hp_a = 1.0f - exp2_fast(-1.4427f * 6.2832f * 20.0f * exp2_fast(5.32f * locut) / FS);
    float hiss = noise * noise * 0.02f;

    struct gl_state s;                                       /* word copies: no memcpy in the cave */
    for (unsigned i = 0; i < sizeof s / 4; i++)
        ((volatile uint32_t *)&s)[i] = ((volatile uint32_t *)GL)[i];
    float *ch[2] = {l, r};
    for (int i = 0; i < n; i++) {
        s.dw += (dw_t - s.dw) * 0.0002f;
        s.df += (df_t - s.df) * 0.0002f;
        s.ph_wow += inc_wow;
        s.ph_flut += inc_flut;
        float d = BASE_DLY + s.dw * (1.0f + lfo(s.ph_wow)) + s.df * (1.0f + lfo(s.ph_flut));
        int di = (int)d;
        float frac = d - (float)di;

        if (fail <= 0.0f) {
            s.gt[0] = s.gt[1] = 1.0f;
            s.timer = 0;
        } else if (s.timer) {
            s.timer--;
        } else if (s.gt[0] < 1.0f || s.gt[1] < 1.0f) {       /* a dropout ends; wait for the next */
            s.gt[0] = s.gt[1] = 1.0f;
            s.timer = (uint32_t)((0.1f + rnd(&s.rng) * (0.15f + 4.0f * (1.0f - fail))) * FS);
        } else {                                             /* a dropout starts: 20 .. 220 ms */
            float depth = 1.0f - fail * (0.4f + 0.6f * rnd(&s.rng)), side = rnd(&s.rng);
            s.gt[0] = side < 0.25f ? 1.0f : depth;
            s.gt[1] = side >= 0.25f && side < 0.5f ? 1.0f : depth;
            s.timer = (uint32_t)((0.02f + 0.2f * rnd(&s.rng)) * FS);
        }

        for (int c = 0; c < 2; c++) {
            float x = ch[c][i];
            x = (x + sat_mix * (softclip(x * drive) * makeup - x)) * LINE_GAIN;   /* Saturate 0 = clean */
            x = x > 32767.0f ? 32767.0f : x < -32767.0f ? -32767.0f : x;
            GLBUF[(s.wpos & (LINE - 1)) * 2 + c] = (int16_t)x;
            float a = (float)GLBUF[((s.wpos - (uint32_t)di) & (LINE - 1)) * 2 + c];
            float b = (float)GLBUF[((s.wpos - (uint32_t)di - 1) & (LINE - 1)) * 2 + c];
            float y = (a + (b - a) * frac) * (1.0f / LINE_GAIN);
            s.g[c] += (s.gt[c] - s.g[c]) * 0.003f;
            y *= s.g[c];
            if (hicut > 0.0f) {
                s.lp1[c] += (y - s.lp1[c]) * lp_a;
                s.lp2[c] += (s.lp1[c] - s.lp2[c]) * lp_a;
                y = s.lp2[c];
            }
            if (locut > 0.0f) {
                s.hp[c] += (y - s.hp[c]) * hp_a;
                y -= s.hp[c];
            }
            ch[c][i] = y + hiss * (2.0f * rnd(&s.rng) - 1.0f);
        }
        s.wpos++;
    }
    for (unsigned i = 0; i < sizeof s / 4; i++)
        ((volatile uint32_t *)GL)[i] = ((volatile uint32_t *)&s)[i];
}

/* ---- Prism ---- */

typedef void (*line_alloc_fn)(int *line, int floats);
typedef uint32_t (*perm_alloc_fn)(uint32_t bytes, int one);
#define fw_line_alloc ((line_alloc_fn)FN(0x0806aa80))
#define fw_perm_alloc ((perm_alloc_fn)FN(0x0804436c))    /* bump allocator of the SDRAM pool; never freed */

/*
 * Replaces the last of the delay constructor's three line allocations (bl FUN_0806aa80 @0x0805462a): runs once per
 * boot, at the point where stock itself takes permanent SDRAM. Takes Prism's block after it.
 */
void master_alloc(int *line, int floats)
{
    instrument_boot();                                      /* fault.c: latch the breadcrumb trail from before the
                                                               reset, then arm the watchdog's early wakeup. Here
                                                               because this is the one hook that runs once per boot,
                                                               and it runs before any audio block. */
    fw_line_alloc(line, floats);
    uint32_t mem = fw_perm_alloc(PRISM_BYTES + EXTRA_BYTES, 1);
    bkp_enable();
    PRISM_MEM = mem;
    PRISM_CHECK = mem ^ PRISM_KEY;
    if (mem) {
        *(volatile uint32_t *)mem = 0;                       /* Prism and the LFOs start clean, whatever a reset left there */
        *(volatile uint32_t *)(mem + PRISM_BYTES) = 0;
        *(volatile uint32_t *)(mem + PRISM_BYTES + 0x7000u) = 0;
        *(volatile uint32_t *)(mem + PRISM_BYTES + 0xb000u) = 0;    /* insert.c's bank */
        *(volatile uint32_t *)(mem + PRISM_BYTES + 0x2d000u) = 0;   /* comp.c's clipper */
        *(volatile uint32_t *)(mem + PRISM_BYTES + 0x2d100u) = 0;   /* clipwin.c's bank */
    }
}

static uint8_t *prism_mem(void)
{
    uint32_t mem = PRISM_MEM;
    return mem >= 0xc0000000u && mem < 0xc4000000u - PRISM_BYTES - EXTRA_BYTES && (mem ^ PRISM_KEY) == PRISM_CHECK ? (uint8_t *)mem : 0;
}

/* lfo.c: the same block (its part starts PRISM_BYTES in) */
uint8_t *master_block(void)
{
    bkp_enable();
    return prism_mem();
}

static void prism(float bpm, float *l, float *r, int n)
{
    uint8_t *mem = prism_mem();
    if (!mem)
        return;                                              /* no memory (the boot hook did not run): pass through */
    struct prism_params p;
    for (int b = 0; b < 4; b++) {
        p.fx[b] = (uint32_t)fw_setting(SETTINGS, P_PR_FX + b);
        p.amt[b] = pct(P_PR_AMT + b);
    }
    p.tilt = pct(P_PR_TILT);
    p.rate = pct(P_PR_RATE);
    p.mix = pct(P_PR_MIX);
    p.time = (uint32_t)fw_setting(SETTINGS, P_PR_TIME);
    if (!b2_live())               /* Prism's DSP is in bank 2: bypass rather than fault on a bad one */
        return;
    prism_block(mem, &p, bpm, l, r, n);
}

/* Called by comp_process every block: is an effect selected? An effect that is not selected is cleared for its next start. */
int master_on(void)
{
    int type = fw_setting(SETTINGS, P_MFX);
    bkp_enable();
    if (type != MFX_VHS && GL->magic == MAGIC)
        GL->magic = 0;
    if (type != MFX_PRISM) {
        uint8_t *mem = prism_mem();
        if (mem && *(volatile uint32_t *)mem == PRISM_MAGIC)
            *(volatile uint32_t *)mem = 0;
    }
    return type == MFX_VHS || type == MFX_PRISM;
}

/* Called by comp_process with Out 1's channels, before the compressor. bpm: the preset tempo (0 if not known). */
void master_fx(float bpm, float *l, float *r, int n)
{
    if (fw_setting(SETTINGS, P_MFX) == MFX_PRISM)
        prism(bpm, l, r, n);
    else
        vhs(l, r, n);
}
