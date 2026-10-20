/*
 * Waveform screen: the four corner knobs' text white with a 1 px black edge, in every pad mode. Original 1010music
 * Blackbox, firmware 3.1.9.
 *
 * Stock: the Waveform view's constructor (FUN_080a5b90) builds its four corner knobs once, for every pad mode, and
 * greys their text: FUN_080b02e6 puts colour 9 (#666666) in each knob's three labels. A knob shows one line here, its
 * + 0xf4 label (the knob's layouts 1..4: TL and BL left-aligned in a box of 151 x 20 px from x 6, TR and BR
 * right-aligned to x 309), in the 6 x 8 font at size 0x10. That grey reads 3.3:1 on the waveform's cyan (#09d7f5) and
 * 3.2:1 on the background (#141414). No single colour fixes both: white alone reads 1.7:1 on the cyan, black 1.1:1 on
 * the background.
 *
 * This makes the line white (palette 15) with a 1 px black edge (14), 12:1 or better on both: stock's own label draw
 * eight times in black, one pixel off in each direction, then once in white. All nine land in the label's box inset by
 * a pixel (the doubled glyphs touch the box's left and bottom edges), so a value that changes leaves nothing outside
 * the box the screen repaints. Each pass draws a copy of the label: the label itself (its box, its grey, its dirty
 * flags) is never touched. The line's vtable is a copy of stock's with its two draws replaced (the whole draw, and the
 * one clipped to a dirty rectangle). Same font, size and text; the knobs' name and value labels are left alone (they
 * are not shown on this screen). The GUI task pays for it: nine draws of the line where stock does one.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

#define LABEL_VT     0x080f17a4u     /* the text label's vtable: [1] draw, [2] draw clipped to a rectangle */
#define LABEL_SIZE   0x58
#define LABEL_BOX    0x04            /* i32 x, y, w, h */
#define LABEL_COLOUR 0x53            /* a palette index (the palette at 0x24000000) */
#define KNOB_LINE    0xf4            /* the knob's "name value" label (layouts 1..4) */
#define PAL_BLACK    14
#define PAL_WHITE    15

typedef void (*label_draw_fn)(uint8_t *label, const void *ctx, const void *clip);
typedef void (*colour_fn)(uint8_t *knob, int colour);
typedef void (*vfn)(void);

#define fw_label_draw  ((label_draw_fn)FN(0x080c3d2c))   /* (label, ctx): ctx + 4 the layer */
#define fw_label_clip  ((label_draw_fn)FN(0x080c3fc6))   /* (label, ctx, the dirty rectangle) */
#define fw_knob_colour ((colour_fn)FN(0x080b02e6))       /* the colour of a knob's three labels */

static void edged(uint8_t *label, const void *ctx, const void *clip, label_draw_fn draw)
{
    uint32_t copy[LABEL_SIZE / 4];
    for (unsigned i = 0; i < LABEL_SIZE / 4; i++)
        copy[i] = ((const uint32_t *)label)[i];
    uint8_t *c = (uint8_t *)copy;
    int32_t *box = (int32_t *)(c + LABEL_BOX), x = box[0] + 1, y = box[1] + 1;
    box[2] -= 2;
    box[3] -= 2;
    for (int i = 0; i < 10; i++) {   /* the eight around it, then the centre (k = 4) in white */
        int k = i == 9 ? 4 : i;
        if (i == 4)
            continue;
        box[0] = x + k % 3 - 1;
        box[1] = y + k / 3 - 1;
        c[LABEL_COLOUR] = k == 4 ? PAL_WHITE : PAL_BLACK;
        draw(c, ctx, clip);
    }
}

static void wavelabel_draw(uint8_t *label, const void *ctx)
{
    edged(label, ctx, 0, fw_label_draw);
}

static void wavelabel_clip(uint8_t *label, const void *ctx, const void *clip)
{
    edged(label, ctx, clip, fw_label_clip);
}

/* stock's (its fourteen entries and the two words after them), with the two draws ours */
static const vfn wavelabel_vt[16] = {
    (vfn)0x080c3b75, (vfn)wavelabel_draw, (vfn)wavelabel_clip, (vfn)0x080aebab, (vfn)0x080a370d, (vfn)0x080a3315,
    (vfn)0x080a370f, (vfn)0x080c3b95, (vfn)0x080a3715, (vfn)0x080a3317, (vfn)0x080aeb5f, (vfn)0x080a331b,
    (vfn)0x080aec05, (vfn)0x080a3321, 0, 0};

/* Replaces bl FUN_080b02e6 @0x080a660a, 0x080a6612, 0x080a661a, 0x080a6622 (TL, BL, TR, BR): the view's constructor
   colouring its four corner knobs, once. The grey stays in the labels; the line's vtable is ours from here on, in every
   pad mode, since nothing sets a label's vtable again. A line that is not stock's label is left alone. */
void wavelabel(uint8_t *knob, int colour)
{
    fw_knob_colour(knob, colour);
    if (*(const uint32_t *)(knob + KNOB_LINE) == LABEL_VT)
        *(const vfn **)(knob + KNOB_LINE) = wavelabel_vt;
}
