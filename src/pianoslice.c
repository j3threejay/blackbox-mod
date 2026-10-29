/*
 * Slice numbers on the piano roll's keys. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: a Keys sequence plays its Play Pad (param 0xb9); on a Slicer pad key C2 (note 36) plays slice 1, one slice
 * per semitone (the engine: note - 36, FUN_08065908). The roll's key strip only names the C keys, so a note laid down
 * on a Slicer pad cannot be read across to its chop. Now, when the Play Pad is a Slicer (ChopShop included: it is a
 * Slicer underneath), every key that has a slice carries the slice's number where the key's label goes, and reads as
 * a white key (asked 10-28: all numbers look the same; a black key with a slice is repainted white inside the
 * row lines, so the separators between keys stay). Keys without a slice stay stock, which shows where the chops end. On a C key stock's octave label stays when the number fits beside it (C2 + "1"); otherwise the
 * number takes the label's place. Nothing below C2 or above the last slice; Pads / MIDI sequences and other pad
 * types are untouched. A key with a slice reads white at every zoom (3.5.l); the numbers come once the
 * rows average 9 px (the 8 px font fits), on every such key at that zoom (3.5.k skipped single 9 px rows: holes).
 *
 * How: the roll widget (view + 0x38, vtable 0x080f13dc, draw FUN_080bc974) ends its draw with the children draw
 * FUN_080aeaf8 (bl @0x080bd024), on both the full and the partial path. The hook runs there: on a full draw (dc[0])
 * it goes over the rows the way the key strip did (y bounds roll + 0xa944, row count + 0xa040, note FUN_080babf6,
 * which also covers Fold), then hands on to the children draw as stock did, so the notes still draw over everything.
 * The pad is the one the view itself shows in its pad picker: view + 0xb49c, set from Play Pad on every refresh
 * (msg 0x66, FUN_080c130c), with view + 0xf5e1 = MIDI (the pad is then 0) and roll + 0xae74 = Pads.
 * Text: stock's 6 x 8 font through FUN_0808f23c in colour 2 on key colour 15, as stock's white-key labels (palette
 * indices, so the themes apply); an erased label is refilled in 15.
 * Cost: none on the audio side. GUI: per full roll draw one cell lookup + per row a note lookup, and for keys with a
 * slice one snprintf + one text draw (only the rows the roll lays out).
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*children_fn)(uint8_t *widget, const uint8_t *dc);
typedef int (*row_note_fn)(uint8_t *roll, int row);
typedef uint8_t *(*cell_fn)(uint8_t *app, const void *ref);
typedef int (*setting_fn)(const void *store, int param);
typedef int (*fmt_fn)(char *buf, unsigned size, const char *fmt, ...);
typedef void (*fill_fn)(const int32_t *rect, int colour, uint32_t ctx);
typedef void (*text_fn)(const char *text, const int32_t *rect, int colour, uint32_t ctx);

#define fw_children ((children_fn)FN(0x080aeaf8))
#define fw_row_note ((row_note_fn)FN(0x080babf6))
#define fw_cell     ((cell_fn)FN(0x08098d0c))
#define fw_setting  ((setting_fn)FN(0x08093e9c))
#define fw_fmt      ((fmt_fn)FN(0x080c89f4))
#define fw_fill     ((fill_fn)FN(0x0808ea22))
#define fw_text     ((text_fn)FN(0x0808f23c))

#define APP         ((uint8_t *)0x24020088u)
#define CELL_REF    0x080eaf38u                 /* the pad ref tag (FUN_080a1718); the lookup reads only the id */
#define FMT_D       ((const char *)0x080cf828u) /* stock's "%d" (read only: stock strings are pooled) */
#define BLACK       ((const uint8_t *)0x080f1444u)   /* stock's 12 entries: 1 = black key */

#define ROLL_IN_VIEW 0x38
#define V_PAD        0xb49c                     /* u16 pad id (row << 4 | col) */
#define V_MIDI       0xf5e1
#define R_X          4
#define R_ROWS       0xa040
#define R_ROW_Y      0xa944
#define R_PADS       0xae74
#define R_FOLD       0xb2b4
#define KEY_X        10                         /* the keys: x + 10, 24 wide; stock's labels at + 3 */
#define KEY_W        24
#define CELL_SLICES  0x2c                       /* the cell's slice list count (buf at + 0x28) */
#define P_MODE       0x8b
#define MODE_SLICER  2
#define SLICE1_NOTE  36                         /* C2 */

static void slice_keys(uint8_t *roll, uint32_t ctx)
{
    const uint8_t *view = roll - ROLL_IN_VIEW;
    if (roll[R_PADS] || view[V_MIDI])
        return;
    unsigned id = *(const uint16_t *)(view + V_PAD);
    if ((id & 0xffu) >> 4 > 3 || (id & 0xfu) > 3)
        return;
    struct { uint32_t tag; uint16_t id, r; } ref = { CELL_REF, (uint16_t)id, 0 };
    const uint8_t *cell = fw_cell(APP, &ref);
    if (!cell || fw_setting(cell, P_MODE) != MODE_SLICER)
        return;
    int count = *(const int32_t *)(cell + CELL_SLICES);
    int rows = *(const int32_t *)(roll + R_ROWS);
    const int32_t *ry = (const int32_t *)(roll + R_ROW_Y);
    int x = *(const int32_t *)(roll + R_X) + KEY_X + 3;
    /* One decision per zoom, not per row: the rows' heights alternate by a pixel (the layout rounds), and a per-row
       "too thin" test left every other key bare at some zooms (glass 10-28, 3.5.k). Rounding keeps every row within
       a pixel of the average, so an average of 9 px means no row under 9: the 8 px number fits each one. */
    int numbers = rows > 0 && ry[rows] - ry[0] >= 9 * rows;
    for (int i = 0; i < rows; i++) {
        int note = fw_row_note(roll, i);
        int k = note - SLICE1_NOTE, h = ry[i + 1] - ry[i];
        if (k < 0 || k >= count)
            continue;
        int pc = note % 12;
        int labelled = (roll[R_FOLD] || pc == 0) && h > 9;   /* stock labelled this key: "C2", or any key under Fold */
        int digits = k < 9 ? 1 : k < 99 ? 2 : 3;
        int dy = (h - 8) >> 1;
        int32_t r[4] = { x, ry[i] + (dy < 1 ? 1 : dy), 0x28, 0x14 };   /* a 9 px row: just above its lower line */
        if (BLACK[pc]) {
            if (h >= 2) {                       /* white at any zoom (asked 10-28): between the two row lines */
                int32_t key[4] = { x - 3, ry[i] + 1, KEY_W, h - 1 };
                fw_fill(key, 15, ctx);
            }
            labelled = 0;
        }
        if (!numbers)
            continue;
        if (labelled) {
            if (digits == 1) {
                r[0] = x - 3 + KEY_W - 6 * digits;           /* "C2   1": the number at the key's right edge */
            } else {
                int32_t lab[4] = { x, r[1], 12, 8 };
                fw_fill(lab, 15, ctx);                      /* the number wins: the label ("C3") goes */
            }
        }
        char t[4];
        fw_fmt(t, sizeof t, FMT_D, k + 1);
        fw_text(t, r, 2, ctx);
    }
}

/* Replaces the roll draw's children draw (bl @0x080bd024 in FUN_080bc974). */
void pianoslice_children(uint8_t *roll, const uint8_t *dc)
{
    if (dc[0])
        slice_keys(roll, *(const uint32_t *)(dc + 4));
    fw_children(roll, dc);
}
