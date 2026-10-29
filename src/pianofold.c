/*
 * Piano roll Fold: Fold to notes, Scale fold, a pitch knob without the end-stop jump, pitches 1..127.
 * Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock built most of a "fold" view (roll + 0xb2b4 on, + 0xb2b8 the shown pitches, + 0xb43c their count, + 0xb440 the
 * list index of the bottom row, + 0xb444 / + 0xb448 rows / base to restore) and wired it to a double-tap on the key
 * strip, but FUN_080bba40 has only the OFF half: nothing ever turns it on (research/pianoroll/FOLD_RE.md). Now:
 * - Fold to notes: only the pitches the sequence uses get rows. Scale fold: only the pitches of the project's scale
 *   (song cell 0x89 keymode, 0x8a keyroot: index 0 = A) plus any note already off the scale, so nothing hides.
 *   Chromatic = every pitch. A Pads roll folds to notes only.
 * - Toggles: the key strip double-tap (stock's gesture) cycles Off -> Notes -> Scale -> Off (Notes is skipped when
 *   the layer is empty); EDIT has "Fold Notes" / "Fold Scale", and picking the active one turns the fold off.
 * - What stock left fold-blind: the drag scroll (vtable slot 0), follow-the-note (4 BLs to FUN_080bbb50), the
 *   refresh zeroing the fold scroll (str @0x080bbd0a, now a NOP) and leaving the list empty until some later layout
 *   (the refresh is followed by one), the auto-fit / pinch setting more rows than the list holds (the layout now runs
 *   the list step on every layout while folded, and stock's own "rows = count" clamp follows it).
 * - BR pitch knob: one detent = the next / previous shown row in Scale fold, a semitone otherwise. The knob is put
 *   back on the middle of its detent after every change and after a push against an end, so there is no dead detent
 *   and no 2-semitone skip coming back from C1 / G9; a note never jumps on a turn that does not move it.
 * - Pitch range 1..127 (stock 24..96): five stock constants (patches/master.py). Not 0: a Keys event with pitch 0 is
 *   not a note to the roll (FUN_080bfeec skips it). The view is kept inside 1..127 every frame (pinch / auto-fit).
 * State: the fold is view state, unstored, as stock meant it. Our only extra byte is roll + 0xb2b5 (padding after
 * the stock flag, never accessed in the image): 1 = the fold is the Scale fold; read only while + 0xb2b4 is on, and
 * written every time we turn it on, so garbage there is harmless.
 * Cost: nothing on the audio side. GUI: a list rebuild (128-pitch bitmap + stock's 512 note slots) only when stock
 * asks for one (+ 0xb44c: note adds, refresh) or the moved note's pitch has no row; a few compares per frame.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

struct knob { int64_t acc; int32_t units, value, count; uint8_t wrap; };

typedef void (*roll_fn)(uint8_t *roll);
typedef void (*roll_int_fn)(uint8_t *roll, int a);
typedef void (*tick_fn)(uint8_t *roll, uint8_t *dirty);
typedef void (*follow_fn)(uint8_t *roll, int step, int pitch);
typedef void (*view_fn)(uint8_t *view);
typedef void (*knob_fn)(struct knob *k, int v);
typedef int (*param_get_fn)(uint8_t *app, const void *ref, unsigned param, uint32_t *out);
typedef void (*menu_add_fn)(uint8_t *menu, const char *label, int id, int style);
typedef void (*set_fn)(uint8_t *w, int on);
typedef int (*msg_fn)(uint8_t *view, const uint16_t *msg);
typedef void (*memset_fn)(void *dst, int c, uint32_t n);

#define fw_layout     ((roll_fn)FN(0x080bb190))
#define fw_fold_off   ((roll_int_fn)FN(0x080bba40))
#define fw_tick       ((tick_fn)FN(0x080bd048))
#define fw_follow     ((follow_fn)FN(0x080bbb50))
#define fw_refresh    ((view_fn)FN(0x080bfeec))
#define fw_pitch      ((roll_int_fn)FN(0x080bbbc4))
#define fw_knob_turn  ((knob_fn)FN(0x080b0b74))
#define fw_knob_set   ((knob_fn)FN(0x080b074c))
#define fw_param_get  ((param_get_fn)FN(0x08099504))
#define fw_menu_add   ((menu_add_fn)FN(0x080bd5b8))
#define fw_menu_hide  ((set_fn)FN(0x080bd24c))
#define fw_button     ((set_fn)FN(0x080a3e00))
#define fw_view_msg   ((msg_fn)FN(0x080c0a40))
#define fw_memset     ((memset_fn)FN(0x080c8d5e))

#define APP        ((uint8_t *)0x24020088u)
#define SONG_TAG   0x080eaf38u                  /* the song cell: {tag, id 0x233}, as the Keys grid reads it */
#define SONG_ID    0x233
#define P_KEYMODE  0x89
#define P_KEYROOT  0x8a

#define I32(o)     (*(int32_t *)(roll + (o)))
#define ROWS       I32(0xa040)
#define NOTES      I32(0xa894)                  /* the sorted note count (select / pitch knobs) */
#define LAST_PITCH I32(0xa934)
#define BASE       I32(0xa93c)
#define MIN_BASE   I32(0xae78)
#define MAX_ROWS   I32(0xae7c)
#define COUNT      I32(0xb43c)
#define SCROLL     I32(0xb440)
#define SAVED_ROWS I32(0xb444)
#define SAVED_BASE I32(0xb448)
#define LIST       ((int32_t *)(roll + 0xb2b8))
#define KNOB       ((struct knob *)(roll + 0xa900))
#define DIRTY      0xa938                       /* + 0xa939 */
#define TOUCH      0xae24                       /* 2..4 = drag / fling / two fingers */
#define PADS       0xae74
#define FOLD       0xb2b4
#define FOLD_SCALE 0xb2b5                       /* ours */
#define REBUILD    0xb44c
#define LIST_MAX   97                           /* stock's int[97] */
#define TOP        128                          /* pitches below this */

#define VIEW_ROLL  0x38
#define VIEW_MENU  0xbc10
#define VIEW_EDIT  0xb8bc
#define MENU_PER_COL 0x1308
#define ID_NOTES   0x7e0
#define ID_SCALE   0x7e1

/* Pitch classes of each keymode above its root, bit n = n semitones: stock's table (FUN_0806e9dc builds it in RAM at
   boot from code immediates; test_pianofold.py runs that and compares). */
static const uint16_t scale_mask[23] = {
    0xfff, 0xab5, 0x295, 0x5ad, 0x4a9, 0x4e9, 0x9b3, 0x9cb, 0x9cd, 0x575, 0x4a5, 0x1a3,
    0x8b1, 0x555, 0xb6d, 0x9ad, 0xaad, 0x6ad, 0x5ab, 0xad5, 0x6b5, 0x5ad, 0x56b,
};

static unsigned song(unsigned param)
{
    struct { uint32_t tag; uint16_t id, r; } ref = { SONG_TAG, SONG_ID, 0 };
    uint32_t v = 0;
    fw_param_get(APP, &ref, param, &v);
    return v;
}

/* The list step of the layout (bl @0x080bb286; the layout now comes here on every layout while folded). */
void pf_build(uint8_t *roll)
{
    if (roll[REBUILD]) {
        roll[REBUILD] = 0;
        uint8_t bm[TOP];                        /* 1 = a note, 2 = the scale */
        fw_memset(bm, 0, sizeof bm);
        int lo = TOP, hi = -1, n = 0;
        for (const uint8_t *s = roll; s < roll + 0xa000; s += 0x50) {
            unsigned p = *(const uint32_t *)(s + 0x78);
            if (s[0x65] && p < TOP) {
                n += !bm[p];
                bm[p] = 1;
                if ((int)p < lo)
                    lo = p;
                if ((int)p > hi)
                    hi = p;
            }
        }
        if (roll[FOLD_SCALE]) {
            unsigned mode = song(P_KEYMODE), root = (song(P_KEYROOT) + 9) % 12;
            unsigned mask = scale_mask[mode < 23 ? mode : 0];
            for (int p = MIN_BASE; p < TOP; p++)
                if (mask >> ((p + 12 - root) % 12) & 1 && !bm[p]) {
                    bm[p] = 2;
                    n++;
                }
            /* more rows than the list holds: drop scale-only pitches farthest from the notes first */
            int c = hi < 0 ? 60 : (lo + hi) >> 1, l = 0, h = TOP - 1;
            while (n > LIST_MAX && l <= h) {
                int at = c - l >= h - c ? l++ : h--;
                if (bm[at] == 2) {
                    bm[at] = 0;
                    n--;
                }
            }
        }
        n = 0;
        for (int p = 0; p < TOP && n < LIST_MAX; p++)
            if (bm[p])
                LIST[n++] = p;
        COUNT = n;
        if (!roll[FOLD_SCALE] && n)
            ROWS = n < MAX_ROWS ? n : MAX_ROWS; /* Fold to notes shows every note's row */
    }
    int over = COUNT - ROWS;                    /* stock's clamp of the fold scroll */
    if (SCROLL > over)
        SCROLL = over;
    if (SCROLL < 0)
        SCROLL = 0;
}

static int index_of(uint8_t *roll, int pitch)
{
    int i = 0;
    while (i < COUNT - 1 && LIST[i] < pitch)
        i++;
    return i;
}

/* mode 0 off, 1 notes, 2 scale */
static void pf_set(uint8_t *roll, int mode)
{
    if (mode == 2 && roll[PADS])
        mode = 0;
    if (!mode) {
        fw_fold_off(roll, 0);                   /* stock's OFF: rows / base back, layout, redraw */
        return;
    }
    if (!roll[FOLD]) {
        SAVED_ROWS = ROWS;
        SAVED_BASE = BASE;
    }
    roll[FOLD] = 1;
    roll[FOLD_SCALE] = mode == 2;
    roll[REBUILD] = 1;
    fw_layout(roll);                            /* builds; an empty Fold to notes turns itself off there */
    if (!roll[FOLD])
        return;
    if (mode == 2)
        ROWS = SAVED_ROWS < COUNT ? SAVED_ROWS : COUNT;
    SCROLL = index_of(roll, SAVED_BASE);        /* open where the unfolded view was */
    fw_layout(roll);
    roll[DIRTY] = roll[DIRTY + 1] = 1;
}

/* The key strip double-tap (bl @0x080bc718, stock: FUN_080bba40(roll, !fold)). */
void pf_tap(uint8_t *roll)
{
    int mode = !roll[FOLD] ? 1 : roll[FOLD_SCALE] ? 0 : 2;
    pf_set(roll, mode);
    if (mode == 1 && !roll[FOLD])
        pf_set(roll, 2);
}

/* The roll's per-frame tick (vtable 0x080f13dc slot 0). Folded, a drag scrolls the fold list: stock's own tick runs
   with the fold index in the base's place and no lower limit, and its result goes to the fold scroll. Unfolded, the
   view is kept inside the pitch range (a pinch or the auto-fit can push it out). */
void pf_tick(uint8_t *roll, uint8_t *dirty)
{
    int base = BASE, moved;
    if (roll[FOLD] && (uint8_t)(roll[TOUCH] - 2) < 3) {
        int min = MIN_BASE;
        BASE = SCROLL;
        MIN_BASE = 0;
        fw_tick(roll, dirty);
        int at = BASE, over = COUNT - ROWS;
        BASE = base;
        MIN_BASE = min;
        if (at > over)
            at = over;
        if (at < 0)
            at = 0;
        moved = at != SCROLL;
        SCROLL = at;
    } else {
        fw_tick(roll, dirty);
        if (roll[FOLD] || roll[PADS])
            return;
        int top = TOP - ROWS;
        base = BASE;
        if (base > top)
            base = top;
        if (base < MIN_BASE)
            base = MIN_BASE;
        moved = base != BASE;
        BASE = base;
    }
    if (moved)
        fw_layout(roll);                        /* redraws next frame (+ 0xa938) */
}

/* Follow-the-note (FUN_080bbb50, from the BR / TL knobs and the reselect). Folded: the note's row into view by the
   fold scroll (a pitch without a row yet, e.g. just moved, rebuilds the list first); stock still does the step axis. */
void pf_follow(uint8_t *roll, int step, int pitch)
{
    if (roll[FOLD] && !roll[TOUCH]) {
        int i = index_of(roll, pitch);
        if (LIST[i] != pitch) {
            roll[REBUILD] = 1;
            pf_build(roll);
            i = index_of(roll, pitch);
        }
        if (i < SCROLL)
            SCROLL = i;
        else if (i >= SCROLL + ROWS)
            SCROLL = i - ROWS + 1;
        pitch = BASE;
    }
    fw_follow(roll, step, pitch);
}

/* The view's refresh (bl @0x080c145c in the 0x66 handler): stock empties the fold list and re-adds the notes; the
   list is rebuilt right away, before anything can read or tap an empty list. */
void pf_refresh(uint8_t *view)
{
    fw_refresh(view);
    if (view[VIEW_ROLL + FOLD])
        fw_layout(view + VIEW_ROLL);
}

/* BR in the note editor (bl @0x080c17ba). */
void pf_pitch(uint8_t *roll, int counts)
{
    struct knob *k = KNOB;
    if (NOTES <= 0) {
        fw_pitch(roll, counts);
        return;
    }
    int64_t want = k->acc + counts;
    int v = k->value;
    fw_knob_turn(k, counts);
    int d = k->value - v, p = LAST_PITCH, t = p + d;
    if (!d && k->acc == want)
        return;                                 /* inside a detent */
    if (d && roll[FOLD] && roll[FOLD_SCALE]) {
        int i = index_of(roll, p);
        i += d - (d > 0 && LIST[i] > p);
        if (i < 0)
            i = 0;
        if (i >= COUNT)
            i = COUNT - 1;
        t = LIST[i];
    }
    int lo = MIN_BASE, hi = lo + k->count - 1;
    if (t < lo || t > hi)
        t = p;                                  /* an end: stay (an out-of-range note never snaps) */
    fw_knob_set(k, t - lo);                     /* the middle of the detent */
    if (t != p)
        fw_pitch(roll, 0);                      /* stock applies lo + value: messages, follow */
}

/* EDIT menu: stock's last entry (Clear Sel, bl @0x080c08b8), then ours. 9 entries at stock's 4 per column make 3
   columns, the first off the left edge (x -40); 5 per column keeps 2 columns where stock has them. */
static const char fold_notes[] = "Fold Notes";
static const char fold_scale[] = "Fold Scale";

void pf_menu_add(uint8_t *menu, const char *label, int id, int style)
{
    *(int32_t *)(menu + MENU_PER_COL) = 5;
    fw_menu_add(menu, label, id, style);
    fw_menu_add(menu, fold_notes, ID_NOTES, style);
    fw_menu_add(menu, fold_scale, ID_SCALE, style);
}

/* The view's notify handler (vtable 0x080f1658 + 0x30, FUN_080c0a40): our two entries. */
int pf_view_msg(uint8_t *view, const uint16_t *msg)
{
    unsigned id = msg[6];                       /* a button's id, in types 1 (press) and 2 (click) */
    if ((unsigned)(msg[0] - 1) > 1 || (id != ID_NOTES && id != ID_SCALE))
        return fw_view_msg(view, msg);
    if (msg[0] == 2) {
        uint8_t *roll = view + VIEW_ROLL;
        int want = id == ID_NOTES ? 1 : 2, now = !roll[FOLD] ? 0 : roll[FOLD_SCALE] ? 2 : 1;
        pf_set(roll, now == want ? 0 : want);
        fw_menu_hide(view + VIEW_MENU, 1);      /* as Clear Sel: close the menu, EDIT up */
        fw_button(view + VIEW_EDIT, 0);
    }
    return 0;
}
