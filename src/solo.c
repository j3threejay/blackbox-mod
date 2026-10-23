/*
 * Mixer Solo for the original 1010music Blackbox, firmware 3.1.9.
 *
 * MIX cycles Mixer (screen 0x2e) -> Mute (0x2f) -> Solo (0x2f + solo flag) -> Mixer.
 * In Solo mode a tap toggles a pad in the solo set; while the set is non-empty every other
 * pad is muted through the firmware's own mute path (GUI msg 0x44 -> engine param 100).
 * Emptying the set restores the mutes captured when the first pad was soloed.
 * While a solo set exists the Mute screen always comes up as Solo (MIX cycles Mixer -> Solo -> Mixer), whichever way
 * it is reached, so the mutes cannot be edited by hand under a solo. (Through 3.1.n the plain Mute screen was still
 * reachable with a set alive; it looks the same minus the yellow outlines, and a tap there muted the soloed pad and
 * dropped the set: everything muted, nothing to restore. Reported on 3.1.d, 3.1.l, 3.1.n.)
 * A set left over from before a preset load or restart is forgotten when the mixer is next shown (drop_stale).
 * Clearing the set sends every pad its restored state whatever the cell reads, so a stale cell cannot leave a pad muted.
 *
 * Linked into the free space after the stock image; every firmware call goes through an
 * absolute function pointer, so the object has no relocations against the stock code.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*fill_fn)(void *rect, int color, void *fb);
typedef void (*post_fn)(void *view, void *msg);
typedef void (*cell_set_fn)(void *cell, int unmuted);
typedef int (*hit_fn)(void *view, void *pt, uint8_t **cell);
typedef void (*touch_fn)(void *view, void *pt, void *arg);
typedef void (*set_mode_fn)(void *view, int mute_mode);
typedef void (*set_screen_fn)(void *app, int screen, int a, int b);

#define fw_fill        ((fill_fn)FN(0x0808ea22))
#define fw_outline     ((fill_fn)FN(0x0808e994))
#define fw_post        ((post_fn)FN(0x080aed14))
#define fw_cell_set    ((cell_set_fn)FN(0x080a4f10))
#define fw_hit         ((hit_fn)FN(0x080b5e78))
#define fw_touch_down  ((touch_fn)FN(0x080b5f44))
#define fw_touch_move  ((touch_fn)FN(0x080b5ebc))
#define fw_set_mode    ((set_mode_fn)FN(0x080b5e44))
#define fw_set_screen  ((set_screen_fn)FN(0x0809eaec))

#define SCREEN_MIXER 0x2e
#define SCREEN_MUTE  0x2f
#define APP_SCREEN   0x8ca4      /* app: current screen id */
#define VIEW_MUTE    0x1e40      /* mixer view: mute-mode flag */
#define VIEW_CELLS   0x3ac       /* mixer view: first of 16 cells */
#define CELL_SIZE    0x1a0
#define CELL_PAD     0x38        /* u16 pad id: bits 0-3 col, 4-7 row */
#define CELL_DIRTY   0x17c
#define CELL_UNMUTED 0x189
#define COLOR_SOLO_FILL 0x1c     /* palette: rgb(119,113,0) */
#define COLOR_SOLO_EDGE 0x14     /* palette: rgb(255,255,0) */
#define MSG_PAD_MUTE 0x44
#define MSG_TAG      0x080cfba4u
#define APP          ((uint8_t *)0x24020088u)
#define APP_PADS     0x8a88      /* app: pad records, [row * 0x78 + col * 0x18]; +0xd = muted (what msg 0x44 mirrors) */

/* Patch RAM: the 172-byte alignment gap between the heap end (0x2405ff54) and the MPU regions at 0x24060000.
 * Never take it from the heap: operator new allocates 167,704 bytes of that 200,000-byte heap in one block and
 * hangs on failure (build 3.1.U crash-looped that way). Not zeroed at boot. */
struct solo_state {
    uint32_t magic;
    uint8_t active;              /* mixer view is showing Solo mode */
    uint8_t pending;             /* MIX asked for Solo; consumed by the next mode change */
    uint8_t pad[2];
    uint8_t *view;
    uint16_t mask;               /* soloed cells, bit = cell index */
    uint16_t saved;              /* muted cells captured when the set became non-empty */
};
#define S ((volatile struct solo_state *)0x2405ff60u)
#define MAGIC 0x534f4c4fu        /* "SOLO" */

struct pad_msg {
    uint16_t id, _r0;
    uint32_t tag;
    uint16_t pad, _r1;
    uint32_t unmuted;
    uint32_t a, b;
};

static void ensure(void)
{
    if (S->magic != MAGIC) {
        S->active = 0;
        S->pending = 0;
        S->view = 0;
        S->mask = 0;
        S->saved = 0;
        S->magic = MAGIC;
    }
}

static uint8_t *cell_at(uint8_t *view, int i)
{
    return view + VIEW_CELLS + i * CELL_SIZE;
}

static int pad_ok(uint8_t *cell)
{
    return (*(uint16_t *)(cell + CELL_PAD) & 0xf) <= 3;
}

static int cell_index(uint8_t *view, uint8_t *cell)
{
    if (!view || cell < cell_at(view, 0) || cell > cell_at(view, 15))
        return -1;
    int off = cell - cell_at(view, 0);
    return off % CELL_SIZE ? -1 : off / CELL_SIZE;
}

/*
 * The solo set counts while every soloed pad is still unmuted. (3.1.d and earlier also required every other pad to be
 * muted; a pad that does not hold a mute, such as an empty one, then broke the set, and un-soloing re-captured
 * "everything muted" as the state to return to: nothing played after un-solo.)
 */
static int solo_valid(uint8_t *view)
{
    uint16_t mask = S->mask;
    if (!mask)
        return 0;
    for (int i = 0; i < 16; i++) {
        uint8_t *c = cell_at(view, i);
        if (pad_ok(c) && ((mask >> i) & 1) && !c[CELL_UNMUTED])
            return 0;
    }
    return 1;
}

/*
 * The solo state sits in RAM that survives a preset load and a warm restart, the mutes it describes do not. A set with
 * nothing muted outside it (by the app's own pad records) is left over from before: forget it. Without this a stale
 * pad stays in the set, and un-soloing the pad just soloed leaves everything but the stale one muted.
 */
static void drop_stale(void)
{
    uint16_t mask = S->mask;
    if (!mask || mask == 0xffff)
        return;
    for (int i = 0; i < 16; i++)
        if (!((mask >> i) & 1) && APP[APP_PADS + (i >> 2) * 0x78 + (i & 3) * 0x18 + 0xd])
            return;
    S->mask = 0;
}

static void mark_dirty(uint8_t *view)
{
    for (int i = 0; i < 16; i++)
        cell_at(view, i)[CELL_DIRTY] = 1;
}

static void apply(uint8_t *view)
{
    uint16_t mask = S->mask, saved = S->saved;
    for (int i = 0; i < 16; i++) {
        uint8_t *c = cell_at(view, i);
        if (!pad_ok(c))
            continue;
        int want = mask ? (mask >> i) & 1 : !((saved >> i) & 1);
        if (mask && c[CELL_UNMUTED] == want)
            continue;
        struct pad_msg m = {MSG_PAD_MUTE, 0, MSG_TAG, *(uint16_t *)(c + CELL_PAD), 0, (uint32_t)want, 0, 0};
        fw_post(view, &m);
        fw_cell_set(c, want);
    }
    mark_dirty(view);
}

static void toggle(uint8_t *view, uint8_t *cell)
{
    int i = cell_index(view, cell);
    if (i < 0 || !pad_ok(cell))
        return;
    if (!S->mask) {
        uint16_t saved = 0;
        for (int j = 0; j < 16; j++)
            if (!cell_at(view, j)[CELL_UNMUTED])
                saved |= 1u << j;
        S->saved = saved;
    }
    S->mask ^= 1u << i;
    apply(view);
}

/* Replaces the set-screen call in the MIX button handler. */
void solo_mix_pressed(uint8_t *app, int computed, int a, int b)
{
    (void)computed;
    ensure();
    int cur = app[APP_SCREEN], next = SCREEN_MIXER;
    if (cur == SCREEN_MIXER) {
        next = SCREEN_MUTE;
    } else if (cur == SCREEN_MUTE && !S->active) {
        S->pending = 1;
        next = SCREEN_MUTE;
    }
    fw_set_screen(app, next, a, b);
}

/* Replaces the GUI's call to the mixer view's set-mode on every mixer (re)show. */
void solo_set_mode(uint8_t *view, int mute_mode)
{
    ensure();
    S->view = view;
    drop_stale();
    S->active = mute_mode && (S->pending || S->mask);
    S->pending = 0;
    fw_set_mode(view, mute_mode);
    mark_dirty(view);
}

/* Replaces the green/red fill in the mixer cell's mute-mode draw. rect = cell + 4. */
void solo_mute_fill(uint8_t *rect, int color, void *fb)
{
    ensure();
    uint8_t *view = S->view;
    int i = S->active ? cell_index(view, rect - 4) : -1;
    if (i >= 0 && solo_valid(view) && ((S->mask >> i) & 1))
        color = COLOR_SOLO_FILL;
    fw_fill(rect, color, fb);
    if (i >= 0) {
        int *r = (int *)rect;
        int inner[4] = {r[0] + 1, r[1] + 1, r[2] - 2, r[3] - 2};
        fw_outline(rect, COLOR_SOLO_EDGE, fb);
        fw_outline(inner, COLOR_SOLO_EDGE, fb);
    }
}

void solo_touch_down(uint8_t *view, void *pt, void *arg)
{
    ensure();
    if (S->active && view[VIEW_MUTE]) {
        uint8_t *cell = 0;
        if (fw_hit(view, pt, &cell) && cell)
            toggle(view, cell);
        return;
    }
    fw_touch_down(view, pt, arg);
}

void solo_touch_move(uint8_t *view, void *pt, void *arg)
{
    ensure();
    if (S->active && view[VIEW_MUTE])
        return;
    fw_touch_move(view, pt, arg);
}

/*
 * ---- Mute / Solo on the Pads screen (3.1.t) ----
 *
 * The Pads view (GUI +0x490, FUN_080b4528) has a right-hand column the lower-right knob flips between two panels: the
 * Velocity slider (panel pointer at view +0x2b58) and the clipboard buttons CUT / COPY / PSTE / CLR (+0x2b5c). The
 * stepper is at +0x2b60 (position +0x2b6c, count +0x2b70, last shown +0x2b78). The count is patched to 3; position 2
 * shows the same clipboard panel with its four buttons relabelled MUTE / SOLO / blank / blank and given our ids, so no
 * new widgets are needed. A button press reaches the view's child-message method (vtable +0x30, FUN at 0x080b3e84):
 * type 1 = pressed, type 2 = clicked, id at +0xc; stock forwards a click to the app with the selected pad (+0x20b8).
 *
 * Both act on the selected pad. Solo shares the set with the Mixer's Solo screen (S->mask / S->saved) but works from
 * the app's pad records, since the mixer view's cells are only current while it is shown. MUTE with a solo on ends the
 * solo first. Both buttons light for the selected pad's state.
 */
typedef void (*label_fn)(void *widget, const char *text);
typedef void (*hide_fn)(void *widget, int hidden);
typedef int (*child_msg_fn)(uint8_t *view, const uint16_t *msg);

#define fw_label        ((label_fn)FN(0x080a3dec))
#define fw_pads_child   ((child_msg_fn)FN(0x080b3e84))
typedef void (*view_msg_fn)(uint8_t *view, const uint16_t *msg);
typedef void (*select_fn)(void *button, int on);
#define fw_pads_msg     ((view_msg_fn)FN(0x080b4134))
#define fw_select       ((select_fn)FN(0x080a3e00))    /* a button's highlighted state */

#define PADS_CELLS    0x34       /* 4 rows of 5 cells (0x820 a row), same class as the mixer's */
#define PADS_ROW      0x820
#define PADS_SELECTED 0x20b8     /* u16 pad id */
#define PADS_PANELS   0x2b58     /* [0] velocity slider, [1] clipboard buttons */
#define PADS_POS      0x2b6c
#define PADS_SHOWN    0x2b78
#define BTN_ID        0x14
/* clipboard panel buttons, top to bottom (FUN_080b811c) */
static const uint16_t btn_at[4] = {0x214, 0x174, 0xd4, 0x34};
#define ID_MUTE  0x1f1
#define ID_SOLO  0x1f2
#define ID_RPT   0x1f3           /* note repeat (repeat.c): hold it, hold pads */
#define ID_DIV   0x1f4           /* note repeat's division: a tap steps it */
void repeat_hold(int on);
void repeat_next_div(void);
const char *repeat_div_name(void);
int repeat_held(void);

static int rec_muted(int i)
{
    return APP[APP_PADS + (i >> 2) * 0x78 + (i & 3) * 0x18 + 0xd] != 0;
}

/* one pad's mute through the firmware's own path, and the two screens' cells kept in step */
static void pad_set(uint8_t *pads, int i, int unmuted)
{
    struct pad_msg m = {MSG_PAD_MUTE, 0, MSG_TAG, (uint16_t)((i >> 2) << 4 | (i & 3)), 0, (uint32_t)unmuted, 0, 0};
    fw_post(pads, &m);
    fw_cell_set(pads + PADS_CELLS + (i >> 2) * PADS_ROW + (i & 3) * CELL_SIZE, unmuted);
    uint8_t *mixer = S->view;
    if (mixer)
        fw_cell_set(cell_at(mixer, i), unmuted);
}

static uint8_t *pads_cell(uint8_t *pads, int i)
{
    return pads + PADS_CELLS + (i >> 2) * PADS_ROW + (i & 3) * CELL_SIZE;
}

/* The Pads cells' mute flags are only written by us; bring them in line with the app's records (mutes may have been
   changed on the Mixer since). */
static void pads_sync(uint8_t *pads)
{
    for (int i = 0; i < 16; i++)
        fw_cell_set(pads_cell(pads, i), !rec_muted(i));
}

/* MUTE / SOLO buttons light up for the selected pad's state (3.1.v), so a press is visible on the glass. */
static void pads_lights(uint8_t *pads)
{
    uint8_t *buttons = *(uint8_t **)(pads + PADS_PANELS + 4);
    unsigned pad = *(uint16_t *)(pads + PADS_SELECTED), row = (pad >> 4) & 0xf, col = pad & 0xf;
    int ok = *(int32_t *)(pads + PADS_POS) == 2 && pad <= 0xff && row <= 3 && col <= 3, i = row * 4 + col;
    fw_select(buttons + btn_at[0], ok && !pads_cell(pads, i)[CELL_UNMUTED]);
    fw_select(buttons + btn_at[1], ok && ((S->mask >> i) & 1));
    fw_select(buttons + btn_at[2], *(int32_t *)(pads + PADS_POS) == 2 && repeat_held());
}

static void pads_restore(uint8_t *pads)
{
    uint16_t saved = S->saved;
    S->mask = 0;
    for (int j = 0; j < 16; j++)
        pad_set(pads, j, !((saved >> j) & 1));
}

static void pads_solo(uint8_t *pads, int i)
{
    drop_stale();
    if (!S->mask) {
        uint16_t saved = 0;
        for (int j = 0; j < 16; j++)
            if (rec_muted(j))
                saved |= 1u << j;
        S->saved = saved;
    }
    S->mask ^= 1u << i;
    uint16_t mask = S->mask;
    if (!mask) {
        pads_restore(pads);
        return;
    }
    for (int j = 0; j < 16; j++) {
        int want = (mask >> j) & 1;
        if ((!rec_muted(j)) != want)
            pad_set(pads, j, want);
    }
}

/* MUTE always acts (3.1.u ignored it while a solo was on: as reported, "mute does not work at all"): a solo that is on
   ends first, the pads going back to their mutes from before it, then the selected pad toggles. */
static void pads_mute(uint8_t *pads, int i)
{
    drop_stale();
    int muted = !pads_cell(pads, i)[CELL_UNMUTED];
    if (S->mask) {
        muted = (S->saved >> i) & 1;
        pads_restore(pads);
    }
    pad_set(pads, i, muted);
}

/* Replaces the Pads view's child-message method (vtable 0x080f0e50 +0x30). Returns 0 = handled here. */
int pads_child_msg(uint8_t *view, const uint16_t *msg)
{
    unsigned id = msg[6];
    if ((msg[0] != 1 && msg[0] != 2) || id < ID_MUTE || id > ID_DIV)
        return fw_pads_child(view, msg);
    if (id == ID_RPT) {                  /* held: pressed = 1, released = 2 */
        repeat_hold(msg[0] == 1);
        pads_lights(view);
        return 0;
    }
    if (id == ID_DIV) {
        if (msg[0] == 2) {
            repeat_next_div();
            fw_label(*(uint8_t **)(view + PADS_PANELS + 4) + btn_at[3], repeat_div_name());
        }
        return 0;
    }
    unsigned pad = *(uint16_t *)(view + PADS_SELECTED), row = (pad >> 4) & 0xf, col = pad & 0xf;
    if (msg[0] != 2 || pad > 0xff || row > 3 || col > 3)
        return 0;
    ensure();
    int i = row * 4 + col;
    if (id == ID_SOLO)
        pads_solo(view, i);
    else
        pads_mute(view, i);
    pads_lights(view);
    return 0;
}

/* Wraps the Pads view's message handler (vtable +0x34, 0x080b4134): keep the lights and the cells' mute flags right
   when another pad is selected (0x63) or the screen comes back (0x67). */
void pads_msg(uint8_t *view, const uint16_t *msg)
{
    fw_pads_msg(view, msg);
    if (!msg || (msg[0] != 0x63 && msg[0] != 0x67) || *(int32_t *)(view + PADS_POS) != 2)
        return;
    ensure();
    if (msg[0] == 0x67) {
        repeat_hold(0);                  /* the screen came back: a release that was missed does not stick */
        pads_sync(view);
    }
    pads_lights(view);
}

/*
 * Replaces the show / hide loop after the lower-right knob moved the column (@0x080b43a4, via pads_panels_thunk):
 * position 0 = Velocity slider, 1 = clipboard buttons, 2 = the same buttons as MUTE / SOLO.
 */
void pads_panels(uint8_t *view)
{
    static const char *const clip[4] = {(const char *)0x080cf730, (const char *)0x080cf728, (const char *)0x080cf720,
                                        (const char *)0x080cf71c};      /* CLR, PSTE, COPY, CUT: top to bottom */
    static const uint16_t clip_id[4] = {0x25, 0x2a, 0x29, 0x28};
    const char *const mute[4] = {"MUTE", "SOLO", "RPT", repeat_div_name()};
    static const uint16_t mute_id[4] = {ID_MUTE, ID_SOLO, ID_RPT, ID_DIV};
    int pos = *(int32_t *)(view + PADS_POS);
    uint8_t *slider = *(uint8_t **)(view + PADS_PANELS), *buttons = *(uint8_t **)(view + PADS_PANELS + 4);
    if (pos > 0)
        for (int k = 0; k < 4; k++) {
            uint8_t *b = buttons + btn_at[k];
            fw_label(b, pos == 2 ? mute[k] : clip[k]);
            *(uint32_t *)(b + BTN_ID) = pos == 2 ? mute_id[k] : clip_id[k];
        }
    ensure();
    if (pos != 2)
        repeat_hold(0);                  /* RPT is off the screen: nothing stays held */
    if (pos == 2)
        pads_sync(view);
    pads_lights(view);
    (*(hide_fn *)(*(uint8_t **)slider + 0x2c))(slider, pos != 0);
    (*(hide_fn *)(*(uint8_t **)buttons + 0x2c))(buttons, pos == 0);
    *(int32_t *)(view + PADS_SHOWN) = pos;
}
