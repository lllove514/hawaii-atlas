# QA log

## Download and aggregate

- Stations kept: **764**
- Station-months aggregated: **238773**
- Year span: **1899–2026**
- Stations dropped: **39**

### Dropped stations (no coordinates / no data)

- `USC00510450` EAST HONOKANE 183.2 — no valid PRCP months
- `USC00511240` HAPUU 31 — no valid PRCP months
- `USC00514610` KILOHANA ALAKAI 1084 — no valid PRCP months
- `USC00514762` KOMAKAWAI 30 — no valid PRCP months
- `USC00516635` NAKALALUA 481 — no valid PRCP months
- `USC00517790` PAUKAHANA 1080 — no valid PRCP months
- `USC00518018` PEPEEKEO A F 140 — no valid PRCP months
- `USC00519130` WAIAKOALI CAMP 1082 — no valid PRCP months
- `USC00519460` WAILUA IKI 348 — no valid PRCP months
- `USR0000HHAI` HAKIOAWA HAWAII — no valid PRCP months
- `USR0000HHAK` HAKALAU HAWAII — no valid PRCP months
- `USR0000HHON` HONOKANAI'A HAWAII — no valid PRCP months
- `USR0000HKAH` KAHUKU TRAINING AREA HAWAII — no valid PRCP months
- `USR0000HKAN` KANELOA HAWAII — no valid PRCP months
- `USR0000HKAU` KAUPO GAP HAWAII — no valid PRCP months
- `USR0000HKEA` KEAMOKU LAVA FLOW HAWAII — no valid PRCP months
- `USR0000HKII` KII HAWAII — no valid PRCP months
- `USR0000HKLL` KEALIALALO HAWAII — no valid PRCP months
- `USR0000HKMO` KEAUMO HAWAII — no valid PRCP months
- `USR0000HLAN` LANAI 1 HAWAII — no valid PRCP months
- `USR0000HLUA` LUA MAKIKA HAWAII — no valid PRCP months
- `USR0000HMAH` MAKAHA RIDGE HAWAII — no valid PRCP months
- `USR0000HMAK` MAKAPULAPAI HAWAII — no valid PRCP months
- `USR0000HMAP` MAKUA VALLEY HAWAII — no valid PRCP months
- `USR0000HMAR` MAKUA RANGE HAWAII — no valid PRCP months
- `USR0000HMLK` MOLOKAI 1 HAWAII — no valid PRCP months
- `USR0000HMOL` MOLOAA DAIRY HAWAII — no valid PRCP months
- `USR0000HMRG` MAKUA RIDGE HAWAII — no valid PRCP months
- `USR0000HPAL` PALI 2 HAWAII — no valid PRCP months
- `USR0000HPTA` PTA EAST HAWAII — no valid PRCP months
- `USR0000HPTK` PTA KIPUKA ALALA HAWAII — no valid PRCP months
- `USR0000HPTP` PTA PORTABLE HAWAII — no valid PRCP months
- `USR0000HPTW` PTA WEST HAWAII — no valid PRCP months
- `USR0000HPUW` PUU WAAWAA HAWAII — no valid PRCP months
- `USR0000HSCH` SCHOFIELD EAST HAWAII — no valid PRCP months
- `USR0000HSCO` SCHOFIELD BARRACKS HAWAII — no valid PRCP months
- `USR0000HSFB` SCHOFIELD FIREBREAK HAWAII — no valid PRCP months
- `USR0000HWAI` WAIKOLU VALLEY HAWAII — no valid PRCP months
- `USR0000HWVA` WAIANAE VALLEY HAWAII — no valid PRCP months

## Interpolation

Grid: 275×170 cells at 0.020° (climatology). IDW power 2, per island.

### Windward vs leeward (annual climatology, mm)

| Island | Windward | mm | Leeward | mm | windward wetter |
|---|---|--:|---|--:|:--:|
| Hawaiʻi | Hilo (windward) | 3336 | Kona (leeward) | 933 | ✓ |
| Oʻahu | Kāneʻohe (windward) | 1575 | Kapolei (leeward) | 696 | ✓ |
| Kauaʻi | Wailua (windward) | 1636 | Waimea (leeward) | 703 | ✓ |

### Monthly climatology (island-mean over all land cells)

| Month | Stations | Mean mm | Min cell | Max cell | Low-conf |
|---|--:|--:|--:|--:|:--:|
| Jan | 481 | 162 | 11 | 840 |  |
| Feb | 472 | 146 | 9 | 577 |  |
| Mar | 483 | 189 | 7 | 686 |  |
| Apr | 481 | 163 | 11 | 816 |  |
| May | 486 | 121 | 4 | 584 |  |
| Jun | 486 | 94 | 1 | 523 |  |
| Jul | 486 | 122 | 4 | 680 |  |
| Aug | 480 | 134 | 3 | 612 |  |
| Sep | 478 | 109 | 2 | 480 |  |
| Oct | 477 | 127 | 4 | 621 |  |
| Nov | 466 | 171 | 6 | 780 |  |
| Dec | 476 | 181 | 11 | 701 |  |
