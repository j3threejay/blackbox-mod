/* TAPESCAM (tapescam.c, bank 2): the settings, as the host hands them every block. */
#ifndef TAPESCAM_H
#define TAPESCAM_H
#include <stdint.h>

struct tapescam_params {
    float input, drive, color, wobble, tone, output, noise;   /* 0 .. 1 */
    uint32_t comp;    /* 0 Off, 1 Lite, 2 Heavy */
    uint32_t age;     /* 0 New, 1 Used, 2 Worn */
    uint32_t speed;   /* 0 High, 1 Std, 2 Low */
    uint32_t widen;   /* 0 Off, 1 On */
};

uint32_t tapescam_bytes(void);
void tapescam_block(uint8_t *mem, const struct tapescam_params *p, float *l, float *r, int n);
#endif
