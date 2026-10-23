/* VHS (Master FX type 1): what master.c (settings, glue; bank 1) and vhs.c (the DSP; bank 2) share. */
#ifndef VHS_H
#define VHS_H
#include <stdint.h>

struct vhs_params {
    float wow, flut, sat, fail, noise, hicut, locut;    /* the seven knobs, 0..1 */
};

/* The state's first word, which master.c clears when VHS is not selected so the next start is clean. */
#define VHS_MAGIC_AT ((volatile uint32_t *)0x38800f20u)
#define VHS_MAGIC    0x474c3031u                        /* "GL01" */

void vhs_block(const struct vhs_params *p, float *l, float *r, int n);

#endif
