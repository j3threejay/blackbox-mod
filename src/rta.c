/*
 * RTA on the master EQ screen: the hooks (rta_dsp.c has the FFT and the drawing, in bank 2). Original 1010music
 * Blackbox, firmware 3.1.9. Asked for 2026-10-20. EQ screen map: NOTES "EQ screen RE" (FX pressed until screen 0x36,
 * view GUI+0x8de50, graph sub-widget at view+0x34).
 *  - GUI: the EQ graph's draw (vtable 0x080f065c +4, stock FUN_080aa13c) comes here. Stock already asks for an overlay
 *    redraw every frame on this screen; on that pass the spectrum is drawn first, then stock's curve, nodes and frame
 *    on top. Each frame also keeps the audio side fed (alive).
 *  - Audio: comp_process (comp.c) calls rta_tap first thing every block: Out 1 right after the stock EQ (engine
 *    0x08053526) and before the Master FX / compressor / clipper, i.e. what the EQ curve shapes. Read-only: the bus
 *    is not forced to stereo. Nothing happens unless the EQ screen drew in the last ~0.25 s.
 * Without the bank 2 payload: stock's screen, untouched.
 * CPU (test_rta.py, emulator instructions): see the numbers printed there; audio side only while the EQ screen shows,
 * GUI side in the screen task, below the audio task.
 */
#include <stdint.h>
#include "rta.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*draw_fn)(uint8_t *widget, uint8_t *dc);
typedef void *(*buf_of_fn)(void *bufs, unsigned idx);
typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **l, float **r);
typedef unsigned (*index_fn)(int *obj);

#define fw_graph_draw ((draw_fn)FN(0x080aa13c))   /* stock: the EQ graph's curve, then its children (nodes, frame) */
#define fw_buf_of     ((buf_of_fn)FN(0x0805f37c))
#define fw_buf_silent ((buf_int_fn)FN(0x0804d8f4))
#define fw_buf_frames ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_chans  ((buf_chans_fn)FN(0x0804d944))
#define DEFAULT_INDEX_FN 0x08046a15u               /* stock "output index" method: reads obj +0x1e */
#define ALIVE 48                                   /* audio blocks (~0.25 s) */

uint8_t *master_block(void);
int b2_live(void);

static struct rta_state *rta(void)
{
    uint8_t *mem = master_block();
    return mem ? (struct rta_state *)(mem + RTA_OFFSET) : 0;
}

/* EQ graph vtable slot 1 (word @0x080f0660). dc: {full pass, overlay pass, .., canvas @+4}; graph +4: x, y, w, h. */
void rta_graph_draw(uint8_t *graph, uint8_t *dc)
{
    if (dc[1] && b2_live()) {
        struct rta_state *s = rta();
        if (s) {
            rta_frame(s, (const int32_t *)(graph + 4), *(void **)(dc + 4));
            s->alive = ALIVE;   /* after: the first frame sets the state up */
        }
    }
    fw_graph_draw(graph, dc);
}

/* comp.c's comp_process, before anything else: obj = the compressor stage (its output index is Out 1's bus) */
void rta_tap(int *obj, void *bufs)
{
    struct rta_state *s = rta();
    if (!s || s->magic != RTA_MAGIC || !s->alive || !b2_live())
        return;
    index_fn index = *(index_fn *)(*obj + 0x54);
    unsigned out = (uint32_t)index == DEFAULT_INDEX_FN ? *(uint16_t *)((uint8_t *)obj + 0x1e) : index(obj);
    void *buf = fw_buf_of(bufs, out);
    if (!buf)
        return;
    int n = fw_buf_frames(buf);
    if (n <= 0 || n > 4096)
        return;
    float *l = 0, *r = 0;
    if (!fw_buf_silent(buf))
        fw_buf_chans(buf, &l, &r);
    rta_feed(s, l, r, n);
}
