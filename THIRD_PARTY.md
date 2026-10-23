# Third-party work

The patch (source and the compiled bytes in `docs/blackbox-mod-*.json`) includes or derives from the following.
All of it is MIT-licensed, and these notices travel with every copy.

| Component | Copyright | License | Where |
|---|---|---|---|
| Munchi Delay ([charlesvestal/schwung-munchi-delay](https://github.com/charlesvestal/schwung-munchi-delay)) | © 2026 Charles Vestal | MIT | `src/munchi/` (`LICENSE`, `THIRD_PARTY.md` beside it) |
| CHOMPI TEMPO 1.0 firmware (granular delay, compressor, crossfades) | © CHOMPI Club | MIT | `src/munchi/tempo/` |
| `reverb.h`, `fx_engine.h` | © Émilie Gillet (Mutable Instruments) | MIT | `src/munchi/tempo/`, notices in the files |
| DaisySP `dsp.h` | © Electrosmith, Corp. | MIT | `src/munchi/daisysp/` |
| TAPESCAM tape / VHS emulation ([charlesvestal/schwung-tapescam](https://github.com/charlesvestal/schwung-tapescam)) | © 2025 Charles Vestal | MIT | `src/tapescam.c` (notice in the file), reference copy and `LICENSE` in `host/tapescam_ref/` |
| State-variable filter, after stmlib `dsp/filter.h` (`Svf`) | © 2014 Émilie Gillet | MIT | reimplemented in `src/filter.c` |

## Not included

**1010music's Blackbox firmware is not in this repository**, in whole or in part, in source, history, or releases.
The patch file stores only the bytes this project adds or changes; the stock image is identified by SHA-256 and
supplied by you.

## Trademarks

"1010music" and "Blackbox" are trademarks of 1010music LLC. CHOMPI is a trademark of CHOMPI Club. SP-1200, SP-12,
S950, MPC60 and Elektron are trademarks of their owners, named here only to describe what a mode is modelled on.
This project is independent and is not affiliated with, endorsed by, or supported by any of them.
