/*
 * Pad numbers on the pad picker. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: the pad picker (the 4 x 4 overlay behind the grid icon on the waveform / parameter pages, the Keys screen,
 * the sequence pad mapping and six more places; one class, constructor FUN_080ae6f8) draws plain squares, the
 * selected one filled. The sequence picker numbers its squares; this one never did.
 * Now every square carries its pad's number, in stock's own numbering: 1 bottom left, across, then up (the manual's
 * MIDI map; the sequence picker counts the same way). Nothing is renumbered, only labelled.
 *
 * How: the squares are buttons (FUN_080a3f50, a FUN_080a3d34 subclass of 0xac bytes) and their draw (0x080a3ab0)
 * already paints the button's label after the fill; stock just never sets one. The constructor's loop adds each
 * square to the view (FUN_080aec44) right after storing its position at +0xa4 as row << 4 | col. The GUI's y runs
 * UP from the bottom of the screen (the picker overlay is y 0..182 under a 38 px tab bar and the 20 px title), so
 * row 0 is the BOTTOM row and pad id 0 is pad 1, the same pad the ducker listens to (duck_thunk.S). The hook does
 * that add, then sets the label from the position
 * and runs the button's restyle (vtable +0x40) so the text takes its colour now rather than on the first touch.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*add_child_fn)(void *view, void *child);
typedef void (*set_label_fn)(void *button, const char *text);
typedef void (*method_fn)(void *self);

#define fw_add_child ((add_child_fn)FN(0x080aec44))
#define fw_set_label ((set_label_fn)FN(0x080a3dec))

void padsel_add_cell(void *view, uint8_t *cell)
{
    fw_add_child(view, cell);
    unsigned pos = *(const uint16_t *)(cell + 0xa4);
    unsigned n = ((pos >> 4) & 3u) * 4u + (pos & 3u) + 1u;
    char text[3];
    if (n >= 10) {
        text[0] = '1';
        text[1] = (char)('0' + n - 10);
        text[2] = 0;
    } else {
        text[0] = (char)('0' + n);
        text[1] = 0;
    }
    fw_set_label(cell, text);
    (*(method_fn *)(*(uint8_t **)cell + 0x40))(cell);
}
