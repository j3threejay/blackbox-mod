/*
 * ChopShop: a fifth pad mode in the Mode list that is a Slicer underneath (0x8b = 2) plus the flag P_CHOP, so a project
 * stays a plain Slicer on stock firmware. Original 1010music Blackbox, firmware 3.1.9. research/slicer/MODE_LIST_RE.md.
 *
 * The list (data patch): Sample, Clip, Slicer, ChopShop, Granular, New Rec, New Multi (7 entries; stock has 6). The
 * popups give a POSITION; chop_set maps it to the stored value before stock's set handler sees it (stock sends the raw
 * value to the engine first): 3 -> Slicer + flag, 4.. -> 3.. The two popup highlights map back.
 * Entering ChopShop: Launch Mode Gate (a chop plays while the pad is held), Sync on and Stretch Cyclic (Stock does
 * not stretch a chop at all; Cyclic is the lightest model). Its POS page gets three rows of ours, at the top of the page: Chop (Off, 1/4, 1/2, Beat, 2 Beats, Bar, Find, Random: picking one runs it, chop.c; the same setting is
 * the ChopShop flag), Roll (any turn rolls new Find / Random chops; not stored) and Tempo (1/2, x1, x2 on the
 * detected tempo: kept in P_SEL_BEATS, unused on Slicer pads; a new sample or a mode change resets it). A new sample on a ChopShop pad keeps it ChopShop and chops it again.
 * CPU: none per audio block; UI events only.
 */
#include <stdint.h>
#include "chop.h"

#define FN(addr) ((addr) | 1u)
typedef int (*setting_fn)(const void *store, int param);
typedef void (*set_fn)(void *store, int param, int value);
typedef uint8_t *(*cell_fn)(uint8_t *app, void *ref);
typedef int (*set_param_fn)(uint8_t *app, void *ref, int id, int value, int extra);
typedef int (*popup_fn)(uint8_t *popup, int pos, int a, int b);
typedef int (*pages_fn)(uint8_t *app, void *ref, void *list, int page);
typedef void (*row_add_fn)(void *list, int id, int value);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef void (*app_post_fn)(uint8_t *queue, void *msg);
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_set           ((set_fn)FN(0x08093ecc))
#define fw_cell          ((cell_fn)FN(0x08098d0c))
#define fw_set_param     ((set_param_fn)FN(0x0809fa50))
#define fw_popup_value   ((popup_fn)FN(0x080bd74e))
#define fw_pages         ((pages_fn)FN(0x08098d40))
#define fw_row_add       ((row_add_fn)FN(0x080a5038))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_app_post      ((app_post_fn)FN(0x080b5758))

#define P_MODE       0x8b
#define P_LAUNCH     0x93       /* Trigger, Gate, Toggle */
#define P_SLICESYNC  0xf4
#define P_STRETCH    0x14c      /* stretch.c: Stock, Smooth, Keyframe, Cyclic */
#define STRETCH_CYCLIC 3
#define P_CHOP       0x14d      /* 0 = not ChopShop, 1 = ChopShop with Chop Off, 2.. = the chop type (one store entry: a pad
                                   store holds 96 and a Sample pad is at 95 with it; test_savexml checks the cap) */
#define P_CHOP_ROLL  0x161      /* Roll: a row with no store entry (any turn re-rolls; nothing to save) */
#define P_CHOP_TEMPO 0x162      /* Tempo: 1/2, x1, x2 on the detected tempo (10-27: the detector can read a song at half time).
                                   No store entry of its own: kept in P_SEL_BEATS (chop.c), which Slicer pads never read */
#define P_SEL_BEATS  0x15e
int chop_retempo(int q, int old, int new_code);         /* chop.c */
#define MODE_SLICER  2
#define POS_CHOP     3          /* the list position of ChopShop */

void chop_request(int q, int op, int unit, int want);
void chop_forget(int q);

/* the stock names (pointers read from the table at 0x080ec87c), ChopShop after Slicer */
const char *const chop_mode_names[7] = {
    (const char *)0x080ce7ac, (const char *)0x080ce7b4, (const char *)0x080ce7bc, "ChopShop",
    (const char *)0x080ce7c4, (const char *)0x080ce7d0, (const char *)0x080ce7d8,
};
static const char *const type_names[9] = { "--", "Off", "1/4", "1/2", "Beat", "2 Beats", "Bar", "Find", "Random" };
static const char *const tempo_names[3] = { "1/2", "x1", "x2" };
/* the Tempo row's list position <-> the stored code (0 x1 so a fresh pad reads x1, 1 half, 2 double) */
static int tempo_pos(int code) { return code == 1 ? 0 : code == 2 ? 2 : 1; }
static int tempo_code(int pos) { return pos == 0 ? 1 : pos == 2 ? 2 : 0; }

static int is_chop(const void *store)
{
    return store && fw_setting(store, P_MODE) == MODE_SLICER && fw_setting(store, P_CHOP);
}

static int pos_of(const void *store, int mode)       /* stored mode -> list position */
{
    if (mode == MODE_SLICER && is_chop(store))
        return POS_CHOP;
    return mode >= 3 ? mode + 1 : mode;
}

static int pad_q(const void *ref)                    /* the app's cell ref -> pad 0..15, -1 = not a pad */
{
    uint16_t id = *(const uint16_t *)((const uint8_t *)ref + 4);
    int row = (id >> 4) & 0xf, col = id & 0xf;
    return row < 4 && col < 4 ? row * 4 + col : -1;
}

static void run_type(int q, int chop)                /* P_CHOP -> chop.c: 2..6 Beats units, 7 Find, 8 Random */
{
    int type = chop - 1;
    if (q < 0 || type <= 0)
        return;
    if (type <= 5)
        chop_request(q, CHOP_OP_BEATS, type - 1, 0);
    else
        chop_request(q, type == 6 ? CHOP_OP_FIND : CHOP_OP_RANDOM, 0, 64);   /* 64 chops (10-27; 32 since 10-25) */
}

/* The app's set handler for message 0x6e (BL @0x080a1be6): the Mode list positions, and our two rows. */
int chop_set(uint8_t *app, void *ref, int id, int value, int extra)
{
    if (id == P_MODE) {
        uint8_t *cell = fw_cell(app, ref);
        int was = is_chop(cell), want = value == POS_CHOP;
        if (cell)
            fw_set(cell, P_CHOP, want ? (was ? fw_setting(cell, P_CHOP) : 1) : 0);   /* before stock: its re-send and
                                                                                         redraw already see it */
        int v = want ? MODE_SLICER : value > POS_CHOP ? value - 1 : value;
        if (cell && want != was)
            fw_set(cell, P_SEL_BEATS, 0);            /* the Tempo row's code (ChopShop) / the Clip selection's Beats:
                                                        each mode's meaning stays its own */
        int r = fw_set_param(app, ref, id, v, extra);
        if (want && !was) {                          /* entering ChopShop: its defaults, through stock's own path */
            fw_set_param(app, ref, P_LAUNCH, 1, extra);
            fw_set_param(app, ref, P_SLICESYNC, 1, extra);
            fw_set_param(app, ref, P_STRETCH, STRETCH_CYCLIC, extra);
        }
        return r;
    }
    if (id == P_CHOP_TEMPO) {                        /* store the code, then chop again at the corrected tempo */
        uint8_t *cell = fw_cell(app, ref);
        int r = fw_set_param(app, ref, id, value, extra);
        if (is_chop(cell)) {
            int old = fw_setting(cell, P_SEL_BEATS), now = tempo_code(value), chop = fw_setting(cell, P_CHOP);
            fw_set(cell, P_SEL_BEATS, now);
            if (now != old && chop >= 2 && !chop_retempo(pad_q(ref), old, now))
                run_type(pad_q(ref), chop);          /* no detection to reuse: detect, which reads the new code */
        }
        return r;
    }
    if (id == P_CHOP && value < 1)
        value = 1;                                   /* the Chop row never leaves ChopShop: the Mode list does that */
    int r = fw_set_param(app, ref, id, value, extra);
    if (id == P_CHOP || id == P_CHOP_ROLL) {
        uint8_t *cell = fw_cell(app, ref);
        if (is_chop(cell))
            run_type(pad_q(ref), fw_setting(cell, P_CHOP));
    }
    return r;
}

/* the Mode popups' highlight: Waveform screen (BL @0x080a5a5a) and the pad view (BL @0x080b8aa2) */
int chop_show_wave(uint8_t *popup, int mode, int a, int b)
{
    return fw_popup_value(popup, pos_of(popup - 0x23fc + 0x2370, mode), a, b);
}

int chop_show_pad(uint8_t *popup, int mode, int a, int b)
{
    return fw_popup_value(popup, pos_of(popup - 0xe3bc + 0x7d8, mode), a, b);
}

/* A row list (FUN_080a5038): u32 count, then 12-byte entries. Move the last k entries to the front, in order. */
static void rows_to_front(uint32_t *list, unsigned k)
{
    unsigned n = list[0];
    if (k == 0 || k >= n)
        return;
    uint32_t *e = list + 1;
    for (unsigned t = 0; t < k; t++) {               /* k rotations by one entry: k is 2, n <= 47 */
        uint32_t a = e[(n - 1) * 3], b = e[(n - 1) * 3 + 1], c = e[(n - 1) * 3 + 2];
        for (unsigned i = n - 1; i > 0; i--) {
            e[i * 3] = e[(i - 1) * 3];
            e[i * 3 + 1] = e[(i - 1) * 3 + 1];
            e[i * 3 + 2] = e[(i - 1) * 3 + 2];
        }
        e[0] = a; e[1] = b; e[2] = c;
    }
}

/* the pad view's page builder (BL @0x080b8956): ChopShop's POS page gets Chop and Roll, at the TOP */
int chop_pages(uint8_t *app, void *ref, void *list, int page)
{
    int r = fw_pages(app, ref, list, page);
    uint8_t *cell = fw_cell(app, ref);
    if (r && page == 1 && is_chop(cell)) {
        unsigned before = *(uint32_t *)list;
        fw_row_add(list, P_CHOP, fw_setting(cell, P_CHOP));
        fw_row_add(list, P_CHOP_ROLL, 50);           /* mid-range: a 0..99 knob stops re-rolling at its ends, and
                                                        every chop's rebuild (0x66) puts it back here */
        fw_row_add(list, P_CHOP_TEMPO, tempo_pos(fw_setting(cell, P_SEL_BEATS)));
        rows_to_front(list, *(uint32_t *)list - before);   /* the list is full at 47: then fewer (or none) were added */
    }
    return r;
}

/* The pad view's per-frame tick (its vtable slot 0, 0x080f1284; Waveform's twin is sel_view_tick): on the POS page,
   the Roll row shows chop_roll_text. The text setter only marks the row dirty when the text changes, so this costs a
   row lookup a frame (research 10-26: rows at view + 0xd50, knob widget at row + 0x38, value text at + 0x9c). */
#define fw_row_find  ((int (*)(uint8_t *, unsigned, uint8_t **))FN(0x080b9d8a))
#define fw_view_tick ((void (*)(uint8_t *, void *))FN(0x080b9590))
#define fw_text_set  ((void (*)(void *, const char *))FN(0x080c3b98))
#define VIEW_ROWS    0xd50
#define VIEW_PAGE    0xf6cc
#define VIEW_REF     0xd810
#define ROW_KNOB     0x38
#define KNOB_TEXT    0x9c

void chop_view_tick(uint8_t *view, void *flags)
{
    uint8_t *row;
    if (*(int32_t *)(view + VIEW_PAGE) == 1 && fw_row_find(view + VIEW_ROWS, P_CHOP_ROLL, &row) && row) {
        char buf[16];
        fw_text_set(row + ROW_KNOB + KNOB_TEXT, chop_roll_text(pad_q(view + VIEW_REF), buf));
    }
    fw_view_tick(view, flags);
}

/* a fresh WAV header sets the pad's mode from the file (BL @0x0809dd28): a ChopShop pad stays ChopShop */
void chop_header_mode(void *cell, int id, int mode)
{
    if (fw_setting(cell, P_CHOP)) {
        if (fw_setting(cell, P_MODE) == MODE_SLICER)
            mode = MODE_SLICER;
        else
            fw_set(cell, P_CHOP, 0);                 /* a stale flag (the pad was changed without the reset): drop it */
    }
    fw_set(cell, id, mode);
}

/* ... and its closing 0x66 post (BL @0x0809def2): a ChopShop pad with a Chop type chops the new sample */
void chop_header_post(uint8_t *queue, void *msg)
{
    fw_app_post(queue, msg);
    uint16_t id = *(const uint16_t *)((const uint8_t *)msg + 8);
    struct { uint32_t tag; uint16_t pad, r; } ref = { 0x080eaf38u, id, 0 };
    uint8_t *cell = fw_cell((uint8_t *)0x24020088u, &ref);
    if (is_chop(cell) && pad_q(&ref) >= 0) {
        chop_forget(pad_q(&ref));
        run_type(pad_q(&ref), fw_setting(cell, P_CHOP));
    }
}

/* clipsel.c sel_reset_cell, after every stock mode reset: the flag only lives on a Slicer */
void chop_invariant(void *store)
{
    if (store && fw_setting(store, P_MODE) != MODE_SLICER)
        fw_set(store, P_CHOP, 0);
}

void chop_register(void *table)
{
    fw_register_list(table, P_CHOP, "Chop:", type_names, 9, "chopshop");
    fw_register_num(table, P_CHOP_ROLL, 1, "Roll:", 0, 99, "choproll");
    fw_register_list(table, P_CHOP_TEMPO, "Tempo:", tempo_names, 3, "choptempo");
}

void chop_defaults(void *store)
{
    fw_store_add(store, P_CHOP, 0);
}
