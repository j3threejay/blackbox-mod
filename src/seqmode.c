/*
 * Sequence mode switch: switching back brings the notes back. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: changing a sequence cell's mode (param 0xb7: PADS / KEYS / MIDI) to or from PADS clears every note in all
 * four patterns of the cell (manual, Piano Roll, step 3). KEYS <-> MIDI keeps them. Before the clear, stock copies
 * the cell - settings and notes of all four patterns - into the buffer the Sequence Grid's UNDO button restores from
 * (app + 0xe868, 4 x 0x2c, cell id at app + 0xe91c; FUN_08098254 copies in, FUN_080988d4 copies back).
 *
 * Now: when a switch crosses PADS again and that buffer still holds what an earlier switch of THIS cell cleared, the
 * notes come back from it instead of the cell being cleared. Only into a cell that is still empty, and only from
 * a buffer whose mode is on the side the cell is switching to, so nothing the user made is ever replaced:
 *  - KEYS -> PADS -> KEYS: the Keys notes come back (stock: gone).
 *  - Recording in PADS in between: the cell is no longer empty, so the switch back is stock (Pads notes go to the
 *    UNDO buffer, the cell is cleared) - and switching to PADS once more brings THOSE back.
 *  - Anything else that fills the UNDO buffer (REC, CLEAR, another cell's switch) makes it no longer match: stock.
 *  - A preset load or new preset forgets it (the buffer is not reset by a load): stock.
 * Only the notes are restored; the cell's settings (Step Len, Play Pad, ...) stay as they are. The restore is a
 * copy, the buffer keeps its contents, so the Sequence Grid's UNDO still does what it did.
 *
 * Hooks (patches/seqfix.py), all in the app's set-parameter handler FUN_0809fa50, case 0xb7:
 *  - bl @0x0809fef6 (the backup FUN_08098254) -> seqmode_cross_thunk (adds the new mode, held in r11 there)
 *  - bl @0x0809ff08 (clear one pattern's notes FUN_08063cc0, called 4 times) -> seqmode_clear
 * and the five calls to FUN_0809acec (stops every cell; only the preset load / new paths call it) -> seqmode_forget.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

struct list {
    uint16_t *handles;
    uint32_t count, index, _r;
    void *pool;
};

typedef uint8_t *(*cell_fn)(uint8_t *app, const void *ref, unsigned layer);
typedef uint32_t (*cell_param_fn)(uint8_t *cell, unsigned param);
typedef void (*app_cell_fn)(uint8_t *app, const void *ref);
typedef void (*list_clear_fn)(struct list *l);
typedef void (*notes_copy_fn)(uint8_t *dst_layer, const uint8_t *src_layer);
typedef void (*app_fn)(uint8_t *app);

#define fw_cell        ((cell_fn)FN(0x08097ce8))
#define fw_cell_param  ((cell_param_fn)FN(0x08093e9c))
#define fw_backup      ((app_cell_fn)FN(0x08098254))     /* the cell -> the UNDO buffer */
#define fw_list_clear  ((list_clear_fn)FN(0x08063cc0))
#define fw_notes_copy  ((notes_copy_fn)FN(0x08094b72))   /* clear dst's notes, then add src's one by one */
#define fw_stop_all    ((app_fn)FN(0x0809acec))

#define APP_UNDO       0xe868                             /* 4 layers x 0x2c */
#define APP_UNDO_ID    0xe91c                             /* u16: the cell the UNDO buffer belongs to */
#define LAYER_SIZE     0x2c
#define LAYER_LIST     0x18
#define LAYERS         4
#define PARAM_MODE     0xb7                               /* 0 PADS, 1 KEYS, 2 MIDI */
#define REF_ID         4

void bkp_enable(void);

/* Backup SRAM, after rotate.c's ACC (0x388006f0, 2 bytes) and before seqfix.c's clock at 0x38800700. It survives a
   restart and a reflash, so neither word is trusted alone: the tag carries a magic, and a restore also needs the
   UNDO buffer (reset at every boot by FUN_0809a028) to hold notes for this very cell. */
struct seqmode_state {
    uint32_t tag;                                         /* MAGIC | cell id: the UNDO buffer holds what a switch
                                                             of that cell cleared */
    uint8_t *restore;                                     /* this switch restores into this cell (its layer 0) */
    uint8_t *undo;                                        /* ... from this UNDO buffer */
};
#define S     ((volatile struct seqmode_state *)0x388006f4u)
#define MAGIC 0x534d0000u                                 /* "SM" */
_Static_assert(0x388006f4u + sizeof(struct seqmode_state) <= 0x38800700u, "seqmode state runs into seqfix.c's clock");

static int has_notes(const uint8_t *layer0)
{
    for (unsigned i = 0; i < LAYERS; i++)
        if (((const struct list *)(layer0 + i * LAYER_SIZE + LAYER_LIST))->count)
            return 1;
    return 0;
}

/* Replaces the backup; the stock code then clears the four patterns (seqmode_clear) and sets the new mode. */
void seqmode_cross(uint8_t *app, const uint8_t *ref, uint32_t mode)
{
    bkp_enable();
    unsigned id = *(const uint16_t *)(ref + REF_ID);
    uint8_t *cell = fw_cell(app, ref, 0);
    uint8_t *undo = app + APP_UNDO;
    S->restore = 0;
    if (S->tag == (MAGIC | id) && *(const uint16_t *)(app + APP_UNDO_ID) == id
        && (fw_cell_param(undo, PARAM_MODE) == 0) == (mode == 0) && !has_notes(cell) && has_notes(undo)) {
        S->undo = undo;
        S->restore = cell;                                /* keep the buffer as it is: it is what comes back */
        return;
    }
    fw_backup(app, ref);
    S->tag = MAGIC | id;
}

void seqmode_clear(struct list *l)
{
    uint8_t *cell = S->restore;
    if (cell) {
        uint8_t *layer = (uint8_t *)l - LAYER_LIST;
        unsigned off = (unsigned)(layer - cell);
        if (layer >= cell && off % LAYER_SIZE == 0 && off / LAYER_SIZE < LAYERS) {
            fw_notes_copy(layer, S->undo + off);
            if (off / LAYER_SIZE == LAYERS - 1)
                S->restore = 0;
            return;
        }
        S->restore = 0;                                   /* not the cell we expected: never copy into it */
    }
    fw_list_clear(l);
}

void seqmode_forget(uint8_t *app)
{
    bkp_enable();
    S->tag = 0;
    S->restore = 0;
    fw_stop_all(app);
}
