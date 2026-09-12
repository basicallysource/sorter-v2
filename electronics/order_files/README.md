# Order Files

Production and procurement files for two PCB assemblies:

- **Distribution Board V1.3** — 10 units, 130 × 120 mm, 2-layer
- **Adapter Board V0.1** — 50 units, 50 × 70 mm, 2-layer

Each subdirectory contains the files needed to place an order with a specific manufacturer:
Gerber ZIP archives, Bill of Materials (BOM), and Component Placement Lists (CPL) where
applicable. The files are formatted to match each manufacturer's upload requirements.

## Board revisions ordered

| Board | Revision | Schematic date | Gerber ZIPs |
|---|---|---|---|
| Adapter Board | **V1.0** | 2026-04-01 | `*/0_Adapter_Board_V1.0.zip` |
| Distribution Board | **V1.3** | 2026-06-01 | `*/1_Distribution_Board_V1.3.zip` |

The Gerber ZIPs are identical across all manufacturer subdirectories for each board —
only the BOM and CPL files differ to match each manufacturer's format.
Source designs live in `electronics/KiCad/0_Adapter_Board/` and
`electronics/KiCad/1_Distribution_Board/`.

## Manufacturers

### Chinese manufacturers

| Manufacturer | Service model | Notes |
|---|---|---|
| **JLCPCB** | Instant online quote, portal-driven | BOM uses LCSC part numbers; DNP parts (U3, U4, U5) have no LCSC equivalent and must be sourced and fitted separately; D1 is DNP for all manufacturers, see below |
| **PCBWay** | Manual quote via portal/sales rep | Full turnkey assembly including U3/U4/U5; accepts panel-by-supplier for Adapter Board; D1 and other DNP references confirmed with the manufacturer, see below |

### European manufacturers

| Manufacturer | Country | Service model | Notes |
|---|---|---|---|
| **Beta LAYOUT** | Germany | Quote by e-mail | PCB pool service; component costs quoted separately at order time |
| **Eurocircuits** | Belgium / Hungary | Portal + PCBA inquiry | ENIG and HAL lead-free are cost-equivalent; Solder Jumpers must be declared DNP manually |

## DNP components

D1 and the connectors/resistors below are **Do Not Place** across all manufacturers,
confirmed against the design's reference BOM (Distribution Board V1.3). Several of
them are individual references inside otherwise-populated groups (e.g. only J2 and
J3 out of the J1/J2/J3 group, or 6 out of 50 resistors in the 10 kΩ group) — the
PCBWay/Beta LAYOUT/Eurocircuits BOM files list the DNP references as separate line
items so the manufacturer does not need to guess which references in a group are
affected.

| Ref | Part | Package |
|-----|------|---------|
| D1 | MBR120VLSFT1G — Schottky diode | SOD-123 |
| J2, J3 | JST VH 2-pin connector | THT |
| J4 | JST XA 4-pin connector | THT |
| J12 | Pin Header 1x06 2.54mm | THT |
| J13 | JST XA 10-pin connector | THT |
| J14, J15, J19, J20 | 2.54-1×4P Female Header | THT |
| J16, J18 | PM254V-11-06-H85 6-pin header | THT |
| J24, J28, J32, J36, J40 | Pin Header 1x04 2.54mm | THT |
| R33, R35, R37, R39, R41, R59 | 10 kΩ resistor | R_0603 |

A1 (Raspberry Pi Pico) is also DNP but is not part of any manufacturer's BOM — it is
a module the buyer plugs in themselves, not a component to be sourced or assembled.

U3, U4 and U5 are marked **Do Not Place** in the JLCPCB BOM only, because they have
no LCSC equivalents. All other manufacturers source and assemble them without issues.

| Ref | Part | Package |
|-----|------|---------|
| U3 | R-78C5.0-1.0 — RECOM 5 V DC/DC | SIP-3 THT |
| U4 | R-78B12-2.0 — RECOM 12 V DC/DC | SIP-3 THT |
| U5 | R-78B6.5-1.5 — RECOM 6.5 V DC/DC | SIP-3 THT |

If ordering via JLCPCB, source U3/U4/U5 from Farnell, Mouser or RS Components and
fit them after delivery.

## Directory structure

```
order_files/
├── jlcpcb/                          Chinese — instant online quote
│   ├── *_BOM_JLCPCB.csv            BOM with LCSC Part# column
│   ├── *_CPL_JLCPCB.csv            Component Placement List
│   └── *.zip                        Gerber files
│
├── pcbway/                          Chinese — manual quote via portal
│   ├── *_BOM_PCBWay.csv
│   ├── *_CPL_PCBWay.csv
│   └── *.zip
│
├── beta_layout/                     European (DE) — quote by e-mail
│   ├── *_BOM_BetaLayout.csv        BOM source format
│   ├── *_BOM_BetaLayout_Vorlage.xlsx  BOM in Beta LAYOUT Excel template
│   ├── *_Centroid_BetaLayout.csv   Pick-and-place / centroid file
│   ├── *_PickPlace_BetaLayout.txt  Pick-and-place text export
│   └── *.zip                        Gerber files
│
└── eurocircuits/                    European (BE/HU) — ECAD upload portal
    ├── *_BOM_Eurocircuits.csv
    ├── *_Centroid_Eurocircuits.csv
    └── *.zip
```
