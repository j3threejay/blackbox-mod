/*
 * Colour themes. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock draws everything with ONE 34-entry palette: ARGB8888 words in RAM at 0x24000000 (.data, copied at boot from
 * flash 0x080f1d80); screens pass palette INDICES (FUN_0808ea22 fill, FUN_0808f23c text...). A theme is a different
 * set of 34 colours, nothing else. "Theme:" on Tools Main (global list 0x144, saved as "theme"): Stock, Midnight,
 * Blue LCD, Amber VFD (the favourites from host/themes; the table is generated from those mock-ups).
 *
 * How:
 *  - The GUI task's loop (FUN_08043dec) composes a frame with FUN_0808b2d0 after every message. The hook before it
 *    compares the RAM palette with the selected theme and, when they differ, copies the theme in and asks for the
 *    full clear + redraw a screen switch does (GUI holder +0x38 / +0x39, as munchi.cpp's fx_screen_msg). No state of
 *    our own: boot (palette = stock .data, setting loaded) and a change on Tools take the same path.
 *  - THE SCREEN DOES NOT READ THE RAM PALETTE (3.3.n on the test unit: the list changed, nothing else did). The GUI draws
 *    8-bit palette indices; the DMA2D turns them into colour through its OWN CLUT, which stock loads once at boot
 *    (FUN_080418c8: CLUT config FUN_0807af64(h, 0x24000000, 0, 0x21, layer), enable FUN_0807ab8c, wait FUN_0807abc2,
 *    for layers 0 and 1; handle = the display object 0x24001fac + 0xa8). So after a copy: clean the palette's cache
 *    lines (the DMA2D reads memory, the copy is in the M7's write-back cache) and run stock's same load sequence.
 *  - The full redraw clears the layer with a hard-coded #141414 (pool word 0x0808b45c, FUN_0808f90c). That clear now
 *    takes palette entry 2 instead, which IS #141414 on stock, so stock looks the same.
 *  - The piano roll writes its pad numbers and step numbers in colour 2, the background colour, on grey cells
 *    (FUN_080bc974). On a theme they would vanish; with any theme but Stock those three calls use 15 (text).
 *    The fourth call there (note names on the keys) is left alone: 2 on key colour 15 reads on every theme.
 * Cost: none on the audio thread. GUI: 34 compares per frame; a change copies 34 words and redraws once.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, int param);
typedef void (*compose_fn)(void *gui);
typedef void (*clear_fn)(void *layer, uint32_t argb);
typedef void (*text_fn)(const char *text, const int32_t *rect, int colour, void *ctx);

#define fw_register_list ((register_fn)FN(0x0808c0d8))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_compose       ((compose_fn)FN(0x0808b2d0))
#define fw_clear         ((clear_fn)FN(0x0808f90c))
#define fw_text          ((text_fn)FN(0x0808f23c))

#define SETTINGS     ((const void *)(0x24020088u + 0x8c90u))     /* app: global settings store */
#define PARAM_THEME  0x144   /* not 0x1ba: that is the insert's Depth (P_INS_RATE + 1) */
#define PALETTE      ((volatile uint32_t *)0x24000000u)
#define STOCK_PALETTE ((const uint32_t *)0x080f1d80u)
#define GUI_HOLDER   0x280                                        /* +0x38 / +0x39 = redraw / full redraw wanted */

typedef int (*clut_cfg_fn)(void *dma2d, const volatile uint32_t *clut, int mode, int size, int layer);
typedef int (*clut_on_fn)(void *dma2d, int layer);
typedef int (*dma_wait_fn)(void *dma2d, uint32_t ms);
#define fw_clut_cfg  ((clut_cfg_fn)FN(0x0807af64))
#define fw_clut_on   ((clut_on_fn)FN(0x0807ab8c))
#define fw_dma_wait  ((dma_wait_fn)FN(0x0807abc2))
#define DMA2D_HANDLE ((void *)(0x24001facu + 0xa8u))              /* the display object's DMA2D handle */
#define DCCMVAC      (*(volatile uint32_t *)0xe000ef68u)          /* clean D-cache line by address */

/* Stock's boot sequence (FUN_080418c8), again: the DMA2D's CLUT for both layers from the RAM palette. */
static void clut_reload(void)
{
    for (uint32_t a = 0x24000000u; a < 0x24000000u + 34u * 4u; a += 32u)
        DCCMVAC = a;
    __asm volatile("dsb" ::: "memory");
    void *h = DMA2D_HANDLE;
    for (int layer = 0; layer < 2; layer++) {
        fw_dma_wait(h, 100);                                      /* a blit still running finishes first */
        fw_clut_cfg(h, PALETTE, 0, 0x21, layer);
        fw_dma_wait(h, 100);
        fw_clut_on(h, layer);
        fw_dma_wait(h, 100);
    }
}

#include "theme_palettes.inc"

void theme_register(void *table)
{
    fw_register_list(table, PARAM_THEME, "Theme:", theme_names, THEMES, "theme");
}

void theme_defaults(void *store)
{
    fw_store_add(store, PARAM_THEME, 0);
}

static unsigned theme_now(void)
{
    unsigned t = (unsigned)fw_setting(SETTINGS, PARAM_THEME);
    return t < THEMES ? t : 0;
}

void chop_poll(void);

/* Replaces the GUI loop's compose call (bl @0x08043e4c). */
void theme_compose(uint8_t *gui)
{
    unsigned t = theme_now();
    const uint32_t *want = t ? theme_palettes[t - 1] : STOCK_PALETTE;
    int differ = 0;
    for (int i = 0; i < 34; i++)
        if (PALETTE[i] != want[i]) {
            PALETTE[i] = want[i];
            differ = 1;
        }
    if (differ) {
        clut_reload();
        if (gui) {
            gui[GUI_HOLDER + 0x38] = 1;
            gui[GUI_HOLDER + 0x39] = 1;
        }
    }
    chop_poll();                                        /* chop.c: a ChopShop operation's next step (GUI task) */
    fw_compose(gui);
}

/* Replaces the full redraw's layer clear (bl @0x0808b3a6): the theme's background instead of a fixed #141414. */
void theme_clear(void *layer, uint32_t argb)
{
    (void)argb;
    fw_clear(layer, PALETTE[2] | 0xff000000u);
}

/* Replaces three of the piano roll's text calls (FUN_080bc974): colour 2 becomes 15 on any theme but Stock. */
void theme_roll_text(const char *text, const int32_t *rect, int colour, void *ctx)
{
    if (colour == 2 && theme_now())
        colour = 15;
    fw_text(text, rect, colour, ctx);
}
