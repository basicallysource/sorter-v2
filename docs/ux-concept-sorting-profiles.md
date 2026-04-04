# UX-Konzept: Sorting Profiles (v2)

## Status Quo & Problem

Die gesamte Profil-Funktionalität wurde als technischer Durchstich gebaut: alle fachlichen Bausteine existieren und funktionieren end-to-end, aber die UI ist ein "alles was das System kann"-Dump auf einer Seite. Das Ergebnis:

- **1.160 Zeilen in einer einzigen Svelte-Komponente** (Profile Detail)
- **Kein Mental Model** — Versionen, Publishing, Rules, AI, Catalog, Preview alles gleichzeitig sichtbar
- **Kein geführter Einstieg** — Neues Profil = leeres Formular
- **Catalog-Admin-Tools** neben Regel-Editor
- **Keine Unsaved-Changes-Protection**

---

## Design-Prinzipien

1. **Progressive Disclosure** — Zeige nur das, was der User im aktuellen Schritt braucht
2. **AI-First Creation** — Der primäre Weg ein Profil zu erstellen ist: beschreiben was du sortieren willst
3. **Seiten statt Tabs** — Jede Seite hat einen klaren Zweck. Editor ≠ Detail-Ansicht
4. **Einfacher Lifecycle** — Edit → Save. Fertig. Kein Publish/Deploy-Overhead fürs MVP
5. **Machine pulls** — Die Maschine entscheidet wann sie updatet, nicht SortHive

---

## Personas & Kernaufgaben

### Persona 1: Profile Author
> "Ich will definieren, wie meine Maschine LEGO sortiert"

- Profil anlegen (AI-assisted oder manuell)
- Regeln bearbeiten und verfeinern
- Preview: wie viele Teile matchen meine Regeln?
- Speichern wenn zufrieden

### Persona 2: Profile Consumer
> "Ich will ein fertiges Profil finden und nutzen"

- Community-Profile durchstöbern
- Profil in Bibliothek speichern
- Profil forken und anpassen

### Persona 3: Machine Operator
> "Ich will sehen was auf meiner Maschine läuft und ggf. wechseln"

- Aktuelles Profil auf der Maschine sehen
- Auf neue Version updaten wenn verfügbar
- Anderes Profil aktivieren

---

## Informationsarchitektur

```
SortHive:
  /profiles                      Profiles Hub (Discover, Library, My Profiles)
  /profiles/new                  Create Wizard (AI-first)
  /profiles/:id                  Profile Detail (Show-Seite: Info, Versions, Stats)
  /profiles/:id/edit             Profile Editor (fokussiert: Rules + AI + Preview)

Lokale Sorter-UI:
  /profiles                      Profile Picker + Runtime Status + Update-Hinweis
```

Vier klar getrennte Seiten statt einem Tab-Monster:

| Seite | Zweck | Modus |
|-------|-------|-------|
| **Hub** | Finden, Entdecken, Verwalten | Browse |
| **Create Wizard** | Geführter Einstieg, AI-first | Einmalig |
| **Detail** | Profil verstehen, Versionen sehen, Fork/Save | Read |
| **Editor** | Rules bearbeiten, AI nutzen, Preview | Write |

---

## Seiten-Design

### 1. Profiles Hub `/profiles`

Einstieg in die Profil-Welt. Drei Scopes über Tabs.

```
┌──────────────────────────────────────────────────────────┐
│  Sorting Profiles                    [+ New Profile]     │
│                                                          │
│  [Discover]  [My Library]  [My Profiles]                 │
│                                                          │
│  ┌─Search────────────────────────────────────────────┐   │
│  │ Search profiles...                                │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─Profile Card──────────────────────────────────────┐   │
│  │  "Technic Parts Sorter"                       v12 │   │
│  │  by @maxbuilder                                   │   │
│  │  Sorts Technic parts into functional groups...    │   │
│  │                                                   │   │
│  │  8.432 parts · 24 categories · 89% coverage       │   │
│  │  47 saves · 12 forks                              │   │
│  │                                                   │   │
│  │  [View]  [Save to Library]  [Fork]                │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─Profile Card──────────────────────────────────────┐   │
│  │  "My Custom Sort"                              v3 │   │
│  │  3.200 parts · 8 categories · 41% coverage        │   │
│  │                                                   │   │
│  │  [View]  [Edit]                                   │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

- Karten zeigen Key-Stats der **neuesten Version** (part count, coverage, categories)
- Eigene Profile zeigen [Edit]-Button statt [Fork]
- Tags als filterbare Pills unter der Suche (später)

---

### 2. Create Profile Wizard `/profiles/new`

AI-first. Der schnellste Weg zu einem brauchbaren Profil.

#### Schritt 1: Wie möchtest du anfangen?

```
┌──────────────────────────────────────────────────────────┐
│  Create a Sorting Profile                                │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  AI-Assisted                      (recommended)     │ │
│  │  Describe what you want to sort and AI builds       │ │
│  │  the initial rules for you.                         │ │
│  │                                        [Choose]     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Start from Template                                │ │
│  │  Fork a community profile and customize it.         │ │
│  │                                        [Choose]     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Blank Profile                                      │ │
│  │  Start from scratch with an empty rule set.         │ │
│  │                                        [Choose]     │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

#### Schritt 2 (AI): Beschreibe dein Ziel

```
┌──────────────────────────────────────────────────────────┐
│  <- Back                                                 │
│                                                          │
│  Describe your sorting goals                             │
│                                                          │
│  Profile Name                                            │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ My Technic Sorter                                   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  What do you want to sort?                               │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ I want to sort Technic parts into functional        │ │
│  │ groups: gears and axles together, all types of      │ │
│  │ beams by length, connectors and pins, panels...     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  How many sorting bins do you have?                      │
│  ┌──────┐                                                │
│  │ 12   │                                                │
│  └──────┘                                                │
│                                                          │
│              [Generate Profile]                          │
└──────────────────────────────────────────────────────────┘
```

Bin-Anzahl hilft der AI die Top-Level-Kategorien sinnvoll zu begrenzen.

#### Schritt 3 (AI): Review

```
┌──────────────────────────────────────────────────────────┐
│  <- Back                                                 │
│                                                          │
│  AI generated 8 categories                               │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Gears & Axles                      1.247 parts   │   │
│  │  Beams                                892 parts   │   │
│  │  Connectors & Pins                  1.534 parts   │   │
│  │  Panels & Fairings                    423 parts   │   │
│  │  High-Value Parts                     156 parts   │   │
│  │  Wheels & Tires                       312 parts   │   │
│  │  Other Technic                        987 parts   │   │
│  │  Miscellaneous                      3.881 parts   │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  Total: 9.432 parts · 59% coverage                       │
│                                                          │
│  You can refine everything in the editor afterwards.     │
│                                                          │
│         [Create Profile & Open Editor]                   │
└──────────────────────────────────────────────────────────┘
```

Nur die Zusammenfassung. Kein Regel-Detail. Feinschliff passiert im Editor.

---

### 3. Profile Detail `/profiles/:id` (Show-Seite)

Die **informative Seite**. Hier versteht man was ein Profil ist und macht, sieht die History, und entscheidet ob man es nutzen will.

#### Für alle User (Owner + Visitor)

```
┌──────────────────────────────────────────────────────────┐
│  <- Profiles                                             │
│                                                          │
│  My Technic Sorter                                       │
│  Sorts Technic parts into functional groups for a        │
│  12-bin sorting machine.                                 │
│                                                          │
│  [technic] [functional] [12-bin]                         │
│                                                          │
│  ┌─Stats─────────────────────────────────────────────┐   │
│  │  9.432 parts    24 categories    89% coverage     │   │
│  │  47 saves       12 forks         v7 (latest)      │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  [Edit Profile]  [Save to Library]  [Fork]               │
│                                                          │
│  ── Categories ──────────────────────────────────────    │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Gears & Axles              1.247 parts  ██████░  │   │
│  │  Connectors & Pins          1.534 parts  ███████░ │   │
│  │  Other Technic                987 parts  █████░   │   │
│  │  Beams                        892 parts  ████░    │   │
│  │  Panels & Fairings            423 parts  ██░      │   │
│  │  Wheels & Tires               312 parts  ██░      │   │
│  │  High-Value Parts             156 parts  █░       │   │
│  │  Miscellaneous              3.881 parts  fallback │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  ── Version History ─────────────────────────────────    │
│                                                          │
│  v7 · 2 hours ago                                        │
│    "Added pneumatics category via AI"                    │
│    9.519 parts · 89% coverage                            │
│                                                          │
│  v6 · yesterday                                          │
│    "Split beams by length"                               │
│    9.432 parts · 87% coverage                            │
│                                                          │
│  v5 · 3 days ago                                         │
│    "Stable release for workshop"                         │
│    8.891 parts · 85% coverage                            │
│                                                          │
│  v4 · 4 days ago                                         │
│    8.102 parts · 83% coverage                            │
│                                                          │
│  ... Show all 7 versions                                 │
│                                                          │
│  ── Settings ────────────────────────────────────────    │
│  (nur Owner)                                             │
│                                                          │
│  Name        [My Technic Sorter          ]               │
│  Description [Sorts Technic parts into...]               │
│  Visibility  [Private ▾]                                 │
│  Tags        [technic] [functional] [+]                  │
│                                      [Save Changes]      │
│                                                          │
│  ────────────────────────────────────────────────────    │
│  [Delete this Profile]                                   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Designentscheidungen:**

- **Eine Seite, scrollbar** — Kein Tab-Interface. Alles was man über ein Profil wissen muss auf einem Blick
- **Kategorien als visuelle Übersicht** — Balken-Diagramm statt Regel-Detail. "Was kommt raus?" statt "Wie ist es gebaut?"
- **Version History inline** — Chronologisch, mit optionalem Change Note und Stats-Delta
- **[Edit Profile]** prominent für Owner → leitet zum Editor weiter
- **[Fork]** prominent für Visitor → erstellt Kopie und leitet zum Editor weiter
- **Settings-Section** am Ende, nur für Owner sichtbar. Name, Description, Visibility, Tags, Delete

**Visitor sieht:**
- Alles oben genannte außer Settings-Section und [Edit]-Button
- [Save to Library] und [Fork] als primäre Actions

**Owner sieht:**
- Alles, inkl. Settings-Section
- [Edit Profile] als primäre Action

---

### 4. Profile Editor `/profiles/:id/edit`

Die **fokussierte Arbeitsseite**. Hier passiert das eigentliche Authoring.

```
┌──────────────────────────────────────────────────────────┐
│  <- My Technic Sorter (v7)           [Save]              │
│                                                          │
│  ┌─Rule Tree──────────────────┐┌─Selected Rule──────────┐│
│  │                            ││                        ││
│  │  > Gears & Axles  1247 pts││  Gears & Axles         ││
│  │    > Spur Gears     89 pts││                        ││
│  │    > Bevel Gears    34 pts││  Match: [All ▾]        ││
│  │    > Axles         412 pts││                        ││
│  │                            ││  Conditions            ││
│  │  v Beams            892 pts││  ┌────────────────────┐││
│  │  v Connectors     1534 pts││  │ category_name      │││
│  │  v Panels           423 pts││  │ contains           │││
│  │  v High-Value       156 pts││  │ "gear"             │││
│  │  v Wheels           312 pts││  └────────────────────┘││
│  │  v Other Technic    987 pts││  ┌────────────────────┐││
│  │  v Miscellaneous  3881 pts││  │ category_id        │││
│  │                            ││  │ in                 │││
│  │  [+ Add Category]          ││  │ [54, 55, 56]      │││
│  │                            ││  └────────────────────┘││
│  │  ───────────────────       ││  [+ Add Condition]    ││
│  │  Fallback Behavior         ││                        ││
│  │  [x] Rebrickable cats      ││  Children              ││
│  │  [ ] BrickLink cats        ││  > Spur Gears         ││
│  │  [ ] Split by color        ││  > Bevel Gears        ││
│  │                            ││  > Axles              ││
│  │                            ││  [+ Add Child]        ││
│  │                            ││                        ││
│  │                            ││  ── Matching Parts ── ││
│  │                            ││  1.247 parts match     ││
│  │                            ││  3648 Gear 24 Tooth    ││
│  │                            ││  3649 Gear 40 Tooth    ││
│  │                            ││  32062 Axle 2L         ││
│  │                            ││  [Show all]            ││
│  └────────────────────────────┘└────────────────────────┘│
│                                                          │
│  ┌─AI Assistant────────────────────────────────────────┐ │
│  │  Context: Gears & Axles (selected)                  │ │
│  │  ┌──────────────────────────────────────────┐       │ │
│  │  │ Add a sub-rule for worm gears...    [Ask]│       │ │
│  │  └──────────────────────────────────────────┘       │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─Bottom Bar────────────────────────────────────────┐   │
│  │  Unsaved changes                          [Save]  │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**Das Layout hat drei Bereiche:**

#### Linke Spalte: Rule Tree
- **Collapsible** — Jede Kategorie/Regel ist ein-/ausklappbar (> / v)
- **Part-Count inline** — Sofort sehen wie viele Teile jede Regel matcht
- **Drag & Drop** zum Umsortieren (later)
- **[+ Add Category]** am Ende für neue Top-Level-Regeln
- **Fallback Behavior** unter dem Baum (Rebrickable/BrickLink/Color-Split Checkboxen)

#### Rechte Spalte: Selected Rule Detail
Zeigt sich wenn eine Regel im Baum ausgewählt ist:
- **Name** (editierbar)
- **Match Mode** (All/Any Dropdown)
- **Conditions** mit feldspezifischen Inputs:
  - `category_id` → Multiselect-Dropdown mit Kategorienamen
  - `color_id` → Color-Picker/Multiselect
  - `name`, `part_num` → Text mit Autocomplete
  - Numerische Felder → Number-Input
  - `in` Operator → Tag-Input für mehrere Werte
- **Children** — Liste der Kind-Regeln + [Add Child]
- **Matching Parts** — Live-Preview der gematchten Teile (auto-update nach Änderung, debounced)

#### Unterer Bereich: AI Assistant (collapsed by default)
- **Kontextbewusst** — zeigt welche Regel gerade selektiert ist
- **Ein-Zeilen-Input** + [Ask] Button — wie ein Chat-Input
- **Expandiert** wenn die AI antwortet mit Proposal + [Apply] Button
- Nicht als eigene Seite oder Tab, sondern **inline im Workflow** des Editors
- Nach Apply: Rules werden aktualisiert, AI-Bereich klappt wieder zusammen

#### Header + Bottom Bar
- **Header**: Zurück-Link zum Detail, Profilname + aktuelle Version, Save-Button
- **Bottom Bar** (sticky): Unsaved-Changes-Indikator + Save-Button
- **Save** öffnet kleines Popover:

```
┌─Save──────────────────────────┐
│  What changed? (optional)      │
│  ┌────────────────────────────┐│
│  │ Added worm gear sub-rule   ││
│  └────────────────────────────┘│
│  [Cancel]  [Save]              │
└────────────────────────────────┘
```

Kein Label, kein Publish-Toggle, kein Overhead. Einfach speichern mit optionalem Kommentar.

---

### 5. Lokale Sorter-UI `/profiles`

Die Maschine ist Consumer. Sie pullt Profile, sie pusht nicht.

```
┌──────────────────────────────────────────────────────────┐
│  Sorting Profiles                  [Reload from Disk]    │
│                                                          │
│  ┌─Active Profile────────────────────────────────────┐   │
│  │                                                   │   │
│  │  "My Technic Sorter" v5                           │   │
│  │  Source: SortHive (hub.sorthive.com)               │   │
│  │  Applied: 2 hours ago · 8.432 parts · 24 cats     │   │
│  │  Status: In sync                                  │   │
│  │                                                   │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  ── Available Profiles ──────────────────────────────    │
│                                                          │
│  ┌─Profile──────────────────────────────────────────┐    │
│  │  My Technic Sorter                                │    │
│  │  v7 available (you're on v5)      [Update]        │    │
│  │                                                   │    │
│  │  Version: [v7 ▾]                  [Apply]         │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─Profile──────────────────────────────────────────┐    │
│  │  Community Technic Sorter                         │    │
│  │  v12                                              │    │
│  │                                                   │    │
│  │  Version: [v12 ▾]                 [Apply]         │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

**Designentscheidungen:**

- **Active Profile prominent** oben — was läuft gerade?
- **Update-Hinweis** wenn eine neuere Version verfügbar ist ("v7 available, you're on v5")
- **Version-Picker + Apply** — Dropdown + Button, mehr braucht man nicht
- **Kein Editing** — dafür geht man auf SortHive
- **Kein Catalog-Sync** — passiert auf SortHive-Seite
- **Kein Deploy von SortHive** — die Maschine pullt selbst

---

## Workflows

### Workflow 1: Profil erstellen (AI-first)

```
Hub → [+ New Profile] → [AI-Assisted]
  → Describe goals + bin count
  → AI generates rules → Review summary
  → [Create & Open Editor]
  → Editor mit v1 geladen
  → Ggf. verfeinern
  → [Save] → v2
  → Fertig in SortHive
  → Auf der Maschine: /profiles → neues Profil sichtbar → [Apply]
```

### Workflow 2: Community-Profil nutzen

```
Hub → [Discover] → Browse/Search
  → [View] → Detail-Seite
  → [Save to Library] (zum Merken)
  → oder [Fork] → Editor mit eigener Kopie
  → Auf der Maschine: Profil taucht in Available Profiles auf
```

### Workflow 3: Profil iterativ verbessern

```
Hub → [My Profiles] → [Edit]
  → Editor: Rule auswählen, Conditions tweaken
  → Preview aktualisiert live
  → AI: "Add a sub-rule for XY" → [Apply]
  → [Save]
  → Auf der Maschine: "v8 available" → [Update]
```

### Workflow 4: Profil auf Maschine wechseln

```
Lokale UI → /profiles
  → Active Profile sehen
  → Anderes Profil aus der Liste wählen
  → Version auswählen → [Apply]
  → Sofort aktiv (Artifact download + Runtime reload)
```

---

## Catalog-Management

Catalog-Sync (Rebrickable Parts, BrickLink Preise) ist ein Admin-Tool und gehört nicht in den Editor.

**Lösung:** Eigener Bereich in SortHive Settings.

```
/settings → Catalog Management
  → Sync-Status für alle Datenquellen
  → Sync-Buttons
  → Part-Search-Tool
```

Der Editor setzt voraus dass der Catalog aktuell ist. Wenn kein Catalog vorhanden: Hinweis-Banner mit Link zum Setup.

---

## Condition-Builder: Feldspezifische Inputs

| Feld | Input-Typ |
|------|-----------|
| `category_id` | Multiselect-Dropdown mit Kategorienamen |
| `category_name` | Text mit Autocomplete |
| `color_id` | Color-Picker Grid / Multiselect |
| `name`, `part_num` | Text mit Autocomplete aus Catalog |
| `year_from`, `year_to` | Number-Input |
| `bl_price_*` | Number mit Währungsformat |
| `*_is_obsolete` | Boolean Toggle |
| `in` Operator | Tag-Input (mehrere Werte) |
| `regex` Operator | Text mit Regex-Preview |

---

## Zusammenfassung: Was ändert sich?

| Aspekt | Status Quo | Neu |
|--------|-----------|-----|
| Seitenstruktur | Alles auf einer 1.160-Zeilen-Seite | 4 klare Seiten: Hub, Create, Detail, Editor |
| Profil-Erstellung | Leeres Modal | AI-first Wizard |
| Rule-Editor | Inline-Rekursion, kein Collapse | Zwei-Spalten: Baum + Detail, collapsible |
| AI-Assistant | Chat-Sidebar neben Editor | Inline im Editor, kontextbewusst, collapsed by default |
| Versions | Liste in Seitenleiste | Chronologisch auf Detail-Seite |
| Save-Flow | "Save New Version" + Checkboxen | Simple Save mit optionalem Kommentar |
| Lifecycle | Edit → Save → Publish → Deploy | Edit → Save |
| Machine-Update | Assignment von SortHive pushen | Machine zeigt "Update available" → User pullt |
| Conditions | Generisches Textfeld | Feldspezifische Inputs |
| Catalog-Sync | Im Editor eingebettet | Eigener Bereich in Settings |
| Detail-Ansicht | Editor mit disabled Feldern | Eigene read-only Show-Seite |

---

## Implementierungs-Reihenfolge

1. **Create Wizard (AI-first)** — Größter Impact für neue User
2. **Detail-Seite** (Show/Read) — Profil verstehen, Versions-History, Fork/Save
3. **Editor-Seite** (Zwei-Spalten-Layout) — Rule Tree + Detail + inline AI + Live-Preview
4. **Lokale UI: Update-Hinweis** — "Neue Version verfügbar" auf der Maschine
5. **Condition-Builder** — Feldspezifische Inputs statt Textfelder
6. **Catalog raus aus Editor** — In eigenen Settings-Bereich verschieben
