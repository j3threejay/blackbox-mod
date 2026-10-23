/* RTA on the master EQ screen: what rta.c (the hooks; bank 1) and rta_dsp.c (FFT + drawing; bank 2) share. */
#ifndef RTA_H
#define RTA_H
#include <stdint.h>

#define RTA_OFFSET (0x56800u + 0x2d100u)                /* in master.c's SDRAM block, behind comp.c's clipper */
#define RTA_BYTES  0x10000u
#define RTA_N      2048                                 /* FFT length: 42.7 ms, 23.4 Hz a bin */
#define RTA_COLS   320                                  /* one value per pixel column of the EQ graph */
#define RTA_MAGIC  0x52544131u                          /* "RTA1" */

struct rta_state {
    uint32_t magic;
    volatile uint32_t alive;     /* GUI: audio blocks to keep feeding (set every EQ frame); the audio task counts down */
    volatile uint32_t w;         /* audio: ring write position */
    uint32_t frame;              /* GUI: frames drawn */
    float ring[RTA_N];           /* audio: Out 1 after the EQ, (L + R) / 2 */
    float re[RTA_N / 2], im[RTA_N / 2];               /* GUI: the real FFT as an N / 2-point complex one */
    float pw[RTA_N / 2 + 1];     /* GUI: power per bin */
    float cs[RTA_N / 2], sn[RTA_N / 2];                 /* cos / sin (2 pi k / N) */
    uint16_t lo[RTA_COLS], hi[RTA_COLS];                /* column -> bins: hi == 0 means interpolate lo .. lo + 1 */
    float fr[RTA_COLS];
    float db[RTA_COLS];          /* what is shown, dB with the tilt */
};
_Static_assert(sizeof(struct rta_state) <= RTA_BYTES, "master.c gives the RTA RTA_BYTES");

/* rta_dsp.c, bank 2: call only when b2_live() */
void rta_feed(struct rta_state *s, const float *l, const float *r, int n);   /* l == 0: n frames of silence */
void rta_frame(struct rta_state *s, const int32_t *rect, void *canvas);      /* rect: x, y, w, h of the graph */

#endif
