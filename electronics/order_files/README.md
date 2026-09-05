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
| **JLCPCB** | Instant online quote, portal-driven | BOM uses LCSC part numbers; DNP parts (D1, U3, U4, U5) have no LCSC equivalent and must be sourced and fitted separately |
| **PCBWay** | Manual quote via portal/sales rep | Full turnkey assembly including DNP parts; accepts panel-by-supplier for Adapter Board |

### European manufacturers

| Manufacturer | Country | Service model | Notes |
|---|---|---|---|
| **Beta LAYOUT** | Germany | Quote by e-mail | PCB pool service; component costs quoted separately at order time |
| **Eurocircuits** | Belgium / Hungary | Portal + PCBA inquiry | ENIG and HAL lead-free are cost-equivalent; Solder Jumpers must be declared DNP manually |

## DNP components (JLCPCB only)

The components below are marked **Do Not Place** in the JLCPCB BOM because they have
no LCSC equivalents. All other manufacturers source and assemble them without issues.

| Ref | Part | Package |
|-----|------|---------|
| D1 | MBR120VLSFT1G — Schottky diode | SOD-123 |
| U3 | R-78C5.0-1.0 — RECOM 5 V DC/DC | SIP-3 THT |
| U4 | R-78B12-2.0 — RECOM 12 V DC/DC | SIP-3 THT |
| U5 | R-78B6.5-1.5 — RECOM 6.5 V DC/DC | SIP-3 THT |

If ordering via JLCPCB, source these parts from Farnell, Mouser or RS Components and
fit them after delivery.

Note: D1 was originally marked DNP as a JLCPCB-specific workaround. It is assembled
without issues by PCBWay, Beta LAYOUT and Eurocircuits.

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
