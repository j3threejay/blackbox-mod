/*
 * Munchi Delay in the delay slot (FX1). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Munchi Delay is Charles Vestal's port of CHOMPI TEMPO's dual delay (github charlesvestal/schwung-munchi-delay, MIT;
 * sources in src/munchi with their licenses): a clock-synced delay whose one "wand" knob goes, left of centre, to
 * random glitch repeats (retrigger / reverse / octave up / octave down) and, right of centre, into a diffusion reverb,
 * with a freeze and a sidechain that ducks the repeats under new material once the feedback is high. It runs here at
 * its native 48 kHz, on the stock delay's own memory.
 *
 * Selector: the unused list parameter 0x197 'FX1:' (fx1algo) becomes "Type:" [Delay, Munchi] and heads the delay's
 * settings. The knob screen has 8 slots, all taken by Type + the stock delay's 7, so the page lists the controls of the
 * selected type only (munchi_list). Munchi's are new parameters: "Wand:" 0x1d1 (0..100 %, 50 % = off, below =
 * glitch delay, above = delay into reverb; the distance from the middle picks the note length), "Random:" 0x1d2 (how
 * often a random event fires) and "Freeze:" 0x1d3; 3.1.m adds "Clock:" 0x1d4, "Width:" 0x1d5 and "Duck:" 0x1d6, which fill
 * the knob screen's 8 slots. Feedback is the delay's own (0x38), and so is the level.
 *
 * The delay's process wrapper (vtable 0x080d0660 +0xc = 0x08054f34) calls the stock process FUN_080548c8 at
 * 0x08054f3a; that call comes here. Type Delay: stock. Type Munchi: stock is not run; the send comes in through the
 * stock gate (FUN_0804f270) and the wet goes out the way stock's does (bus += level x wet).
 *
 * Memory (the stock delay's three lines, allocated in its constructor and only used by its process):
 *   line 1 (obj+0x30, 192256 floats)  -> Munchi's live buffer, 16-bit stereo: 192256 frames = 4.0 s
 *   line 3 (obj+0x68, 192256 floats)  -> the freeze buffer, same size
 *   line 2 (obj+0x4c, 96256 floats)   -> everything else (delay, reverb incl. its 64 KB, ducker, clock)
 * A delay longer than ~3 s (a bar below ~80 BPM, or at Clock 1/2x) is clamped to the buffer in granularDelay.h.
 * All of it is cleared when the type changes either way. A magic word guards the state: if anything else ever clears
 * the lines, the next block starts Munchi afresh instead of following zeroed pointers.
 *
 * MUNCHI_OFF (build.sh, 3.1.T): Munchi's engine is left out to make room in the code cave (about 7 KB). What stays is
 * everything the other types and old presets need: the Type list keeps its four places (the second reads "---" and
 * plays the stock delay, so Relapse and Confetti keep their saved values), and Munchi's six settings stay registered
 * with their defaults, so a preset saved with them carries them until the engine is back (build with MUNCHI=1).
 */
#include <stddef.h>
#include <stdint.h>
#include "motion.h"
#include <new>

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#ifndef MUNCHI_OFF
#include "munchi/tempo/granularDelay.h"
#include "munchi/tempo/reverb.h"
#include "munchi/tempo/SimpleCompressor.h"
#else
namespace daisysp {
static inline float fclamp(float x, float lo, float hi)
{
    return x < lo ? lo : x > hi ? hi : x;
}
}
#endif

#define FN(addr) ((addr) | 1u)

extern "C" {
void bkp_enable(void);
struct confetti_params {
    uint32_t mode, size;
    float repeats, density, contour, tone, space;
};
int b2_live(void);               /* cpu.c: is bank 2, where confetti_block lives, the matching payload */
int b2_present(void);            /* cpu.c: the same question for the Type list's names, asked before the meter is up */
void fxout_register(void *table);                         /* fxout.c: the FX OUT page's Level + Low Cut */
void fxout_defaults(void *store);
void fxout_run(int which, const void *store, float *l, float *r, int n);
int fxout_list(void *list, const void *store, int which);
void fxout_before_build(void);
void fxout_after_build(uint8_t *screen);
int fxout_tap(const uint16_t *msg);
void confetti_block(void *state, float *rev, int16_t *a, int16_t *b, uint32_t half, const struct confetti_params *p, float bpm,
                 const float *il, const float *ir, float *ol, float *orr, int n, int fresh);
void relapse_block(uint8_t *state, int16_t *a, int16_t *b, uint32_t half, const void *store, float bpm,
                 const float *il, const float *ir, float *ol, float *orr, int n, int fresh);
void *munchi_ready(uint8_t *obj, int fresh);              /* munchi_dsp.cpp (bank 2): the engine */
void munchi_run(void *state, const void *store, float bpm, const float *il, const float *ir, int n, float **wl,
                float **wr);
}

typedef int (*process_fn)(uint8_t *obj, uint32_t *bufs);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef void *(*bus_fn)(uint32_t *bufs, int ch);
typedef void (*ptrs_fn)(void *buf, float **l, float **r);
typedef int (*len_fn)(void *buf);
typedef void (*setlen_fn)(void *buf, int n);
typedef void (*gate_fn)(void *gate, void *bus);
typedef void (*gate_in_fn)(void *gate, void *bus, void **in, int consume);
typedef void (*mixadd_fn)(float gain, const float *src, int n, float *dst);
typedef void (*line_clear_fn)(void *line);
typedef int (*chan_fn)(uint8_t *obj);
typedef void (*list_fill_fn)(void *list, void *store);
typedef void (*list_remove_fn)(void *list, unsigned param);
typedef int (*cell_type_fn)(void *store);

#define fw_process       ((process_fn)FN(0x080548c8))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_bus           ((bus_fn)FN(0x0805f37c))
#define fw_ptrs          ((ptrs_fn)FN(0x0804d9c0))
#define fw_len           ((len_fn)FN(0x0804d8e8))
#define fw_setlen        ((setlen_fn)FN(0x0804d8d0))
#define fw_gate          ((gate_fn)FN(0x0804f0d4))
#define fw_gate_in       ((gate_in_fn)FN(0x0804f270))
#define fw_mixadd        ((mixadd_fn)FN(0x08061844))
#define fw_line_clear    ((line_clear_fn)FN(0x0806aac0))
#define fw_list_fill     ((list_fill_fn)FN(0x080a50fc))
#define fw_list_remove   ((list_remove_fn)FN(0x080a506c))
typedef void (*list_clear_fn)(void *list);
typedef void (*list_add_fn)(void *list, int param, int value);
#define fw_list_clear    ((list_clear_fn)FN(0x080a4fc2))
#define fw_list_add      ((list_add_fn)FN(0x080a5038))
#define FW_CHAN_DEFAULT  0x08046a15u

#define APP_FX       (0x24020088u + 0x2fc0u)    /* app: FX cell records, 0x18 each, by row */
#define OBJ_ID       0x18
#define OBJ_CHAN     0x1e
#define OBJ_LEVEL    0x2c                       /* float: the delay's output level (stock: obj[0xb]) */
#define OBJ_GATE     0xd0
#define OBJ_MIXADD   0x21f
#define LINE_LIVE    0x30
#define LINE_STATE   0x4c
#define LINE_FREEZE  0x68

#define P_TYPE   0x197
#define P_FEEDBK 0x38
#define P_WAND   0x1d1
#define P_RANDOM 0x1d2
#define P_FREEZE 0x1d3
#define P_CLOCK  0x1d4           /* 3.1.m: 1x / 1/2x / 2x: TEMPO's clock multiplier */
#define P_WIDTH  0x1d5           /* 3.1.m: stereo offset of the repeats: TEMPO's 20 / 10 ms, mono, x2.5, x5 */
#define P_DUCK   0x1d6           /* 3.1.m: sidechain ducking: Auto (TEMPO's: rises with Feedback past 60 %), Off, fixed */
#define P_MO_KIND  0x1bf         /* motion.c: Off / Trem / Filter / Duck / Swell on the repeats */
#define P_MO_RATE  0x1c0
#define P_MO_DEPTH 0x1c1
#define P_ROOM_FIRST 0x1d7       /* fx2.c: Room's Size / Mod / Early / Width, 0x1d7..0x1da */
#define P_ROOM_LAST  0x1da
#define P_FX2_TYPE   0x198
#define P_COMP_MODEL 0xb4
#define P_MASTER_FX  0x1db
#define CELL_REVERB  0x4b
#define ROOM 1
#define TYPE_PCT 8
#define CELL_DELAY 0x26

/*
 * Munchi and Motion had to SHARE one slot while the cave was full: `#define ALG_MOTION ALG_MUNCHI`, and which one
 * you got depended on MUNCHI_OFF. Bank 2 ended that (3.2.l: ~900 KB free up there), so they each have their own
 * place and both are in the build.
 * DELAY STAYS AT 0 because every existing preset's plain delay stores that index; Munchi takes 1 by request, and
 * Motion, Relapse and Confetti each shift one place, so presets saved on those come back one type EARLIER in the
 * list. That was accepted explicitly ("I don't really care if we push everything around in the tables").
 */
enum { ALG_DELAY, ALG_MUNCHI, ALG_MOTION, ALG_RELAPSE, ALG_CONFETTI, ALGS };
#ifndef MUNCHI_OFF
static const char *const type_names[ALGS] = {"Delay", "Munchi", "Motion", "Relapse", "Confetti"};
static const char *const type_names_none[ALGS] = {"Delay", "---", "---", "---", "---"};   /* no bank 2 payload (Munchi's engine too since 3.3.y) */
#else
static const char *const type_names[ALGS] = {"Delay", "---", "Motion", "Relapse", "Confetti"};
static const char *const type_names_none[ALGS] = {"Delay", "---", "---", "---", "---"};
#endif
/* Confetti (confetti.c), 3.1.z: Mode / Density / Contour / Space; it shares Relapse's Size and Tone and the delay's Feedback */
#define P_CF_MODE   0x1ec
#define P_CF_DENSITY    0x1ed
#define P_CF_CONTOUR  0x1ee
#define P_CF_SPACE  0x1ef
static const char *const cf_mode_names[6] = {"Loops", "Cloud", "Slide", "Stutter", "Arp", "Taps"};
#define CONFETTI_REV   0x2000                                /* line 2: Confetti' reverb lines sit after its wet blocks */
#define CONFETTI_REV_FLOATS 12234
/* Relapse (relapse.c), 3.1.s: Size / Recall / Reach / Twist / Tone / Feed, with Type and Feedback = the page's 8 slots */
#define P_RL_SIZE   0x1e3
#define P_RL_RECALL   0x1e4
/* 0x1e5 is NOT free: stock's cell get / set (FUN_08099504 / FUN_0809fa50) special-case it as a one-byte flag at
   app+0x8cc7, so a knob on it reads 0 / 1 and snaps back (3.1.s had Spread there: as reported). Spread is 0x1e9. */
#define P_RL_REACH 0x1e9
#define P_RL_TWIST 0x1e6
#define P_RL_TONE   0x1e7
#define P_RL_FEED   0x1e8
static const char *const rl_size_names[9] = {"1/32", "1/16", "1/8T", "1/8", "1/8D", "1/4", "1/4D", "1/2", "1 Bar"};
static const char *const rl_twist_names[5] = {"Off", "Reverse", "Oct Dn", "Oct Up", "Stutter"};
#define RELAPSE_OUT 0x1000                                  /* line 2: Relapse's two wet blocks sit after its state */
static const char *const freeze_names[2] = {"Off", "On"};
static const char *const clock_names[3] = {"1x", "1/2x", "2x"};
static const char *const width_names[4] = {"TEMPO", "Mono", "Wide", "Huge"};
static const char *const duck_names[4] = {"Auto", "Off", "Light", "Heavy"};

/*
 * Which type ran last, in BACKUP SRAM - which survives a reset AND A REFLASH. That is a trap: `fresh` is decided
 * by comparing it with the selected type, and 3.2.m RENUMBERED the list (Munchi took slot 1, so Motion, Relapse
 * and Confetti each moved up one). A value stored by the old numbering then reads as a different type under the
 * new one, `fresh` comes out false, the three delay lines are NOT cleared, and the new type reads the old type's
 * state as its own. On the test unit that crashed the moment scrolling reached Relapse, which now has the number
 * Confetti used to have (2026-10-11).
 * So the stored value carries an epoch, and anything that does not match it counts as "unknown" - which never
 * equals a real type, so the lines always get cleared. BUMP MODE_EPOCH WHENEVER THE TYPE NUMBERING CHANGES.
 */
/*
 * BREADCRUMBS, into fault.c's ring (3.2.q). 3.2.p wrote the single word at 0x38800fc0, which the delay rewrites on
 * EVERY audio block - so the watchdog reset the unit, the app came back up, and the crumb described the rebooted
 * unit before anyone could read it (proved on the test unit: a sentinel poked in was gone within one block). The ring is
 * copied to a saved area once per boot, before any audio runs, so what survives is the trail INTO the hang.
 * Six slots, consecutive repeats dropped. Read SAVED at 0x38800fe8 over the USB peek; see src/fault.c.
 */
extern "C" void crumb_drop(uint32_t v, uint32_t which);
extern "C" void audio_watch(uint32_t sp);
#define DROP(step, alg) crumb_drop(((uint32_t)(step) << 8) | ((uint32_t)(alg) & 0xffu), 0)   /* audio ring */
#define DROP_GUI(step, alg) crumb_drop(((uint32_t)(step) << 8) | ((uint32_t)(alg) & 0xffu), 1)
static inline uint32_t stack_now(void)
{
    uint32_t sp;
    __asm volatile("mov %0, sp" : "=r"(sp));
    return sp;
}

#define MODE_RAW (*(volatile uint32_t *)0x38800b14u)
#define MODE_EPOCH 0x4d32u                                /* "M2": the five-slot numbering */
#define MODE_UNKNOWN 0xffu
#define MODE_GET ((MODE_RAW >> 16) == MODE_EPOCH ? (MODE_RAW & 0xffu) : MODE_UNKNOWN)
#define MODE_SET(a) (MODE_RAW = ((uint32_t)MODE_EPOCH << 16) | ((uint32_t)(a) & 0xffu))
/*
 * 3.3.y: a type change clears the three lines over several blocks instead of in one. All three at once is ~1.9 MB of
 * SDRAM, 4.5 ms in a 2.67 ms block (NOTES: the fx1 spikes of up to 416 % in the profiler reading, 10-20). While the
 * clear runs MODE_RAW holds CLR_EPOCH | chunks done << 8 | the type it is for, the slot gives silence, and the type
 * starts (fresh) in the block AFTER the last chunk (CLR_DONE), so its own start-up never shares a block with clearing.
 * CLR_WORDS a block: ~0.3 ms on the unit (stock's clear ran at ~9 ns a word), about what the slot's own DSP costs, so
 * 15 blocks + 1 = ~43 ms of silence after a change. A change during the clear carries on with it (every type wants
 * all three lines clear); a reset in the middle of one finishes it on the next boot.
 */
#define CLR_EPOCH 0x4d43u                                 /* "MC" */
#define CLR_WORDS 32768u                                  /* 128 KB a block */
#define CLR_DONE  0xffu                                   /* all chunks done: the next block starts the type */
/* motion.c's state: the gap behind the USB-MIDI queue (ends 0x38800988), ahead of master.c's UI at 0x38800b1c */
#define MOTION_ST ((struct motion_state *)0x38800990u)
#ifdef MUNCHI_OFF
#define MUNCHI_BUILT 0
#else
#define MUNCHI_BUILT 1
#endif
#define MAXN 128


static inline void *line_ptr(uint8_t *obj, int line)
{
    return *(void **)(obj + line);
}

static inline uint32_t line_floats(uint8_t *obj, int line)
{
    return *(uint32_t *)(obj + line + 0x14);
}

extern "C" {

/* the compiler's own zeroing (value-initialising Munchi) calls this; there is no C library */
void *memset(void *d, int c, size_t n)
{
    uint8_t *p = (uint8_t *)d;
    while (n--)
        *p++ = (uint8_t)c;
    return d;
}

/* Replaces the registration of 0x197 (bl @0x0808de8e): the type list, then Munchi's three settings. */
void munchi_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Type:", b2_present() ? type_names : type_names_none, ALGS, xml);
    fw_register_num(table, P_WAND, TYPE_PCT, "Wand:", 0, 1000, "munchiwand");
    fw_register_num(table, P_RANDOM, TYPE_PCT, "Random:", 0, 1000, "munchirandom");
    fw_register_list(table, P_FREEZE, "Freeze:", freeze_names, 2, "munchifreeze");
    fw_register_list(table, P_CLOCK, "Clock:", clock_names, 3, "munchiclock");
    fw_register_list(table, P_WIDTH, "Width:", width_names, 4, "munchiwidth");
    fw_register_list(table, P_DUCK, "Duck:", duck_names, 4, "munchiduck");
    fw_register_list(table, P_RL_SIZE, "Size:", rl_size_names, 9, "relapsesize");
    fw_register_num(table, P_RL_RECALL, TYPE_PCT, "Recall:", 0, 1000, "relapserecall");
    fw_register_num(table, P_RL_REACH, TYPE_PCT, "Reach:", 0, 1000, "relapsereach");
    fw_register_list(table, P_RL_TWIST, "Twist:", rl_twist_names, 5, "relapsetwist");
    fw_register_num(table, P_RL_TONE, TYPE_PCT, "Tone:", 0, 1000, "relapsetone");
    fw_register_list(table, P_RL_FEED, "Feed:", freeze_names, 2, "relapsefeed");
    fw_register_list(table, P_CF_MODE, "Mode:", cf_mode_names, 6, "confettimode");
    fw_register_num(table, P_CF_DENSITY, TYPE_PCT, "Density:", 0, 1000, "confettidensity");
    fw_register_num(table, P_CF_CONTOUR, TYPE_PCT, "Contour:", 0, 1000, "confetticontour");
    fw_register_num(table, P_CF_SPACE, TYPE_PCT, "Space:", 0, 1000, "confettispace");
    static const char *const motion_names[MOTION_TYPES] = {"Off", "Trem", "Filter", "Duck", "Swell"};
    fw_register_list(table, P_MO_KIND, "Motion:", motion_names, MOTION_TYPES, "motionkind");
    fw_register_num(table, P_MO_RATE, TYPE_PCT, "Rate:", 0, 1000, "motionrate");
    fw_register_num(table, P_MO_DEPTH, TYPE_PCT, "Depth:", 0, 1000, "motiondepth");
    fxout_register(table);                  /* Level + Low Cut, for both effects (fxout.c) */
}

/* Replaces the delay cell's first default, Time 400 (bl @0x0809444a): Type first. */
void munchi_defaults_first(void *store, int param, int value)
{
    fw_store_add(store, P_TYPE, ALG_DELAY);
    fw_store_add(store, param, value);
}

/* Replaces the delay cell's last default, Ping Pong on (bl @0x08094494): Munchi's settings at the end. */
void munchi_defaults_last(void *store, int param, int value)
{
    fw_store_add(store, param, value);
    fw_store_add(store, P_WAND, 250);
    fw_store_add(store, P_RANDOM, 300);
    fw_store_add(store, P_FREEZE, 0);
    fw_store_add(store, P_CLOCK, 0);
    fw_store_add(store, P_WIDTH, 0);
    fw_store_add(store, P_DUCK, 0);
    fw_store_add(store, P_RL_SIZE, 5);
    fw_store_add(store, P_RL_RECALL, 400);
    fw_store_add(store, P_RL_REACH, 500);
    fw_store_add(store, P_RL_TWIST, 0);
    fw_store_add(store, P_RL_TONE, 300);
    fw_store_add(store, P_RL_FEED, 0);
    fw_store_add(store, P_CF_MODE, 0);
    fw_store_add(store, P_CF_DENSITY, 500);
    fw_store_add(store, P_CF_CONTOUR, 500);
    fw_store_add(store, P_CF_SPACE, 300);
    fw_store_add(store, P_MO_KIND, MOTION_TREM);
    fw_store_add(store, P_MO_RATE, 400);
    fw_store_add(store, P_MO_DEPTH, 600);
    fxout_defaults(store);
}

/*
 * Replaces the settings-list fill in the page builder (bl FUN_080a50fc @0x08098e72). The FX knob screen shows the first
 * 8 entries only (FUN_080a87b6), and the stock delay already has 7 (Delay, Feedback, Width, Cutoff, Beat, Filter,
 * Ping), so the delay's list depends on its Type: Delay shows Type + the stock 7, Munchi shows Type, Feedback, Wand,
 * Random, Freeze.
 */
void munchi_list(void *list, void *store)
{
    static const uint16_t stock_only[] = {0x32, 0x33, 0x0e, 0xca, 0x34, 0xc9, 0x35};
    static const uint16_t munchi_only[] = {P_WAND, P_RANDOM, P_CLOCK, P_WIDTH, P_DUCK, P_FREEZE};
    DROP_GUI(18, 0);                        /* GUI: in, before stock's fill */
    fw_list_fill(list, store);
    DROP_GUI(19, 0);                        /* GUI: the fill returned */
    int cell = (*(cell_type_fn *)*(uint8_t **)store)(store);
    if (fxout_list(list, store, cell == CELL_DELAY ? 1 : cell == CELL_REVERB ? 2 : 0))
        return;                             /* the OUT page: Level, Low Cut (fxout.c) */
    if (cell == CELL_REVERB) {               /* Room's four settings only when Type is Room */
        if (fw_setting(store, P_FX2_TYPE) != ROOM)
            for (unsigned id = P_ROOM_FIRST; id <= P_ROOM_LAST; id++)
                fw_list_remove(list, id);
        return;
    }
    if (cell != CELL_DELAY)
        return;
    int type = fw_setting(store, P_TYPE);
    DROP_GUI(20, type);                     /* GUI: building the page for this type */
    if (type == ALG_CONFETTI) {                 /* its own order: what to play on the first four knobs, how on the next */
        static const uint16_t confetti_page[8] = {P_TYPE, P_CF_MODE, P_RL_SIZE, P_CF_DENSITY, P_CF_CONTOUR, P_FEEDBK, P_RL_TONE, P_CF_SPACE};
        fw_list_clear(list);
        for (unsigned i = 0; i < 8; i++)
            fw_list_add(list, confetti_page[i], fw_setting(store, confetti_page[i]));
        return;
    }
    static const uint16_t motion_only[] = {P_MO_KIND, P_MO_RATE, P_MO_DEPTH};
    const int is_motion = (type == ALG_MOTION);
    if (is_motion) {
        /* the fill already carries the motion's three: only make room for them by dropping the stock controls the
           8-slot screen cannot fit (3.2.a listed Motion twice by adding them a second time) */
        static const uint16_t drop[] = {0x0e, 0xca, 0xc9, 0x35};
        for (unsigned i = 0; i < sizeof drop / sizeof *drop; i++)
            fw_list_remove(list, drop[i]);
    } else {
        for (unsigned i = 0; i < sizeof motion_only / sizeof *motion_only; i++)
            fw_list_remove(list, motion_only[i]);
    }
    static const uint16_t confetti_only[] = {P_CF_MODE, P_CF_DENSITY, P_CF_CONTOUR, P_CF_SPACE};
    for (unsigned i = 0; i < sizeof confetti_only / sizeof *confetti_only; i++)
        fw_list_remove(list, confetti_only[i]);
    if (type != ALG_DELAY && !is_motion)      /* Motion runs the stock delay, so it keeps stock's own controls */
        for (unsigned i = 0; i < sizeof stock_only / sizeof *stock_only; i++)
            fw_list_remove(list, stock_only[i]);
    if (type != ALG_MUNCHI || !MUNCHI_BUILT)
        for (unsigned i = 0; i < sizeof munchi_only / sizeof *munchi_only; i++)
            fw_list_remove(list, munchi_only[i]);
    if (type != ALG_RELAPSE) {
        static const uint16_t relapse_only[] = {P_RL_SIZE, P_RL_RECALL, P_RL_REACH, P_RL_TWIST, P_RL_TONE, P_RL_FEED};
        for (unsigned i = 0; i < sizeof relapse_only / sizeof *relapse_only; i++)
            fw_list_remove(list, relapse_only[i]);
    }
    DROP_GUI(21, type);                     /* GUI: the page for this type is built and we are leaving */
}


/* the send in (through the stock gate) and the block length */
static int slot_in(uint8_t *obj, uint32_t *bufs, void **bus, float **il, float **ir)
{
    chan_fn chan = *(chan_fn *)(*(uint8_t **)obj + 0x54);
    int ch = (uint32_t)chan == FW_CHAN_DEFAULT ? *(uint16_t *)(obj + OBJ_CHAN) : chan(obj);
    *bus = fw_bus(bufs, ch);
    int n = fw_len(*bus);
    if (n > MAXN)
        n = MAXN;
    fw_gate(obj + OBJ_GATE, *bus);
    void *in = nullptr;
    fw_gate_in(obj + OBJ_GATE, *bus, &in, 1);
    *il = *ir = nullptr;
    fw_ptrs(in, il, ir);
    return n;
}

/* the wet out, the way stock's goes: bus += level x wet */
static void slot_out(uint8_t *obj, void *bus, const float *wl, const float *wr, int n)
{
    float *ol = nullptr, *orr = nullptr;
    fw_ptrs(bus, &ol, &orr);
    fw_setlen(bus, n);
    float level = *(float *)(obj + OBJ_LEVEL);
    if (obj[OBJ_MIXADD]) {
        fw_mixadd(level, wl, n, ol);
        fw_mixadd(level, wr, n, orr);
    } else {
        for (int i = 0; i < n; i++) {
            ol[i] = wl[i];
            orr[i] = wr[i];
        }
    }
}

/* One chunk of the type-change clear: words [k * CLR_WORDS, (k + 1) * CLR_WORDS) of the three lines taken end to end.
   Returns 1 when that was the last; then the lines' positions are reset as stock's clear (FUN_0806aac0) does. */
static int clear_chunk(uint8_t *obj, uint32_t k)
{
    static const uint8_t lines[3] = {LINE_LIVE, LINE_STATE, LINE_FREEZE};
    uint32_t from = k * CLR_WORDS, to = from + CLR_WORDS, base = 0;
    for (int i = 0; i < 3; i++) {
        uint32_t *line = (uint32_t *)(obj + lines[i]);
        uint32_t *w = (uint32_t *)line[0], words = w ? line[5] : 0;    /* +0x14: floats, the 0x100 guard included */
        uint32_t a = from > base ? from - base : 0, b = to - base < words ? to - base : words;
        if (to > base && b > a) {
            uint32_t *p = w + a, *e = w + b;
            for (; p + 4 <= e; p += 4)
                p[0] = p[1] = p[2] = p[3] = 0;
            for (; p < e; p++)
                *p = 0;
        }
        base += words;
    }
    if (to < base)
        return 0;
    for (int i = 0; i < 3; i++) {
        uint32_t *line = (uint32_t *)(obj + lines[i]);
        line[1] = line[4];
        line[2] = line[3] = 0;
    }
    return 1;
}

/* The slot gives nothing this block (a clear is under way): the send is taken as usual, the bus carries no wet. */
static void slot_quiet(uint8_t *obj, uint32_t *bufs)
{
    void *bus;
    float *il, *ir, *ol = nullptr, *orr = nullptr;
    int n = slot_in(obj, bufs, &bus, &il, &ir);
    fw_ptrs(bus, &ol, &orr);
    fw_setlen(bus, n);
    if (!obj[OBJ_MIXADD])
        for (int i = 0; i < n; i++)
            ol[i] = orr[i] = 0.f;
}

/* The delay slot itself: the selected Type, or the stock delay. */
static int delay_slot(uint8_t *obj, uint32_t *bufs)
{
    unsigned row = (*(uint32_t *)(obj + OBJ_ID) >> 8) & 0xff;
    const void *store = (const void *)(APP_FX + (row < 5 ? row : 0) * 0x18u);
    audio_watch(stack_now());           /* the stack the audio task runs the delay at: a stacking fault is the one
                                           fault class the recorder cannot survive, so watch for it instead */
    DROP(1, row);                       /* in, before the settings read: 3.2.p had no step 1, so a hang before the
                                           clear left a stale crumb that read as whatever ran last */
    unsigned alg = row < 5 ? (unsigned)fw_setting(store, P_TYPE) : ALG_DELAY;
    if (alg >= ALGS)
        alg = ALG_DELAY;
    DROP(12, alg);                      /* the settings read returned: a spin inside it stops at step 1 */
    int motion_kind = 0;
    /*
     * Confetti's DSP is in bank 2. When bank 2 is not live it has to BE the stock delay from here on, not merely
     * call it: 3.2.m - 3.2.t fell back further down, after `fresh` had been worked out for Confetti, and stamped
     * MODE as Delay on the way out - so the next block saw "Confetti selected, Delay ran last", cleared all three
     * lines again, and did that EVERY block. 4.5 ms of clearing in a 2.67 ms block ran the engine at about a
     * quarter speed (103 blocks a second on the test unit, button lights stuttering) for as long as bank 2 stayed off
     * with Confetti selected - which is the state every bank 2 rewrite passes through.
     */
    if ((alg == ALG_CONFETTI || alg == ALG_RELAPSE || alg == ALG_MOTION || alg == ALG_MUNCHI) && !b2_live())
        alg = ALG_DELAY;                /* 3.3.o: Relapse's and Motion's DSP moved up to bank 2 beside Confetti's;
                                           3.3.y: Munchi's engine too (munchi_dsp.cpp) */
    if (alg == ALG_MOTION) {                    /* Motion runs the stock delay, so it keeps stock's lines and MODE */
        alg = ALG_DELAY;
        motion_kind = fw_setting(store, P_MO_KIND);
        if (motion_kind < 0 || motion_kind >= MOTION_TYPES)
            motion_kind = 0;
    }
    bkp_enable();
    /*
     * An unmatched epoch counts as "the stock delay ran last", not as a type of its own: stock owns these three
     * lines and clearing them under it is not ours to do. Any of our types then still sees fresh == true and gets
     * its clear, which is the case that was crashing; plain Delay sees fresh == false and stock is left alone.
     */
    const unsigned raw = MODE_GET;
    const unsigned mode_was = (raw == MODE_UNKNOWN) ? (unsigned)ALG_DELAY : raw;
    int fresh = mode_was != (unsigned)alg;
    uint32_t clr = MODE_RAW, k = (clr >> 16) == CLR_EPOCH ? (clr >> 8) & 0xffu : 0;
    if ((clr >> 16) == CLR_EPOCH && k == CLR_DONE) {
        fresh = 1;                      /* the lines were cleared in the blocks before this one: start the type */
    } else if ((clr >> 16) == CLR_EPOCH || fresh) {   /* the three lines change hands: nothing of the old type stays */
        DROP(2, alg);                   /* clearing a chunk of the three lines */
        int last = clear_chunk(obj, k) || k + 1 >= CLR_DONE;
        MODE_RAW = ((uint32_t)CLR_EPOCH << 16) | ((last ? CLR_DONE : k + 1) << 8) | ((uint32_t)alg & 0xffu);
        DROP(last ? 5 : 3, alg);        /* 5: all three cleared */
        slot_quiet(obj, bufs);
        return 1;
    }
    void *bus;
    float *il, *ir;

    if (alg == ALG_CONFETTI) {
        uint8_t *st = (uint8_t *)line_ptr(obj, LINE_STATE);
        int16_t *a = (int16_t *)line_ptr(obj, LINE_LIVE), *b = (int16_t *)line_ptr(obj, LINE_FREEZE);
        uint32_t half = line_floats(obj, LINE_LIVE);
        if (line_floats(obj, LINE_FREEZE) < half)
            half = line_floats(obj, LINE_FREEZE);
        if (st && a && b && half > 96000 && line_floats(obj, LINE_STATE) * 4 >= CONFETTI_REV + CONFETTI_REV_FLOATS * sizeof(float)) {
            MODE_SET(ALG_CONFETTI);
            float *wl = (float *)(st + RELAPSE_OUT), *wr = wl + MAXN;
            confetti_params p;
            p.mode = (uint32_t)fw_setting(store, P_CF_MODE);
            p.size = (uint32_t)fw_setting(store, P_RL_SIZE);
            p.repeats = (float)fw_setting(store, P_FEEDBK) * .001f;
            p.density = daisysp::fclamp((float)fw_setting(store, P_CF_DENSITY) * .001f, 0.f, 1.f);
            p.contour = daisysp::fclamp((float)fw_setting(store, P_CF_CONTOUR) * .001f, 0.f, 1.f);
            p.tone = (float)fw_setting(store, P_RL_TONE) * .001f;
            p.space = (float)fw_setting(store, P_CF_SPACE) * .001f;
            int n = slot_in(obj, bufs, &bus, &il, &ir);
            confetti_block(st, (float *)(st + CONFETTI_REV), a, b, half, &p, *(float *)((uint8_t *)bufs[0] + 0x18), il, ir, wl, wr, n, fresh);
            slot_out(obj, bus, wl, wr, n);
            return 1;
        }
        alg = ALG_DELAY;
    }
    if (alg == ALG_RELAPSE) {
        uint8_t *st = (uint8_t *)line_ptr(obj, LINE_STATE);
        int16_t *a = (int16_t *)line_ptr(obj, LINE_LIVE), *b = (int16_t *)line_ptr(obj, LINE_FREEZE);
        uint32_t half = line_floats(obj, LINE_LIVE);
        if (line_floats(obj, LINE_FREEZE) < half)
            half = line_floats(obj, LINE_FREEZE);
        if (st && a && b && half > 96000 && line_floats(obj, LINE_STATE) * 4 >= RELAPSE_OUT + 2 * MAXN * sizeof(float)) {
            DROP(6, alg);               /* relapse guard passed, about to render */
            MODE_SET(ALG_RELAPSE);
            float *wl = (float *)(st + RELAPSE_OUT), *wr = wl + MAXN;
            int n = slot_in(obj, bufs, &bus, &il, &ir);
            relapse_block(st, a, b, half, store, *(float *)((uint8_t *)bufs[0] + 0x18), il, ir, wl, wr, n, fresh);
            slot_out(obj, bus, wl, wr, n);
            return 1;
        }
        alg = ALG_DELAY;
    }
#ifndef MUNCHI_OFF
    if (alg == ALG_MUNCHI) {
        void *m = munchi_ready(obj, fresh);
        DROP(7, alg);                   /* munchi branch */
        MODE_SET(ALG_MUNCHI);
        if (m) {
            int mn2 = slot_in(obj, bufs, &bus, &il, &ir);
            float *wl, *wr;
            munchi_run(m, store, *(float *)((uint8_t *)bufs[0] + 0x18), il, ir, mn2, &wl, &wr);
            slot_out(obj, bus, wl, wr, mn2);
            return 1;
        }
        return fw_process(obj, bufs);
    }
#endif
    MODE_SET(ALG_DELAY);
    DROP(8, alg);                       /* falling through to the stock delay */
    if (motion_kind == 0) {
        int rc = fw_process(obj, bufs);
        DROP(9, alg);                   /* stock returned */
        return rc;
    }
    /* The delay slot is a send: before stock runs, the bus holds what the pads sent it (the sidechain for Duck and
       Swell); after it, the bus holds the repeats, which is what the motion rides on. */
    chan_fn chan = *(chan_fn *)(*(uint8_t **)obj + 0x54);
    int ch = (uint32_t)chan == FW_CHAN_DEFAULT ? *(uint16_t *)(obj + OBJ_CHAN) : chan(obj);
    void *mbus = fw_bus(bufs, ch);
    int mn = fw_len(mbus);
    if (mn > MAXN)
        mn = MAXN;
    float *ml = nullptr, *mr = nullptr;
    fw_ptrs(mbus, &ml, &mr);
    float peak = 0.f;
    if (ml)
        for (int i = 0; i < mn; i++) {
            float a = ml[i] < 0.f ? -ml[i] : ml[i];
            if (a > peak)
                peak = a;
        }
    DROP(10, alg);                      /* motion: stock first */
    int ok = fw_process(obj, bufs);
    DROP(11, alg);
    ml = mr = nullptr;
    fw_ptrs(mbus, &ml, &mr);
    if (ml && mn > 0)
        motion_block(MOTION_ST, motion_kind, (float)fw_setting(store, P_MO_RATE) * .001f,
                     (float)fw_setting(store, P_MO_DEPTH) * .001f, peak, ml, mr, mn);
    return ok;
}

/* Replaces the delay process call in the delay's vtable wrapper (bl FUN_080548c8 @0x08054f3a): the slot, whatever
   its Type, then the FX OUT page's Level + Low Cut on the slot's bus, which holds the wet and nothing else by now. */
#ifdef CPU_PROF
#define munchi_process munchi_process_body /* prof.c times it under the hooked name */
#endif
int munchi_process(uint8_t *obj, uint32_t *bufs)
{
    int rc = delay_slot(obj, bufs);
    unsigned row = (*(uint32_t *)(obj + OBJ_ID) >> 8) & 0xff;
    if (row >= 5)
        return rc;
    chan_fn chan = *(chan_fn *)(*(uint8_t **)obj + 0x54);
    int ch = (uint32_t)chan == FW_CHAN_DEFAULT ? *(uint16_t *)(obj + OBJ_CHAN) : chan(obj);
    void *bus = fw_bus(bufs, ch);
    int n = bus ? fw_len(bus) : 0;
    if (n > MAXN)
        n = MAXN;
    float *l = nullptr, *r = nullptr;
    if (n > 0)
        fw_ptrs(bus, &l, &r);
    if (l)
        fxout_run(0, (const void *)(APP_FX + row * 0x18u), l, r, n);
    return rc;
}

/*
 * The FX knob screen's message handler (vtable 0x080f07e0 +0x10 = FUN_080ab900). Message 0x32 updates one knob's
 * value in place; message 0x66 rebuilds the whole page from the settings list. The page only rebuilt on some other
 * event, so after turning Type the old type's controls stayed until later (the 3.1.l report: the delay's Beat / Filter
 * / Ping buttons lingered on the Munchi page). When a 0x32 lands on a Type slot (0x197 delay, 0x198 reverb), follow it
 * with a 0x66, so the page always shows the selected type's controls. UI task, like the handler itself.
 * Slot layout (FUN_080a86a0): knob view at screen +0x450, its page at +0x3c, slot k at +0x40 + k * 0x3d0, the slot's
 * parameter id at slot +0x94 (= view + 0xd4 + k * 0x3d0, as FUN_080a8598 reads it).
 */
typedef void (*screen_msg_fn)(uint8_t *screen, const uint16_t *msg);
#define fw_screen_msg ((screen_msg_fn)FN(0x080ab900))
#define GUI_PTR    0x24002e6cu   /* the GUI task's object pointer (literal @0x08043e54) */
#define GUI_HOLDER 0x280         /* GUI: current-view holder; +0x38 / +0x39 = redraw / full redraw wanted */


void fx_screen_msg(uint8_t *screen, const uint16_t *msg)
{
    const int build = msg && (msg[0] == 0x66 || msg[0] == 0x67);
    if (build)
        fxout_before_build();
    fw_screen_msg(screen, msg);
    if (build)
        fxout_after_build(screen);           /* the OUT tab, or the empty tab back on a page that is not an effect's */
    if (!msg || msg[0] != 0x32)
        return;
    uint8_t *view = screen + 0x450;
    int slot = (int)*(const int16_t *)((const uint8_t *)msg + 0xc) + *(int32_t *)(view + 0x3c) * 4;
    if (slot < 0 || slot >= 8)
        return;
    uint16_t id = *(uint16_t *)(view + 0xd4 + slot * 0x3d0);
    if (id != P_TYPE && id != P_FX2_TYPE && id != P_COMP_MODEL && id != P_MASTER_FX && id != 0x1b6)
        return;                          /* the master pages (master.c) and a pad's insert page (0x1b6 = its Type,
                                            insert.c) also show per-type knobs */
    uint16_t rebuild[16] = {0x66};
    DROP_GUI(30, id & 0xffu);                /* GUI: into stock's handler a second time, from inside its own 0x32 */
    fxout_before_build();
    fw_screen_msg(screen, rebuild);
    fxout_after_build(screen);
    DROP_GUI(31, id & 0xffu);                /* GUI: it came back out */
    /* The rebuild hides the slots the new type does not use, but hidden widgets are only skipped, not erased: going
     * Room -> Plate left four bare knob arcs on the right (the 3.1.n photo). Ask for the full clear + redraw the GUI
     * does on a screen switch (FUN_080ab4fc sets the same two flags; FUN_0808b2d0 consumes them next frame). */
    uint8_t *gui = *(uint8_t *volatile *)GUI_PTR;
    if (gui) {
        gui[GUI_HOLDER + 0x38] = 1;
        gui[GUI_HOLDER + 0x39] = 1;
    }
}

/*
 * The knob screen's handler for what its children send up (vtable 0x080f07bc +0x30 = FUN_080ab9b4): a tab tap arrives
 * as message 1 with the tab's id at +0xc, which stock turns into an app message of that type. A tap on the OUT tab
 * (fxout.c) flips the effect between its knobs and its OUT page instead, and rebuilds the page. UI task.
 */
typedef int (*child_msg_fn)(uint8_t *screen, const uint16_t *msg);
#define fw_screen_child ((child_msg_fn)FN(0x080ab9b4))

int fx_screen_child(uint8_t *screen, const uint16_t *msg)
{
    if (!fxout_tap(msg))
        return fw_screen_child(screen, msg);
    uint16_t rebuild[16] = {0x66};
    fx_screen_msg(screen, rebuild);           /* a rebuild keeps the page; only an open drops it (fxout_open) */
    uint8_t *gui = *(uint8_t *volatile *)GUI_PTR;
    if (gui) {                                /* the full clear + redraw: the two pages have different knob counts */
        gui[GUI_HOLDER + 0x38] = 1;
        gui[GUI_HOLDER + 0x39] = 1;
    }
    return 0;
}

}  /* extern "C" */
