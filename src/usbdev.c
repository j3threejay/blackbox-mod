/*
 * USB MIDI device on the POWER jack. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock runs one USB controller, OTG_FS at 0x40080000 on PA11 / PA12, as the host for the USB-A jack. The other one,
 * OTG_HS at 0x40040000, is never touched, and the pins of its built-in full-speed transceiver (PB14 = D-, PB15 = D+)
 * are never set up. The power jack's data lines go to those two pins (3.1.K enumerated on a Mac, 2026-10-05), so the
 * computer feeding the power jack sees a full-speed, class-compliant MIDI device, "Blackbox", one port each way.
 *
 * usbdev_poll runs from the audio task's wait (cpu_wait), once per audio block (128 frames = 2.67 ms), and answers
 * the control requests of enumeration from there. Since 3.1.Q the controller's interrupt empties the receive FIFO:
 * MIDI from the computer goes into a small queue the moment it arrives and the endpoint is armed again at once, so
 * several packets inside one block are all taken (before, the second one waited a block).
 *
 * CLOCK IN: nothing special. 3.1.Q also moved each tick's stamp to where in the block it arrived (cycle counter in
 * the interrupt, a wrapper on the tail call to FUN_08070304 @0x0806a2dc). Measured on the unit it gained nothing:
 * the sequencer's own kicks sit 0.58 ms sd / 1.9 ms peak to peak off a grid on the INTERNAL clock, slaved on 3.1.P
 * they measured the same (0.60 / 2.0), and with the finer stamps 0.81 / 3.2. Taken out again in 3.1.R.
 *
 * Stock's MIDI manager (the object at 0x24002e88) already speaks USB-MIDI's four-byte events for the USB-A host jack,
 * and both ends of it run in this same task:
 *   in:  FUN_08044708(manager, events, bytes) queues events exactly as if they came from the USB-A jack, so MIDI In /
 *        Clock settings of "USB Device" apply to this port too. It stops at the first event it does not know, so
 *        anything but channel messages and single-byte real-time is dropped here first (stock drops those as well).
 *   out: FUN_08044896 packs the "to USB" message queue for the host jack once per block (bl @0x08044b08). Our wrapper
 *        reads the same queue first, without consuming it, and sends it to the computer. So USB Dev Out governs both.
 *        Stock's packer keeps only notes and clock / start / stop; ours sends whatever is in the queue, except a
 *        Start straight after a Start or a Stop after a Stop (slaved, stock puts each in the queue twice).
 *
 * AUDIO (3.1.M): the three stereo outputs, 6 channels of 24-bit at 48 kHz, to the computer (USB Audio 1.0, one
 * isochronous IN endpoint, asynchronous: the Blackbox's converter clock is the clock, the computer follows).
 *   tap:  the block function's last step turns its float output buffers into converter words: FUN_0806002c(a, b, c,
 *         frames, dst, 4) twice (bl @0x0804cf62 / @0x0804cf7c; three 20-bit samples per pair of 32-bit words, so the
 *         converters get 20 bits and USB gets 24), then FUN_0805feb4 twice (bl @0x0804cf8e / @0x0804cfa0). usbaud_tap
 *         and usbaud_tap1 wrap them and copy three of the four buses, after the Out volumes, into a ring of 1024
 *         frames in SDRAM (behind Prism's block).
 *   send: one packet per 1 ms USB frame, loaded by the controller's own interrupt (vector 77, usbaud_isr), which is
 *         the only interrupt this file uses and touches only endpoint 2. 48 frames a packet, 47 or 49 when the ring
 *         runs low or high, silence until the ring has ~4.7 ms in it.
 * State: 48 bytes of backup SRAM at 0x38800680, the MIDI queue at 0x38800908. (Until 3.3.h the state sat at 0x38800650,
 * where the last 4 bytes of comp.c's Limit lookahead overwrote the first 4 of the SETUP packet - see comp.c.)
 *
 * DEBUG (3.1.N; compiled OUT of a public build, PUBLIC_BUILD - see release.h): two vendor requests on endpoint 0 let the computer read memory and
 * write a word (peek 0xc0 / 0x50, poke 0x40 / 0x51 + 0x52), so registers and counters can be read on the running unit.
 * Both stay inside whole memory regions (MEM, below): a read that runs past the end of one bus-faults the chip. A dev
 * build also flushes endpoint 0's IN FIFO at every SETUP, so a reply the computer timed out on is not sent later as
 * the answer to the next request.
 */
#include <stdint.h>

void bkp_enable(void);           /* od.c */
uint8_t *master_block(void);     /* master.c: the SDRAM block taken at boot, or 0 */

#define REG(a) (*(volatile uint32_t *)(a))

#define RCC_D2CCIP2R  REG(0x58024454u)
#define USBSEL        (3u << 20)             /* the 48 MHz source both controllers share; stock sets it for the host */
#define RCC_AHB1ENR   REG(0x580244d8u)
#define RCC_AHB1LPENR REG(0x58024500u)
#define OTGHSEN       (1u << 25)
#define OTGHSULPIEN   (1u << 26)
#define OTGFSEN       (1u << 27)
#define PWR_CR3       REG(0x5802480cu)
#define USB33DEN      (1u << 24)

#define GPIOB         0x58020400u
#define GPIO_MODER    0x00
#define GPIO_OSPEEDR  0x08
#define GPIO_PUPDR    0x0c
#define GPIO_AFRH     0x24

#define USB           0x40040000u
#define GOTGCTL   REG(USB + 0x000)
#define GUSBCFG   REG(USB + 0x00c)
#define GRSTCTL   REG(USB + 0x010)
#define GINTSTS   REG(USB + 0x014)
#define GINTMSK   REG(USB + 0x018)
#define GRXSTSP   REG(USB + 0x020)
#define GRXFSIZ   REG(USB + 0x024)
#define DIEPTXF0  REG(USB + 0x028)
#define GCCFG     REG(USB + 0x038)
#define DCFG      REG(USB + 0x800)
#define DCTL      REG(USB + 0x804)
#define DIEPCTL0  REG(USB + 0x900)
#define DIEPINT0  REG(USB + 0x908)
#define DIEPTSIZ0 REG(USB + 0x910)
#define DOEPCTL0  REG(USB + 0xb00)
#define DOEPINT0  REG(USB + 0xb08)
#define DOEPTSIZ0 REG(USB + 0xb10)
#define PCGCCTL   REG(USB + 0xe00)
#define FIFO0     REG(USB + 0x1000)
#define DIEPTXF1  REG(USB + 0x104)
#define DIEPCTL1  REG(USB + 0x920)
#define DIEPINT1  REG(USB + 0x928)
#define DIEPTSIZ1 REG(USB + 0x930)
#define DOEPCTL1  REG(USB + 0xb20)
#define DOEPINT1  REG(USB + 0xb28)
#define DOEPTSIZ1 REG(USB + 0xb30)
#define FIFO1     REG(USB + 0x2000)
#define GAHBCFG   REG(USB + 0x008)
#define DIEPTXF2  REG(USB + 0x108)
#define DSTS      REG(USB + 0x808)
#define DIEPMSK   REG(USB + 0x810)
#define DAINTMSK  REG(USB + 0x81c)
#define DIEPCTL2  REG(USB + 0x940)
#define DIEPINT2  REG(USB + 0x948)
#define DIEPTSIZ2 REG(USB + 0x950)
#define FIFO2     REG(USB + 0x3000)
#define NVIC_ISER2 REG(0xe000e108u)
#define NVIC_ICER2 REG(0xe000e188u)
#define NVIC_IPR77 (*(volatile uint8_t *)0xe000e44du)
#define IRQ_BIT   (1u << 13)                 /* interrupt 77, OTG_HS, in the third enable word */

#define PHYSEL    (1u << 6)                  /* GUSBCFG: the built-in full-speed transceiver */
#define FDMOD     (1u << 30)                 /* GUSBCFG: device, whatever the ID pin says */
#define TRDT_6    (6u << 10)
#define CSRST     (1u << 0)
#define RXFFLSH   (1u << 4)
#define TXFFLSH_ALL ((1u << 5) | (0x10u << 6))
#define PWRDWN    (1u << 16)                 /* GCCFG: transceiver on */
#define VBDEN     (1u << 21)
#define BVALO     ((1u << 6) | (1u << 7))    /* GOTGCTL: "VBUS is valid", without a sensing pin */
#define SDIS      (1u << 1)                  /* DCTL: soft disconnect (D+ pull-up off) */
#define CGINAK    (1u << 8)
#define RXFLVL    (1u << 4)
#define USBRST    (1u << 12)
#define ENUMDNE   (1u << 13)
#define EPENA     (1u << 31)
#define CNAK      (1u << 26)
#define STALL     (1u << 21)
#define STUP      (1u << 3)
#define EPDIS     (1u << 30)
#define SNAK      (1u << 27)
#define SD0PID    (1u << 28)
#define NAKSTS    (1u << 17)
#define USBAEP    (1u << 15)
#define BULK_64   (64u | USBAEP | (2u << 18) | SD0PID)
#define TXFIFO_1  (1u << 22)
#define TXFFLSH_1 ((1u << 5) | (1u << 6))
#define TXFFLSH_0 (1u << 5)
#define TXFFLSH_2 ((1u << 5) | (2u << 6))
#define IEPINT    (1u << 18)
#define IISOIXFR  (1u << 20)
#define XFRC      (1u << 0)
#define EPDISD    (1u << 1)
#define SODDFRM   (1u << 29)
#define SEVNFRM   (1u << 28)
#define ISO_882   (882u | USBAEP | (1u << 18) | (2u << 22))

/* audio: 6 channels x 3 bytes a frame; 47..49 frames a packet */
#define CHANNELS   6
#define RING       1024u         /* frames */
#define RING_BYTES (RING * CHANNELS * 4u)
#define RING_OFFSET (0x56800u + 0x1000u)     /* behind Prism's block and the LFOs' (master.c) */
#define PRIME      224u          /* frames in the ring before the first real packet */
#define LOW        96u
#define HIGH       352u
typedef void (*to_dac_fn)(const float *a, const float *b, const float *c, int frames, uint32_t *dst, int stride);
#define fw_to_dac ((to_dac_fn)(0x0806002cu | 1u))

typedef void (*midi_in_fn)(void *manager, const uint8_t *events, unsigned bytes);
typedef int (*midi_pack_fn)(void *manager, uint8_t *queue, uint8_t *out, unsigned max, unsigned *len);
#define fw_midi_usb_in ((midi_in_fn)(0x08044708u | 1u))
#define fw_midi_pack   ((midi_pack_fn)(0x08044896u | 1u))
#define MIDI_MANAGER   ((void *)0x24002e88u)
#define Q_READ   0x500           /* a message queue: 256 x 5 bytes (up to 4 of message, then its length), two counters */
#define Q_WRITE  0x504
#define OUT_EVENTS 64            /* at most this many events to the computer per block (the endpoint's FIFO) */
#define SETUP_ARM ((3u << 29) | (1u << 19) | 64u)   /* three setups back to back, or one 64-byte packet */

struct usbdev_state {
    uint8_t setup[8];
    uint16_t count;
    uint8_t phase, config;
    uint8_t more_at, more_left;  /* rest of a descriptor longer than one packet */
    uint8_t alt, primed;         /* audio stream open; ring has been filled since it opened or ran dry */
    uint32_t write, read;        /* ring counters, frames: the tap moves write, the interrupt moves read */
    uint32_t runs_dry;           /* times the ring ran dry while streaming */
    uint32_t irqs, sent, missed; /* interrupt entries, packets the host took, frames that went by without one */
    uint32_t poke_at;            /* debug: where the next poke writes */
    uint8_t mq_w, mq_r;          /* MIDI from the computer: the interrupt writes, the poll reads */
    uint8_t last_transport;      /* the last Start / Continue / Stop sent to the computer */
};
#define MQ_N 32u
#define MQ ((volatile uint32_t *)0x38800908u)                /* USB-MIDI events as they came off the wire */

#define S ((volatile struct usbdev_state *)0x38800680u)
_Static_assert(0x38800680u + sizeof(struct usbdev_state) <= 0x388006f0u, "usbdev state runs into rotate.c's ACC at 0x388006f0");

enum { WAIT_BOOT, WAIT_RESET, WAIT_MODE, RUNNING, FAILED };

#ifdef USB_DIAG
/*
 * USB_DIAG=1 (2026-10-15): what the USB device side did, for a unit whose computer never sees it (Chupitnik's: M1 Mac,
 * data cable, compressor Off, "not even an unknown device"). cpu.c puts usbdev_diag_text() on TOOLS in place of the
 * load, so one photo says where it stops: the phase, how many bus resets the computer sent (0 = it never saw the
 * device: wiring or pull-up), whether it got configured, and how far the 48 MHz oscillator is off. That oscillator
 * is HSI48: stock picks it for both USB controllers (D2CCIP2R USBSEL = 3) and never turns the CRS on, so it runs on
 * its factory trim; a full-speed device has to be within 0.25 %. Measured once, read-only, never trimmed here.
 */
struct usbdiag {
    uint8_t resets, setups, measured, _r;
    int32_t hsi_err;             /* HSI48 cycles in 1 ms of the crystal clock, minus 48000; + = fast */
};
#define DIAG ((volatile struct usbdiag *)0x388006b0u)
_Static_assert(0x388006b0u + sizeof(struct usbdiag) <= 0x388006f0u, "usbdiag runs into rotate.c's ACC");
_Static_assert(0x38800680u + sizeof(struct usbdev_state) <= 0x388006b0u, "usbdev state runs into usbdiag");

#define CRS_CR       REG(0x40008400u)   /* ST's CRS_TypeDef: CR +0, CFGR +4, ISR +8, ICR +0xc (cmsis stm32h743xx.h) */
#define CRS_CFGR     REG(0x40008404u)
#define CRS_ISR      REG(0x40008408u)
#define CRS_ICR      REG(0x4000840cu)
#define CRS_CEN      (1u << 5)
#define CRS_AUTOTRIM (1u << 6)
#define CRS_SWSYNC   (1u << 7)
#define RCC_APB1HENR REG(0x580244ecu)   /* bit 1 CRSEN */
#define RCC_PLLCKSELR REG(0x58024428u)
#define RCC_PLL1DIVR REG(0x58024430u)
#define RCC_D1CFGR   REG(0x58024418u)
#define DWT_CYC      REG(0xe0001004u)
#define CYC_PER_MS   399360u            /* HSE 6.144 MHz / 3 x 390 / 2 - the test unit's PLL1, checked before use */

static int32_t hsi48_error(void)
{
    uint32_t sel = RCC_PLLCKSELR, div = RCC_PLL1DIVR;
    if ((sel & 3u) != 2u || ((sel >> 4) & 0x3fu) != 3u || (div & 0x1ffu) != 389u || ((div >> 9) & 0x7fu) != 1u ||
        ((RCC_D1CFGR >> 8) & 0xfu) >= 8u)
        return 0x7fffffff;              /* not the clock this was worked out for: no number rather than a wrong one */
    uint32_t had = RCC_APB1HENR & 2u, cfgr;
    RCC_APB1HENR |= 2u;
    (void)RCC_APB1HENR;
    CRS_CR &= ~(CRS_CEN | CRS_AUTOTRIM);
    cfgr = CRS_CFGR;
    CRS_CFGR = (cfgr & ~((3u << 28) | (0xffu << 16) | 0xffffu)) | (0xffu << 16) | 47999u;   /* SYNCSRC 0 (unwired pin), widest limit */
    CRS_ICR = 0xfu;
    CRS_CR |= CRS_CEN;
    uint32_t pm;
    __asm__ volatile("mrs %0, primask\n cpsid i" : "=r"(pm));
    CRS_CR |= CRS_SWSYNC;               /* the counter starts from RELOAD ... */
    uint32_t t0 = DWT_CYC;
    while (DWT_CYC - t0 < CYC_PER_MS)
        ;
    CRS_CR |= CRS_SWSYNC;               /* ... and what is left of it 1 ms of crystal later is the error */
    __asm__ volatile("msr primask, %0" : : "r"(pm));
    for (volatile int i = 0; i < 64; i++)
        ;
    uint32_t isr = CRS_ISR;
    CRS_CR &= ~CRS_CEN;
    CRS_CFGR = cfgr;
    if (!had)
        RCC_APB1HENR &= ~2u;
    if (isr & ((1u << 8) | (1u << 9) | (1u << 10)))     /* SYNCERR / SYNCMISS / TRIMOVF */
        return 0x7fffffff;
    int32_t cap = (int32_t)(isr >> 16);
    return (isr & (1u << 15)) ? -cap : cap;              /* FEDIR 1: counting down still, the oscillator is slow */
}

static char *put_dec(char *p, unsigned v)
{
    char t[10];
    int n = 0;
    do t[n++] = (char)('0' + v % 10u); while ((v /= 10u) && n < 10);
    while (n)
        *p++ = t[--n];
    return p;
}

/* "U3r2c1+0.12%" (at most 14 + NUL, cpu.c's buffer is 16 with its "!"): phase, bus resets (9 = 9 or more), configured, oscillator error in hundredths of a percent. */
char *usbdev_diag_text(char *p)
{
    bkp_enable();
    *p++ = 'U';
    *p++ = (char)('0' + (S->phase <= FAILED ? S->phase : 9));
    *p++ = 'r';
    *p++ = (char)('0' + (DIAG->resets > 9 ? 9 : DIAG->resets));
    *p++ = 'c';
    *p++ = S->config ? '1' : '0';
    if (!DIAG->measured) {
        *p++ = '-';
        *p++ = '-';
    } else if (DIAG->hsi_err == 0x7fffffff) {
        *p++ = '?';
    } else {
        int32_t e = DIAG->hsi_err;                           /* counts of 48000: 4.8 counts = 0.01 % */
        unsigned h = (unsigned)((e < 0 ? -e : e) * 5 + 12) / 24u;
        *p++ = e < 0 ? '-' : '+';
        p = put_dec(p, h / 100u);
        *p++ = '.';
        *p++ = (char)('0' + h / 10u % 10u);
        *p++ = (char)('0' + h % 10u);
        *p++ = '%';
    }
    *p = 0;
    return p;
}
#endif
#define BOOT_BLOCKS 400          /* ~2 s of audio blocks after the host controller's clock is seen running */
#define MODE_BLOCKS 10           /* the core wants 25 ms after a mode change */

static const uint8_t DEVICE[18] = {
    18, 1, 0x00, 0x02, 0, 0, 0, 64,
    0x09, 0x12, 0x03, 0x00,      /* 1209:0003, a pid.codes test id (0002 was the MIDI-only build: hosts cache descriptors) */
    0x00, 0x01, 1, 2, 0, 1,
};
/* USB Audio 1.0 + MIDI: audio control, audio streaming (alt 1 = the 6-channel stream), MIDI streaming. */
static const uint8_t CONFIG[175] = {
    9, 2, 175, 0, 3, 1, 0, 0x80, 250,
    9, 4, 0, 0, 0, 1, 1, 0, 0,
    10, 0x24, 1, 0x00, 0x01, 31, 0, 2, 1, 2,     /* control header: streaming interfaces 1 and 2 */
    12, 0x24, 2, 1, 0x03, 0x06, 0, CHANNELS, 0, 0, 0, 0,     /* terminal 1: line connector, 6 channels */
    9, 0x24, 3, 2, 0x01, 0x01, 0, 1, 0,          /* terminal 2: USB streaming, fed by 1 */
    9, 4, 1, 0, 0, 1, 2, 0, 0,                   /* audio streaming, alt 0: closed */
    9, 4, 1, 1, 1, 1, 2, 0, 0,                   /* alt 1: one endpoint */
    7, 0x24, 1, 2, 1, 1, 0,                      /* from terminal 2, PCM */
    11, 0x24, 2, 1, CHANNELS, 3, 24, 1, 0x80, 0xbb, 0x00,    /* 3-byte samples, 24 bits, 48000 only */
    9, 5, 0x82, 0x05, 0x72, 0x03, 1, 0, 0,       /* isochronous IN, asynchronous, up to 882 bytes every frame */
    7, 0x25, 1, 0, 0, 0, 0,
    9, 4, 2, 0, 2, 1, 3, 0, 0,                   /* MIDI streaming */
    7, 0x24, 1, 0x00, 0x01, 65, 0,
    6, 0x24, 2, 1, 1, 0,                         /* jack 1: in, embedded */
    6, 0x24, 2, 2, 2, 0,                         /* jack 2: in, external */
    9, 0x24, 3, 1, 3, 1, 2, 1, 0,                /* jack 3: out, embedded, fed by 2 */
    9, 0x24, 3, 2, 4, 1, 1, 1, 0,                /* jack 4: out, external, fed by 1 */
    9, 5, 0x01, 2, 64, 0, 0, 0, 0,
    5, 0x25, 1, 1, 1,
    9, 5, 0x81, 2, 64, 0, 0, 0, 0,
    5, 0x25, 1, 1, 3,
};
static const char MAKER[] = "blackbox-mod";
static const char PRODUCT[] = "Blackbox";

static void send(const uint8_t *p, unsigned len)
{
    DIEPTSIZ0 = (1u << 19) | len;
    DIEPCTL0 |= EPENA | CNAK;
    for (unsigned i = 0; i < len; i += 4) {
        uint32_t w = 0;
        for (unsigned k = 0; k < 4 && i + k < len; k++)
            w |= (uint32_t)p[i + k] << (8 * k);
        FIFO0 = w;
    }
}

static void flush(uint32_t bits)
{
    GRSTCTL = bits;
    for (int i = 0; i < 2000 && (GRSTCTL & bits & (RXFFLSH | (1u << 5))); i++)
        ;
}

static int32_t *ring(void)
{
    uint8_t *block = master_block();
    return block ? (int32_t *)(block + RING_OFFSET) : 0;
}

/*
 * Load endpoint 2 with the packet for the next USB frame. Interrupt context (and once from the task, interrupts held
 * off, when the stream opens). Integer only: the interrupt must not touch the FPU.
 */
static void audio_load(void)
{
    const int32_t *base = ring();
    uint32_t read = S->read, fill = S->write - read, frames = 48;
    if (fill > RING)                                         /* the tap lapped us: start again */
        fill = 0;
    if (!S->primed && fill >= PRIME)
        S->primed = 1;
    if (S->primed && fill < 49u) {
        S->primed = 0;
        S->runs_dry++;
    }
    int live = base && S->primed;
    if (live)
        frames = fill > HIGH ? 49u : fill < LOW ? 47u : 48u;
    else
        S->read = S->write - (fill < PRIME ? fill : PRIME);  /* while silent, never fall more than PRIME behind */
    DIEPTSIZ2 = (1u << 29) | (1u << 19) | (frames * CHANNELS * 3u);
    DIEPCTL2 = DIEPCTL2 | EPENA | CNAK | (((DSTS >> 8) + 1u) & 1u ? SODDFRM : SEVNFRM);
    uint32_t left = frames * CHANNELS, at = (read % RING) * CHANNELS;
    while (left) {                                           /* four 3-byte samples to three words */
        uint32_t v[4], n = left < 4u ? left : 4u;
        for (uint32_t k = 0; k < 4u; k++) {
            v[k] = 0;
            if (k >= n)
                continue;
            if (live)
                v[k] = (uint32_t)base[at] & 0xffffffu;
            if (++at == RING * CHANNELS)
                at = 0;
        }
        FIFO2 = v[0] | v[1] << 24;
        FIFO2 = v[1] >> 8 | v[2] << 16;
        if (n > 2u)
            FIFO2 = v[2] >> 16 | v[3] << 8;
        left -= n;
    }
    if (live)
        S->read = read + frames;
}

/* Drop whatever endpoint 2 holds. */
static void audio_drop(void)
{
    if (DIEPCTL2 & EPENA) {
        DIEPCTL2 |= EPDIS | SNAK;
        for (int i = 0; i < 2000 && !(DIEPINT2 & EPDISD); i++)
            ;
    }
    DIEPINT2 = DIEPINT2;
    flush(TXFFLSH_2);
}

/* Vector 77 (OTG_HS), unused by stock. Only endpoint 2 and the "a frame went by without our packet" flag. */
static void out_arm(void)
{
    DOEPTSIZ1 = (1u << 19) | 64u;
    DOEPCTL1 |= EPENA | CNAK;
}

/* Empty the receive FIFO. Interrupt context. */
static void receive(void)
{
    for (int guard = 0; guard < 8 && (GINTSTS & RXFLVL); guard++) {
        uint32_t st = GRXSTSP, bytes = (st >> 4) & 0x7ffu, kind = (st >> 17) & 0xfu, ep = st & 0xfu;
        for (uint32_t i = 0; i < bytes; i += 4) {
            uint32_t w = FIFO0;
            if (kind == 6 && i < 8)                          /* a setup packet's eight bytes, for the poll */
                for (unsigned k = 0; k < 4; k++)
                    S->setup[i + k] = (uint8_t)(w >> (8 * k));
            if (kind != 2 || ep != 1 || !(w & 0x8u) || (uint8_t)(S->mq_w - S->mq_r) >= MQ_N)
                continue;                                    /* MIDI: only what stock's parser knows, while there is room */
            MQ[S->mq_w % MQ_N] = w;
            S->mq_w++;
        }
        if (kind == 3 && ep == 1 && (uint8_t)(S->mq_w - S->mq_r) <= MQ_N - 16u)
            out_arm();                                       /* room for another packet: take it now */
    }
}

void usbaud_isr(void)
{
    uint32_t ints = GINTSTS & GINTMSK;
    S->irqs++;
    if (ints & RXFLVL)
        receive();
    if (ints & IISOIXFR) {                                   /* armed for the wrong frame, or the host skipped one */
        GINTSTS = IISOIXFR;
        S->missed++;
        audio_drop();
        if (S->alt)
            audio_load();
        return;
    }
    if (ints & IEPINT) {
        uint32_t ep = DIEPINT2;
        DIEPINT2 = ep;
        if (ep & XFRC)
            S->sent++;
        if ((ep & XFRC) && S->alt)
            audio_load();
    }
}

static void audio_open(int on)
{
    GAHBCFG &= ~1u;                                          /* our interrupt off while the task changes endpoint 2 */
    audio_drop();
    S->alt = (uint8_t)on;
    S->primed = 0;
    if (on && ring()) {
        if (!(DIEPCTL2 & USBAEP))
            DIEPCTL2 = ISO_882;
        S->read = S->write;
        DIEPMSK = XFRC;
        DAINTMSK = 1u << 2;
        GINTMSK = RXFLVL | IEPINT | IISOIXFR;
        audio_load();
    } else {
        S->alt = 0;
        GINTMSK = RXFLVL;
        DIEPCTL2 &= ~USBAEP;
    }
    GAHBCFG |= 1u;
}

/* One bus's block into its column of the ring, as 24-bit. */
static void ring_put(const float *p, int frames, uint32_t column, int last)
{
    int32_t *base = ring();
    if (!(RCC_AHB1ENR & OTGHSEN) || S->phase != RUNNING || !S->alt || !base)
        return;
    uint32_t write = S->write;
    for (int i = 0; i < frames; i++) {
        float x = p[i] * 8388608.0f;
        int32_t v = x > 8388607.0f ? 8388607 : x < -8388608.0f ? -8388608 : (int32_t)x;
        base[((write + (uint32_t)i) % RING) * CHANNELS + column] = v;
    }
    if (last)                                                /* the block's last column: the frames are complete */
        S->write = write + (uint32_t)frames;
}

/*
 * The block function's last step turns four stereo buses into converter words, left side then right side each time
 * (the right side's words sit 8 bytes further in): FUN_0806002c(a, b, c) for the first converter stream, then
 * FUN_0805feb4(d) for the second. From the 3.1.M recordings: a = the HEADPHONE mix (every output summed: it measured
 * as 0.5 c + 0.46 b + a remainder), c = Out 1 (where pads go by default). From the 3.1.O recording (kick on Out 1,
 * hi-hat on Out 2): the hat came in on bus d, so d = Out 2 and b = Out 3. The ring takes c, d, b = USB 1-2, 3-4, 5-6
 * = Out 1, 2, 3, and leaves the headphone mix out.
 */
void usbaud_tap(const float *a, const float *b, const float *c, int frames, uint32_t *dst, int stride)
{
    uint32_t right = ((uint32_t)dst >> 3) & 1u;
    fw_to_dac(a, b, c, frames, dst, stride);
    ring_put(c, frames, 0u + right, 0);
    ring_put(b, frames, 4u + right, 0);
}

typedef void (*to_dac1_fn)(const float *src, int frames, uint32_t *dst, int zero, int stride);
#define fw_to_dac1 ((to_dac1_fn)(0x0805feb4u | 1u))

void usbaud_tap1(const float *src, int frames, uint32_t *dst, int zero, int stride)
{
    fw_to_dac1(src, frames, dst, zero, stride);
    uint32_t right = ((uint32_t)dst >> 3) & 1u;
    ring_put(src, frames, 2u + right, (int)right);           /* stock's last conversion of the block */
}

#ifndef PUBLIC_BUILD
/*
 * DEBUG peek and poke, bounded to whole memory regions.
 *
 * Why: a read with nothing behind it bus-faults the chip, and the fault restarts the unit. A 64-byte peek at
 * 0x38800fd8 read on into 0x38801000, one word past the end of backup SRAM, and did exactly that. So a peek reads
 * aligned words inside one of the ranges below and stops at that range's end (a shorter reply, never a word past it);
 * a peek that starts outside every range, or unaligned, is stalled. A poke writes one aligned word, and only in the
 * ranges from MEM_RAMS on: the RAMs and SDRAM, never flash, never a peripheral register.
 *
 * What a peek may read, in this order (each RANGE(first byte, one past the last byte), both multiples of 4):
 *   peek only:  the LTDC's registers (the screen's layers; a read changes none of them), RCC_RSR (the reset cause
 *               fault.c records), flash (both banks)
 *   peek, poke: DTCM, AXI SRAM, SRAM1-3, SRAM4, backup SRAM, SDRAM
 *
 * To widen it: add the block as one more RANGE in the "peek only" group, before flash, and add 1 to MEM_RAMS (it is
 * the index of the first range a poke may write, so it must stay on DTCM: a poke must never reach a register). One
 * range per block, never across a gap in the memory map: the gap faults like any other address with nothing behind
 * it. Check that the block's clock is on (its RCC enable bit), or a read does not show its state. Then add a check
 * to test_usbdev.py for the new range's last word and the word past it.
 * Safe to read: configuration and status registers that a read leaves as they were: RCC, GPIO, the LTDC, timers,
 * DMA stream set-up, the USB core's control, status and interrupt registers (GINTSTS, DIEPCTLx, DOEPCTLx, ...).
 * NOT safe: anything a read changes. The USB core's GRXSTSP (+0x020) pops the receive status queue and its FIFO
 * windows (+0x1000 on) pop endpoint data: usbdev's own interrupt then loses a packet, so never list the whole USB core.
 * The data registers of SAI (the audio: a read pops a sample), SPI / I2S and USART (a read takes the data out of
 * their receive FIFO), the SDMMC FIFO (card data), and any status register a read clears (read-to-clear). Read those
 * from code on the unit, never from a peek.
 * Each range is kept as its start and the offset of its last word (one subtract and one compare a range).
 */
#define RANGE(lo, hi) {lo, (hi) - (lo) - 4u}
static const uint32_t MEM[][2] = {
    RANGE(0x50001000u, 0x50001148u),     /* LTDC registers                 peek only */
    RANGE(0x580244d0u, 0x580244d4u),     /* RCC_RSR                        peek only */
    RANGE(0x08000000u, 0x08200000u),     /* flash, banks 1 and 2           peek only */
    RANGE(0x20000000u, 0x20020000u),     /* DTCM                           peek, poke (MEM_RAMS) */
    RANGE(0x24000000u, 0x24080000u),     /* AXI SRAM                       peek, poke */
    RANGE(0x30000000u, 0x30048000u),     /* SRAM1-3                        peek, poke */
    RANGE(0x38000000u, 0x38010000u),     /* SRAM4                          peek, poke */
    RANGE(0x38800000u, 0x38801000u),     /* backup SRAM                    peek, poke */
    RANGE(0xc0000000u, 0xc4000000u)};    /* SDRAM                          peek, poke */
#define MEM_RAMS   3             /* the index of the first range a poke may write (DTCM): the peek-only ranges are above */

static int inside(uint32_t a, unsigned from)
{
    if (a & 3)
        return 0;
    for (unsigned i = from; i < sizeof MEM / sizeof MEM[0]; i++)
        if (a - MEM[i][0] <= MEM[i][1])          /* below the start, the difference wraps past every offset here */
            return 1;
    return 0;
}
#endif

static void request(void)
{
    uint8_t buf[64];
    unsigned type = S->setup[0], req = S->setup[1], lo = S->setup[2], hi = S->setup[3];   /* wValue */
    unsigned want = S->setup[6] | (unsigned)S->setup[7] << 8, len = 0, ok = 0, data = 1;
    const uint8_t *from = 0;

    S->more_left = 0;
#ifndef PUBLIC_BUILD
    /* A reply the computer gave up waiting for (its timeout) can still be queued in endpoint 0's FIFO: this request's
       reply would go in behind it, and every reply after that would be the previous request's. A setup starts afresh.
       Dev builds only: it was seen with the peek, a vendor IN request, and a release build serves no vendor IN
       request (it stalls them), so it is not needed there today. A standard request a host abandons could in theory
       leave the same stale reply; if that is ever seen on a release build, move this block out of #ifndef
       PUBLIC_BUILD. */
    if (DIEPCTL0 & EPENA)
        DIEPCTL0 |= EPDIS | SNAK;
    flush(TXFFLSH_0);
#endif
    if (type == 0x80 && req == 6) {                          /* GET_DESCRIPTOR */
        const char *text = 0;
        if (hi == 1)
            from = DEVICE;
        else if (hi == 2)
            from = CONFIG;
        else if (hi == 3 && lo == 1)
            text = MAKER;
        else if (hi == 3 && lo == 2)
            text = PRODUCT;
        if (from) {
            len = from == DEVICE ? sizeof DEVICE : sizeof CONFIG;
            ok = 1;
        } else if (text) {
            for (len = 2; *text; text++) {
                buf[len++] = (uint8_t)*text;
                buf[len++] = 0;
            }
            ok = 1;
        } else if (hi == 3 && lo == 0) {
            buf[2] = 0x09;
            buf[3] = 0x04;
            len = 4;
            ok = 1;
        }
        if (hi == 3 && ok) {
            buf[0] = (uint8_t)len;
            buf[1] = 3;
        }
#ifndef PUBLIC_BUILD                                         /* not in a public build: see release.h */
    } else if (type == 0xc0 && req == 0x50) {                /* DEBUG peek: up to 64 bytes at wIndex:wValue, as words */
        uint32_t a = lo | hi << 8 | (uint32_t)S->setup[4] << 16 | (uint32_t)S->setup[5] << 24;
        for (len = 0; len < want && len < 64 && inside(a + len, 0); len += 4) {   /* stops at its memory's end */
            uint32_t w = *(const volatile uint32_t *)(a + len);   /* one word read, as the registers want */
            __builtin_memcpy(buf + len, &w, 4);                   /* its bytes in order, low first: one store */
        }
        ok = len > 0;                                        /* nothing readable there: stalled */
    } else if (type == 0x40 && (req == 0x51 || req == 0x52)) {   /* DEBUG poke: 0x51 sets the address, 0x52 writes a word */
        uint32_t v = lo | hi << 8 | (uint32_t)S->setup[4] << 16 | (uint32_t)S->setup[5] << 24;
        if (req == 0x51)
            S->poke_at = v;
        else if ((ok = inside(S->poke_at, MEM_RAMS)))
            *(volatile uint32_t *)S->poke_at = v;
        ok |= req == 0x51;                                   /* a poke outside the RAMs: stalled, nothing written */
        data = 0;
#endif
    } else if (type == 0x00 && req == 5) {                   /* SET_ADDRESS: the core applies it after the status */
        DCFG = (DCFG & ~(0x7fu << 4)) | ((lo & 0x7fu) << 4);
        ok = 1;
        data = 0;
    } else if (type == 0x00 && req == 9) {                   /* SET_CONFIGURATION */
        S->config = (uint8_t)lo;
        audio_open(0);
        DIEPCTL1 = DIEPCTL1 & USBAEP ? DIEPCTL1 | SD0PID : BULK_64 | TXFIFO_1;
        DOEPCTL1 = DOEPCTL1 & USBAEP ? DOEPCTL1 | SD0PID : BULK_64;
        ok = 1;
        data = 0;
    } else if ((type == 0x01 && req == 11) || (type == 0x02 && req == 1)) {   /* SET_INTERFACE, clear an endpoint halt */
        if (type == 0x01 && S->setup[4] == 1)                /* the audio stream opens (alt 1) or closes */
            audio_open(lo == 1);
        ok = 1;
        data = 0;
    } else if (type == 0x81 && req == 10) {                  /* GET_INTERFACE */
        buf[0] = S->setup[4] == 1 ? S->alt : 0;
        len = 1;
        ok = 1;
    } else if (type == 0x80 && req == 8) {                   /* GET_CONFIGURATION */
        buf[0] = S->config;
        len = 1;
        ok = 1;
    } else if ((type & 0xe0) == 0x80 && req == 0) {            /* GET_STATUS */
        buf[0] = buf[1] = 0;
        len = 2;
        ok = 1;
    }

    if (!(DOEPCTL0 & EPENA))
        DOEPTSIZ0 = SETUP_ARM;
    if (!ok) {
        DIEPCTL0 |= STALL;
        DOEPCTL0 |= STALL;
        return;
    }
    if (data)
        DOEPCTL0 |= EPENA | CNAK;                            /* the host's empty status packet after our data */
    if (len > want)
        len = want;
    if (from && len > 64) {                                  /* the rest follows, a packet per block (serve) */
        S->more_at = 64;
        S->more_left = (uint8_t)(len - 64);
        len = 64;
    }
    send(from ? from : buf, len);
}

static void core_setup(void)
{
    GCCFG &= ~VBDEN;
    GOTGCTL |= BVALO;
    PCGCCTL = 0;
    DCFG = (DCFG & ~3u) | 3u;                                /* full speed */
    flush(TXFFLSH_ALL);
    flush(RXFFLSH);
    GINTMSK = RXFLVL;
    GINTSTS = 0xbfffffffu;
    GRXFSIZ = 0x80;
    DIEPTXF0 = (0x40u << 16) | 0x80u;
    DIEPTXF1 = (0x40u << 16) | 0xc0u;
    DIEPTXF2 = (0x100u << 16) | 0x100u;                      /* 1024 bytes: one audio packet is at most 882 */
    S->alt = 0;
    S->mq_w = S->mq_r = S->last_transport = 0;
    NVIC_IPR77 = 0x70;                                       /* the level stock gives its own USB interrupt */
    NVIC_ISER2 = IRQ_BIT;
    GUSBCFG = (GUSBCFG & ~(0xfu << 10)) | TRDT_6;
    DOEPTSIZ0 = SETUP_ARM;
    DCTL &= ~SDIS;                                           /* D+ pull-up on: "a device is here" */
    GAHBCFG |= 1u;                                           /* the interrupt: only the receive FIFO for now */
}

static void serve(void)
{
    uint32_t ints = GINTSTS;
    if (ints & USBRST) {
        GINTSTS = USBRST;
#ifdef USB_DIAG
        if (DIAG->resets < 255)
            DIAG->resets++;
#endif
        DCFG &= ~(0x7fu << 4);
        DOEPTSIZ0 = SETUP_ARM;
        S->config = 0;
        audio_open(0);
        if (DIEPCTL1 & EPENA)
            DIEPCTL1 |= EPDIS | SNAK;
        flush(TXFFLSH_1);
        DOEPCTL1 |= SNAK;
    }
    if (ints & ENUMDNE) {
        GINTSTS = ENUMDNE;
        DIEPCTL0 &= ~3u;                                     /* 64-byte packets on endpoint 0 */
        DCTL |= CGINAK;
    }
    uint8_t upto = S->mq_w;                                  /* what has arrived so far; later arrivals wait a block */
    while (S->mq_r != upto) {                                /* MIDI from the computer, to stock's USB event parser */
        uint8_t events[68];
        unsigned n = 0;
        while (S->mq_r != upto && n < 64) {
            uint32_t w = MQ[S->mq_r % MQ_N];
            for (unsigned k = 0; k < 4; k++)
                events[n++] = (uint8_t)(w >> (8 * k));
            S->mq_r++;
        }
        events[n] = 0;                                       /* stock looks at the next event's first byte */
        fw_midi_usb_in(MIDI_MANAGER, events, n);
    }
    uint32_t out = DOEPINT0, in = DIEPINT0;
    DOEPINT0 = out;
    DIEPINT0 = in;
    DOEPINT1 = DOEPINT1;
    DIEPINT1 = DIEPINT1;
    if (out & STUP) {
#ifdef USB_DIAG
        if (DIAG->setups < 255)
            DIAG->setups++;
#endif
        request();
    } else if ((in & XFRC) && S->more_left) {                /* next packet of a long descriptor */
        unsigned n = S->more_left > 64 ? 64 : S->more_left;
        send(CONFIG + S->more_at, n);
        S->more_at = (uint8_t)(S->more_at + n);
        S->more_left = (uint8_t)(S->more_left - n);
    }
    if (S->config) {                                         /* the endpoint for the computer's MIDI, if the interrupt left it idle */
        NVIC_ICER2 = IRQ_BIT;
        uint32_t c = DOEPCTL1;
        if (!(c & EPENA))
            out_arm();
        else if (c & NAKSTS)
            DOEPCTL1 = c | CNAK;
        NVIC_ISER2 = IRQ_BIT;
    }
}

/*
 * The USB-MIDI event code for a message's status byte; 0 = not sent. *last is the last Start / Continue / Stop sent:
 * a repeat of it is not sent again.
 */
static unsigned event_code(unsigned status, uint8_t *last)
{
    if (status == 0xfa || status == 0xfb || status == 0xfc) {
        if (*last == status)
            return 0;
        *last = (uint8_t)status;
    }
    if (status < 0x80)
        return 0;
    if (status < 0xf0)
        return status >> 4;
    if (status >= 0xf8)
        return 0xf;
    if (status == 0xf2)
        return 3;
    if (status == 0xf1 || status == 0xf3)
        return 2;
    return 0;
}

/*
 * Replaces the call that packs the "to USB" queue for the host jack (bl FUN_08044896 @0x08044b08, audio task, once
 * per block). The queue's messages go to the computer first; then stock packs and consumes them as before. If the
 * computer has not taken the previous block's packet yet, this block's messages are not sent to it.
 */
int usbdev_midi_out(void *manager, uint8_t *queue, uint8_t *out, unsigned max, unsigned *len)
{
    if ((RCC_AHB1ENR & OTGHSEN) && S->phase == RUNNING && S->config && !(DIEPCTL1 & EPENA)) {
        uint32_t read = *(uint32_t *)(queue + Q_READ), waiting = *(uint32_t *)(queue + Q_WRITE) - read, events = 0;
        uint8_t last = S->last_transport, counted = last;
        if (waiting > OUT_EVENTS)
            waiting = OUT_EVENTS;
        for (uint32_t i = 0; i < waiting; i++)
            events += event_code(queue[((read + i) & 0xffu) * 5], &counted) != 0;
        S->last_transport = counted;
        if (events) {
            DIEPTSIZ1 = (((events + 15u) / 16u) << 19) | (events * 4u);
            DIEPCTL1 |= EPENA | CNAK;
            for (uint32_t i = 0; i < waiting; i++) {
                const uint8_t *m = queue + ((read + i) & 0xffu) * 5;
                uint32_t w = event_code(m[0], &last);
                if (!w)
                    continue;
                for (unsigned k = 0; k < 3 && k < m[4]; k++)
                    w |= (uint32_t)m[k] << (8 * (k + 1));
                FIFO1 = w;
            }
        }
    }
    return fw_midi_pack(manager, queue, out, max, len);
}

/* Once per audio block, from cpu_wait. */
void usbdev_poll(void)
{
    bkp_enable();
    if (!(RCC_AHB1ENR & OTGHSEN)) {                          /* first calls after a reset: the clock is still off */
        if (S->phase != WAIT_BOOT) {
            S->phase = WAIT_BOOT;
            S->count = 0;
#ifdef USB_DIAG
            DIAG->measured = 0;                              /* backup SRAM: last boot's numbers are not this one's */
            DIAG->resets = 0;
#endif
        }
        if (!(RCC_AHB1ENR & OTGFSEN) || !(RCC_D2CCIP2R & USBSEL))
            return;                                          /* stock has not started its own USB yet */
        if (++S->count < BOOT_BLOCKS)
            return;
#ifdef USB_DIAG
        DIAG->resets = 0;
        DIAG->setups = 0;
        DIAG->hsi_err = hsi48_error();
        DIAG->measured = 1;
#endif
        PWR_CR3 |= USB33DEN;
        RCC_AHB1LPENR &= ~OTGHSULPIEN;                       /* no external transceiver: its clock must not gate ours */
        RCC_AHB1ENR |= OTGHSEN;
        (void)RCC_AHB1ENR;
        volatile uint32_t *b = (volatile uint32_t *)GPIOB;   /* PB14, PB15: alternate function 12, fastest, no pull */
        b[GPIO_AFRH / 4] = (b[GPIO_AFRH / 4] & 0x00ffffffu) | 0xcc000000u;
        b[GPIO_OSPEEDR / 4] |= 0xf0000000u;
        b[GPIO_PUPDR / 4] &= 0x0fffffffu;
        b[GPIO_MODER / 4] = (b[GPIO_MODER / 4] & 0x0fffffffu) | 0xa0000000u;
        GUSBCFG |= PHYSEL;
        DCTL |= SDIS;
        GRSTCTL |= CSRST;
        S->count = 0;
        S->phase = WAIT_RESET;
        return;
    }
    switch (S->phase) {
    case WAIT_RESET:
        if (GRSTCTL & CSRST) {
            if (++S->count > 200)
                S->phase = FAILED;                           /* the core never came out of reset: no 48 MHz clock */
            return;
        }
        GCCFG |= PWRDWN;
        GUSBCFG = (GUSBCFG & ~(1u << 29)) | FDMOD | PHYSEL;
        DCTL |= SDIS;
        S->count = 0;
        S->phase = WAIT_MODE;
        return;
    case WAIT_MODE:
        if (++S->count < MODE_BLOCKS)
            return;
        core_setup();
        S->config = 0;
        S->phase = RUNNING;
        return;
    case RUNNING:
        serve();
        return;
    default:
        return;
    }
}
