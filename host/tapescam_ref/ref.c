/* Charles Vestal's TAPESCAM exactly as published (tapescam_orig.c, unmodified), driven from Python for
   test_tapescam.py. Only the I/O differs from his v2_process_block: float in / out instead of int16, so the
   comparison measures the port, not 16-bit rounding. Everything inside the chain is his code and his libm. */
#include "tapescam_orig.c"

void *ref_create(void) { return v2_create_instance(0, 0); }
void ref_set(void *inst, const char *key, const char *val) { v2_set_param(inst, key, val); }

void ref_process(void *instance, float *l, float *r, int frames)
{
    tapescam_instance_t *inst = (tapescam_instance_t *)instance;
    float inputGain = inst->param_input;
    for (int i = 0; i < frames; i++) {
        l[i] *= inputGain;
        r[i] *= inputGain;
    }
    v2_TapeSat_UpdateControls(inst);
    v2_WF_UpdateControls(inst);
    v2_Tone_UpdateControls(inst, SAMPLE_RATE);
    v2_Hiss_UpdateControls(inst);
    v2_GS_Process(inst, l, r, frames);
    v2_TapeSat_Process(inst, l, r, frames);
    v2_WF_Process(inst, l, r, l, r, frames, SAMPLE_RATE);
    v2_Hiss_Process(inst, l, r, frames);
    v2_Dropout_Process(inst, l, r, frames);
    v2_Tone_Process(inst, l, r, frames);
    v2_Comp_Process(inst, l, r, frames);
    v2_Width_Process(inst, l, r, frames);
    for (int i = 0; i < frames; i++) {
        float out_l = tanhf(l[i] * inst->param_outputLevelLin * 0.95f);
        float out_r = tanhf(r[i] * inst->param_outputLevelLin * 0.95f);
        l[i] = Clamp(out_l, -1.0f, 1.0f);
        r[i] = Clamp(out_r, -1.0f, 1.0f);
    }
}
