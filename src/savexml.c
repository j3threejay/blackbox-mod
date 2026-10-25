/*
 * The preset writer, streamed. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: Save, Save As and Pack all end in FUN_08096754, which builds the whole project as a tinyxml2 XMLDocument
 * (about 6.4x the size of the preset.xml it makes) from the SDRAM top-down heap, and only then prints it to the file
 * (FUN_08097148). A big project runs the heap into the permanent allocations; the allocator then spins at `b .`
 * (0x0808a37c) and stock's watchdog resets the unit ~10 s later, at "Saving: 95%" (tester report, 10-24).
 *
 * This writes the same file with no document at all: it walks the same data in the same order and prints each
 * element straight through stock's own XMLPrinter (the printer FUN_08097148 makes, FIL set, Print = f_write per
 * fragment), with the calls stock's printer would make while visiting the document:
 *   element open  = OpenElement FUN_0804b810 (compact 0), what XMLPrinter::VisitEnter calls
 *   attribute     = Print(" %s=\"", name), PrintString(value, 0), Print("\""), VisitEnter's loop, inlined there
 *   element close = CloseElement FUN_0804b30c (compact 0), what VisitExit runs
 * Values are formatted as tinyxml2 stores them (SetAttribute: "%d" / "%u", strings copied as they are), so the
 * bytes are stock's; test_savexml.py runs both writers on the same loaded project and compares the files.
 *
 * The one thing a document does that a stream does not: tinyxml2 adds an attribute with FindOrCreateAttribute, so
 * setting a name twice on one element keeps ONE attribute, where the name first appeared, with the value set last.
 * Only <params> can meet that (its names come from the settings store, which does not refuse a repeated id), and
 * params() below reproduces it.
 *
 * Heap: none. The printer lives on this stack (as it does in FUN_08097148); Print's 0x200 buffer is inside it.
 * Errors: as FUN_08097148. No FIL -> 0; f_open fails -> "Unable to open %s for writing" (an empty printf stub) and 0;
 * otherwise 1, whatever f_write said (Print never looks at it).
 * Watchdog: the disk task's stamp (FUN_080469c4, one store: stamp A = the supervisor's block counter) is refreshed at
 * every element, so a slow card cannot starve it while elements are still being written. A write that stops coming
 * back still trips it: the stamp only moves when the next element starts.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*print_fn)(void *prn, const char *fmt, ...);
typedef void (*pstring_fn)(void *prn, const char *s, int restricted);
typedef void (*open_el_fn)(void *prn, const char *name, int compact);
typedef void (*close_el_fn)(void *prn, int compact);
typedef void *(*printer_fn)(void *prn, void *fil, int compact, int depth);
typedef int (*f_open_fn)(void *fil, const char *path, int mode);
typedef int (*f_close_fn)(void *fil);
typedef void (*memset_fn)(void *dst, int c, uint32_t n);
typedef void (*free_fn)(void *p);
typedef void (*printf_fn)(const char *fmt, ...);
typedef const char *(*cstr_fn)(void *str);
typedef int (*empty_fn)(void *str);
typedef void (*stamp_fn)(void *wdg);
typedef const char *(*name_fn)(uint32_t code);
typedef int (*get_fn)(void *list, uint32_t i, void *out);
typedef uint32_t (*vfn)(void *obj);

#define fw_print        ((print_fn)FN(0x0804b1c4))     /* XMLPrinter::Print(fmt, ...) */
#define fw_print_string ((pstring_fn)FN(0x0804b6e8))   /* XMLPrinter::PrintString(p, restricted) */
#define fw_open_el      ((open_el_fn)FN(0x0804b810))   /* XMLPrinter::OpenElement(name, compact) */
#define fw_close_el     ((close_el_fn)FN(0x0804b30c))  /* XMLPrinter::CloseElement(compact) */
#define fw_printer      ((printer_fn)FN(0x0804b148))   /* XMLPrinter(FILE *, compact, depth) */
#define fw_f_open       ((f_open_fn)FN(0x08086534))
#define fw_f_close      ((f_close_fn)FN(0x08086d76))
#define fw_memset       ((memset_fn)FN(0x080c8d5e))
#define fw_free         ((free_fn)FN(0x08044470))      /* the SDRAM heap's free */
#define fw_printf       ((printf_fn)FN(0x08043de4))
#define fw_cstr         ((cstr_fn)FN(0x080460ba))      /* string object -> char * (terminates at [0xff]) */
#define fw_empty        ((empty_fn)FN(0x08046070))
#define fw_wdg_stamp    ((stamp_fn)FN(0x080469c4))
#define fw_param_name   ((name_fn)FN(0x0808e33c))      /* setting id -> xml name (the registry), 0 if none */
#define fw_src_name     ((name_fn)FN(0x0808e3d0))      /* modulation source code -> xml name */
#define fw_enum_name    ((name_fn)FN(0x0808e45c))      /* jack / output code -> xml name */
#define fw_mod_get      ((get_fn)FN(0x08094a30))       /* cell's modulation slot i -> 12-byte record */
#define fw_slice_get    ((get_fn)FN(0x08093c9e))       /* slice list i -> u32 */
#define fw_event_get    ((get_fn)FN(0x08063d08))       /* event list i -> 0x18-byte event */

#define FIL_PTR     (*(void *volatile *)0x24020084u)   /* the FIL FUN_08097148 and the reader share */
#define WDG_STAMPS  ((void *)0x2400a584u)
#define CELL_TYPES  ((const uint8_t *)0x2401fcacu)     /* 0x52 x {u8 code, pad, const char *name, ...}, 12 bytes */
#define N_TYPES     0x52
#define ENUM_F8     ((const uint8_t *)0x080eaf9cu)     /* value -> code, for the settings 0xf8 / 0xf9 */
#define ENUM_F9     ((const uint8_t *)0x080eaf80u)
#define PRINTER_VT  0x080cff78u
#define FA_WRITE_CREATE 10

/* stock's own strings, the very pointers its writer passes */
#define STR(a) ((const char *)(a))
#define FMT_S        STR(0x080cf3e8)   /* "%s" */
#define BOM          STR(0x080cffac)   /* EF BB BF */
#define FMT_DECL     STR(0x080cb084)   /* "<?%s?>" */
#define DECL         STR(0x080cafd8)   /* xml version="1.0" encoding="UTF-8" */
#define FMT_ATTR     STR(0x080cb0bc)   /* " %s=\"" */
#define FMT_QUOTE    STR(0x080cb0c0)   /* "\"" */
#define MSG_OPEN     STR(0x080cf220)   /* "Unable to open %s for writing" */
#define S_DOCUMENT   STR(0x080ceb50)
#define S_SESSION    STR(0x080cf1b4)
#define S_VERSION    STR(0x080cf1fc)
#define S_CELL       STR(0x080cf204)
#define S_ROW        STR(0x080cf11c)
#define S_COLUMN     STR(0x080cf120)
#define S_LAYER      STR(0x080cf128)
#define S_FILENAME   STR(0x080cf1cc)
#define S_SLICES     STR(0x080cf1f4)
#define S_SLICE      STR(0x080cb1cc)
#define S_POS        STR(0x080cbde0)
#define S_TYPE       STR(0x080cc1b0)
#define S_PARAMS     STR(0x080ceb68)
#define S_MODSOURCE  STR(0x080cbe1c)
#define S_DEST       STR(0x080cf0fc)
#define S_SRC        STR(0x080cc024)
#define S_MCHAN      STR(0x080cf104)
#define S_CCNUM      STR(0x080cf10c)
#define S_SLOT       STR(0x080cf114)
#define S_AMOUNT     STR(0x080cbf18)
#define S_SEQSUB     STR(0x080cf130)
#define S_NAME       STR(0x080cf1d0)
#define S_SEQUENCE   STR(0x080cf13c)
#define S_SEQEVENT   STR(0x080cf148)
#define S_STEP       STR(0x080cf154)
#define S_CHAN       STR(0x080cbe90)
#define S_NOTE       STR(0x080cb998)
#define S_STRTKS     STR(0x080cf15c)
#define S_PITCH      STR(0x080cbd24)
#define S_LENCOUNT   STR(0x080cf164)
#define S_LENTKS     STR(0x080cf170)
#define S_VELOCITY   STR(0x080cccdc)
#define S_COND       STR(0x080cf178)
#define S_SCENEITEM  STR(0x080cf180)
#define S_SILAYER    STR(0x080cf18c)
#define S_AUTO       STR(0x080cf194)
#define S_VALUE      STR(0x080cf19c)
#define S_VALUE2     STR(0x080cf1a4)
#define S_XYVALUE    STR(0x080cf1ac)
#define S_STEPLEN    STR(0x080cc04c)

/* the project data block (FUN_08096754's 4th argument) */
#define PAD(d, row, col)        ((d) + (col) * 0x30 + (row) * 0xf0)
#define SEQ(d, row, col, sub)   ((d) + 0x3c0 + (col) * 0xb0 + (row) * 0x370 + (sub) * 0x2c)
#define SECTION(d, i)           ((d) + 0x1180 + (i) * 0x30)
#define FX(d, i)                ((d) + 0x1780 + (i) * 0x18)
#define GLOBAL(d)               ((d) + 0x17f8)
#define ASSET_NAME(d, i)        ((d) + 0x1848 + (i) * 0x28)   /* its settings cell is 0x10 below */
#define N_ASSETS 0x240
#define PAD_NAME   0x18     /* string object */
#define PAD_SLICES 0x28     /* {u32 *, count} */
#define SEQ_EVENTS 0x18     /* event list */
#define STORE_ENTRIES 0x04  /* settings store: {u16 id, u32 value} x count, 8 bytes each */
#define STORE_COUNT   0x0a
#define TICKS_PER_STEP 960u

#define PRN_WORDS (0x2f4 / 4)                          /* sizeof(XMLPrinter) here: FUN_08097148's frame */

static void open_el(void *prn, const char *name)
{
    fw_wdg_stamp(WDG_STAMPS);
    fw_open_el(prn, name, 0);
}

static void close_el(void *prn)
{
    fw_close_el(prn, 0);
}

static void attr_str(void *prn, const char *name, const char *value)
{
    fw_print(prn, FMT_ATTR, name);
    fw_print_string(prn, value, 0);
    fw_print(prn, FMT_QUOTE);
}

/* XMLUtil::ToStr: "%d", or "%u" when is_unsigned */
static void attr_num(void *prn, const char *name, uint32_t v, int is_unsigned)
{
    char buf[12];
    char *p = buf + sizeof buf;
    int neg = !is_unsigned && (int32_t)v < 0;
    if (neg)
        v = 0u - v;
    *--p = 0;
    do {
        *--p = (char)('0' + v % 10u);
        v /= 10u;
    } while (v);
    if (neg)
        *--p = '-';
    attr_str(prn, name, p);
}

static void attr_int(void *prn, const char *name, int32_t v)
{
    attr_num(prn, name, (uint32_t)v, 0);
}

static void attr_uint(void *prn, const char *name, uint32_t v)
{
    attr_num(prn, name, v, 1);
}

static uint32_t vcall(void *obj, int slot)
{
    return ((vfn)(*(uint32_t **)obj)[slot])(obj);
}

static int same(const char *a, const char *b)
{
    if (a == b)
        return 1;
    while (*a && *a == *b)
        a++, b++;
    return *a == *b;
}

struct entry {
    const char *name;
    const char *text;   /* string value (settings 0xf8 / 0xf9), else 0 */
    int32_t value;
};

/* What FUN_08095328 sets for store entry i: 0 if it sets nothing. */
static int entry(const uint8_t *cell, int i, struct entry *e)
{
    const uint8_t *en = *(const uint8_t *const *)(cell + STORE_ENTRIES) + i * 8;
    uint32_t id = *(const uint16_t *)en;
    int32_t v = *(const int32_t *)(en + 4);
    e->name = fw_param_name(id);
    if (!e->name)
        return 0;
    e->text = 0;
    e->value = v;
    if (id == 0xf8 || id == 0xf9) {
        e->text = fw_enum_name((id == 0xf8 ? ENUM_F8 : ENUM_F9)[v]);
        if (!e->text)
            return 0;
    }
    return 1;
}

/* FUN_08095328: the cell's "type" attribute, then <params> with one attribute per setting in the store. */
static void params(void *prn, uint8_t *cell)
{
    uint32_t code = vcall(cell, 0);
    for (int i = 0; i < N_TYPES; i++) {
        const uint8_t *t = CELL_TYPES + i * 12;
        if (t[0] == code) {
            const char *name = *(const char *const *)(t + 4);
            if (name)
                attr_str(prn, S_TYPE, name);
            break;
        }
    }
    open_el(prn, S_PARAMS);
    /* the store as FUN_080947ec walks it: up to the count, and no further than the first id 0 */
    const uint8_t *en = *(const uint8_t *const *)(cell + STORE_ENTRIES);
    int n = 0, count = *(const uint16_t *)(cell + STORE_COUNT);
    while (n < count && *(const uint16_t *)(en + n * 8))
        n++;
    for (int i = 0; i < n; i++) {
        struct entry e, o;
        if (!entry(cell, i, &e))
            continue;
        /* FindOrCreateAttribute: a name already set on this element is not added again ... */
        int seen = 0;
        for (int j = 0; j < i && !seen; j++)
            seen = entry(cell, j, &o) && same(o.name, e.name);
        if (seen)
            continue;
        /* ... and the value it ends up with is the one set last */
        for (int j = i + 1; j < n; j++)
            if (entry(cell, j, &o) && same(o.name, e.name))
                e = o;
        if (e.text)
            attr_str(prn, e.name, e.text);
        else
            attr_int(prn, e.name, e.value);
    }
    close_el(prn);
}

/* FUN_08095440: one <modsource> per modulation slot record. */
static void modsources(void *prn, uint8_t *cell)
{
    struct {
        int32_t amount;
        uint16_t src, dest;
        int16_t slot;
        uint16_t pad;
    } m;
    for (uint32_t i = 0; fw_mod_get(cell, i, &m); i++) {
        open_el(prn, S_MODSOURCE);
        const char *s = fw_param_name(m.dest);
        if (s)
            attr_str(prn, S_DEST, s);
        if ((int16_t)m.src < 0) {
            s = fw_src_name(0x8000);
            if (s)
                attr_str(prn, S_SRC, s);
            attr_int(prn, S_MCHAN, (m.src & 0x7ff) >> 7);
            attr_int(prn, S_CCNUM, m.src & 0x7f);
        } else {
            s = fw_src_name(m.src);
            if (s)
                attr_str(prn, S_SRC, s);
        }
        attr_int(prn, S_SLOT, m.slot);
        attr_int(prn, S_AMOUNT, m.amount);
        close_el(prn);
    }
}

/* FUN_0809557c: a sequence cell's attributes, settings, modulation and events (the <cell> is open). */
static void sequence(void *prn, uint8_t *seq, int row, int column, int layer, int sub)
{
    attr_int(prn, S_ROW, row);
    attr_int(prn, S_COLUMN, column);
    attr_int(prn, S_LAYER, layer);
    attr_int(prn, S_SEQSUB, sub);
    const char *name = (const char *)vcall(seq, 2);
    if (name)
        attr_str(prn, S_NAME, name);
    params(prn, seq);
    modsources(prn, seq);
    open_el(prn, S_SEQUENCE);
    struct {
        uint8_t type, cond;
        uint16_t chan;
        uint32_t start, len, unused;
        uint16_t pitch, velocity;   /* note; also the low / high halves of value */
        uint16_t value2_lo, silayer;
    } ev;
    for (uint32_t i = 0; fw_event_get(seq + SEQ_EVENTS, i, &ev); i++) {
        int32_t value = ev.pitch | (int32_t)ev.velocity << 16;
        int32_t value2 = ev.value2_lo | (int32_t)ev.silayer << 16;
        open_el(prn, S_SEQEVENT);
        attr_int(prn, S_STEP, ev.start / TICKS_PER_STEP);
        if (ev.chan)
            attr_int(prn, S_CHAN, ev.chan);
        switch (ev.type) {
        case 1:
            attr_str(prn, S_TYPE, S_NOTE);
            attr_uint(prn, S_STRTKS, ev.start);
            attr_int(prn, S_PITCH, ev.pitch);
            attr_uint(prn, S_LENCOUNT, ev.len / TICKS_PER_STEP);
            attr_uint(prn, S_LENTKS, ev.len);
            if (ev.velocity)
                attr_int(prn, S_VELOCITY, ev.velocity);
            if (ev.cond)
                attr_int(prn, S_COND, ev.cond);
            break;
        case 2:
            attr_str(prn, S_TYPE, S_AUTO);
            attr_int(prn, S_VALUE, value);
            attr_int(prn, S_VALUE2, value2);
            if (ev.len >= TICKS_PER_STEP)
                attr_uint(prn, S_LENCOUNT, ev.len / TICKS_PER_STEP);
            break;
        case 3:
            attr_str(prn, S_TYPE, S_XYVALUE);
            attr_int(prn, S_VALUE, value);
            attr_int(prn, S_VALUE2, value2);
            break;
        case 4:
            attr_str(prn, S_TYPE, S_STEPLEN);
            attr_int(prn, S_VALUE, value);
            break;
        case 9:
            attr_str(prn, S_TYPE, S_SCENEITEM);
            attr_int(prn, S_SILAYER, ev.silayer);
            attr_int(prn, S_COND, ev.cond);
            break;
        }
        close_el(prn);
    }
    close_el(prn);
}

static void session(void *prn, uint8_t *d)
{
    open_el(prn, S_DOCUMENT);
    open_el(prn, S_SESSION);
    attr_int(prn, S_VERSION, 2);
    for (int col = 0; col < 5; col++)
        for (int row = 0; row < 4; row++) {
            uint8_t *pad = PAD(d, row, col);
            open_el(prn, S_CELL);
            attr_int(prn, S_ROW, row);
            attr_int(prn, S_COLUMN, col);
            attr_int(prn, S_LAYER, 0);
            attr_str(prn, S_FILENAME, fw_cstr(pad + PAD_NAME));
            params(prn, pad);
            modsources(prn, pad);
            open_el(prn, S_SLICES);
            uint32_t pos;
            for (uint32_t i = 0; fw_slice_get(pad + PAD_SLICES, i, &pos); i++) {
                open_el(prn, S_SLICE);
                attr_int(prn, S_POS, pos);
                close_el(prn);
            }
            close_el(prn);
            close_el(prn);
        }
    for (int col = 0; col < 5; col++)
        for (int row = 0; row < 4; row++)
            for (int sub = 0; sub < 4; sub++) {
                open_el(prn, S_CELL);
                sequence(prn, SEQ(d, row, col, sub), row, col, 1, sub);
                close_el(prn);
            }
    for (int i = 0; i < 32; i++) {
        open_el(prn, S_CELL);
        sequence(prn, SECTION(d, i), i, 0, 2, 0);
        close_el(prn);
    }
    for (int i = 0; i < 5; i++) {
        open_el(prn, S_CELL);
        attr_int(prn, S_ROW, i);
        attr_int(prn, S_LAYER, 3);
        params(prn, FX(d, i));
        modsources(prn, FX(d, i));
        close_el(prn);
    }
    for (int i = 0; i < N_ASSETS; i++) {
        uint8_t *name = ASSET_NAME(d, i);
        if (fw_empty(name))
            continue;
        open_el(prn, S_CELL);
        attr_int(prn, S_ROW, i);
        attr_str(prn, S_FILENAME, fw_cstr(name));
        params(prn, name - 0x10);
        close_el(prn);
    }
    open_el(prn, S_CELL);
    params(prn, GLOBAL(d));
    close_el(prn);
    close_el(prn);
    close_el(prn);
}

/* Called where stock calls FUN_08096754(path, buf, size, data); the same arguments, the same result. */
int savexml(const char *path, void *buf, uint32_t size, uint8_t *data)
{
    (void)buf;
    (void)size;
    void *fil = FIL_PTR;
    if (!fil)
        return 0;
    fw_memset(fil, 0, 0x58);
    if (fw_f_open(fil, path, FA_WRITE_CREATE)) {
        fw_printf(MSG_OPEN, path);
        return 0;
    }
    uint32_t prn[PRN_WORDS];
    fw_printer(prn, fil, 0, 0);
    /* XMLPrinter::VisitEnter(document): entities on (the document's flag), the BOM (the writer sets it) */
    ((uint8_t *)prn)[0x4c] = 1;
    fw_print(prn, FMT_S, BOM);
    /* Visit(declaration), the first node: nothing before it, so no newline */
    ((uint8_t *)prn)[0x3c] = 0;
    fw_print(prn, FMT_DECL, DECL);
    session(prn, data);
    fw_f_close(fil);
    /* ~XMLPrinter: its two arrays, if either outgrew its own storage */
    prn[0] = PRINTER_VT;
    if (prn[0xd4 / 4] != (uint32_t)&prn[0xd8 / 4])
        fw_free((void *)prn[0xd4 / 4]);
    if (prn[2] != (uint32_t)&prn[3])
        fw_free((void *)prn[2]);
    return 1;
}
