/*
 * The boot splash: the JOEBOX graphic instead of "blackbox / by 1010music". Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock's app splash (FUN_080c70b8, vtable 0x080f19a4) is six text labels in a view whose draw (vtable +4) is the
 * generic "draw my children" FUN_080aeaf8: "blackbox", "by 1010music", three empty status lines (y 0x3c / 0x28 / 0x14,
 * where stock writes boot messages) and the version (x 200, y 0). It shows ~2 s on every boot (seen on video, 10-17).
 *
 * How the screen is drawn (FUN_0808b2d0 / FUN_0808b604): every frame the GUI clears ONE full-screen 8-bit surface
 * (GUI + 0x274: buffer, width 320, height 240, format 5 = L8, orientation 1 = buffer row 0 is the top of the screen),
 * the current view draws palette INDICES into it, and the DMA2D converts the whole surface to the LTDC layer through
 * its own CLUT (theme.c). The CLUT holds 256 entries and stock loads 34. So the graphic is stored as indices 34..255
 * (host/splash/make_splash.py: mock-up B, 222 colours, run-length coded, ~21 KB in bank 2), and this draw:
 *   1. builds a 256-entry CLUT IN THE SURFACE ITSELF (the DMA2D can read it, and the next step overwrites it):
 *      entries 0..33 = the live RAM palette (so a theme is never disturbed), 34.. = the graphic's colours; cleans
 *      those cache lines and loads it for both layers with stock's own sequence (theme.c's clut_reload, 256 long);
 *   2. decodes the graphic over the whole surface;
 *   3. lets the status lines draw on top (boot messages still show), and in a test build the version label too
 *      (the build letter matters there); a release build leaves the version off: the name is in the graphic.
 * theme.c's per-frame check reloads entries 0..33 only, so it never touches 34..255; nothing else uses them.
 * Without the matching bank 2 payload (b2_present: an install whose BBEXTRA is not on the unit yet, or none) or on a
 * surface that is not the 320 x 240 L8 one, stock's text splash draws exactly as before.
 * Cost: boot only, GUI task, ~2 s of frames: one payload check (sums bank 2), a 1 KB CLUT load, 76,800 bytes written.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*draw_fn)(void *view, void *arg);     /* the generic draw passes (child, arg) on, nothing else */
typedef int (*clut_cfg_fn)(void *dma2d, const volatile uint32_t *clut, int mode, int size, int layer);
typedef int (*clut_on_fn)(void *dma2d, int layer);
typedef int (*dma_wait_fn)(void *dma2d, uint32_t ms);
#define fw_view_draw ((draw_fn)FN(0x080aeaf8))
#define fw_clut_cfg  ((clut_cfg_fn)FN(0x0807af64))
#define fw_clut_on   ((clut_on_fn)FN(0x0807ab8c))
#define fw_dma_wait  ((dma_wait_fn)FN(0x0807abc2))
#define DMA2D_HANDLE ((void *)(0x24001facu + 0xa8u))
#define DCCMVAC      (*(volatile uint32_t *)0xe000ef68u)
#define PALETTE      ((const volatile uint32_t *)0x24000000u)

int b2_present(void);                    /* cpu.c: this image's bank 2 payload is on the unit */
extern const uint32_t splash_colours;    /* splash_img.c, in bank 2 */
extern const uint32_t splash_clut[];
extern const uint32_t splash_rle_len;
extern const uint8_t splash_rle[];

#define W 320
#define H 240
#define FIRST 34
/* the splash view's children (FUN_080c70b8): labels at these offsets */
#define CHILD_STATUS1 0xe4
#define CHILD_STATUS2 0x13c
#define CHILD_STATUS3 0x194
#define CHILD_VERSION 0x1ec

struct surface {
    uint8_t *buf;
    uint16_t w, h;
    uint8_t format, orient;
};

static int graphic(uint8_t *buf)
{
    uint32_t colours = splash_colours;
    if (colours > 256u - FIRST)
        return 0;
    void *h = DMA2D_HANDLE;
    fw_dma_wait(h, 100);                  /* the frame's clear of this surface may still be a DMA2D fill (FUN_08041e5c) */
    uint32_t *clut = (uint32_t *)buf;
    for (int i = 0; i < FIRST; i++)
        clut[i] = PALETTE[i];
    for (uint32_t i = 0; i < colours; i++)
        clut[FIRST + i] = splash_clut[i];
    for (uint32_t a = (uint32_t)buf & ~31u; a < (uint32_t)buf + (FIRST + colours) * 4u; a += 32u)
        DCCMVAC = a;
    __asm volatile("dsb" ::: "memory");
    for (int layer = 0; layer < 2; layer++) {
        fw_dma_wait(h, 100);
        fw_clut_cfg(h, (const volatile uint32_t *)clut, 0, (int)(FIRST + colours - 1), layer);
        fw_dma_wait(h, 100);
        fw_clut_on(h, layer);
        fw_dma_wait(h, 100);
    }
    uint32_t at = 0, len = splash_rle_len & ~1u;
    for (uint32_t i = 0; i < len && at < W * H; i += 2) {
        uint32_t n = splash_rle[i];
        uint8_t v = splash_rle[i + 1];
        if (n > W * H - at)
            n = W * H - at;
        while (n--)
            buf[at++] = v;
    }
    while (at < W * H)                    /* a short table: the rest black, never stock's transparent 0 */
        buf[at++] = FIRST;
    return 1;
}

/* Replaces the splash view's draw (vtable 0x080f19a4 +4 = FUN_080aeaf8). GUI task. */
void splash_draw(uint8_t *view, uint8_t *arg)
{
    const struct surface *s = arg ? *(const struct surface **)(arg + 4) : 0;
    if (!s || !s->buf || ((uint32_t)s->buf & 3u) || s->format != 5 || s->orient != 1 || s->w != W || s->h != H ||
        !b2_present() || !graphic(s->buf)) {
        fw_view_draw(view, arg);
        return;
    }
    for (uint8_t *c = *(uint8_t **)(view + 0x1c); c; c = *(uint8_t **)(c + 0x24)) {
        uint32_t off = (uint32_t)(c - view);
        int show = off == CHILD_STATUS1 || off == CHILD_STATUS2 || off == CHILD_STATUS3;
#ifndef PUBLIC_BUILD
        show |= off == CHILD_VERSION;
#endif
        if (show && !c[0x30])             /* the generic draw skips a hidden child (+0x30) the same way */
            (*(draw_fn *)(*(uint8_t **)c + 4))(c, arg);
    }
}
