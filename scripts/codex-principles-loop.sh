#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/codex-principles-loop.sh [max-runs]

Starts fresh Codex sessions in a mini Ralph loop. Each session must:
  1. pick exactly one concrete violation of docs/lab/sorter-architecture-principles/index.md,
  2. fix only that point,
  3. run focused verification,
  4. create exactly one git commit,
  5. stop.

Environment:
  CODEX_BIN       Codex executable to use (default: codex)
  CODEX_MODEL     Optional model name passed as -m
  CONTINUE_ON_NO_COMMIT=1 keeps looping when a session exits without a commit

Logs are written under .git/codex-principles-loop/.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

MAX_RUNS="${1:-3}"
if ! [[ "$MAX_RUNS" =~ ^[0-9]+$ ]] || [[ "$MAX_RUNS" -lt 1 ]]; then
  echo "max-runs must be a positive integer" >&2
  exit 2
fi

CODEX_BIN="${CODEX_BIN:-codex}"
ROOT="$(git rev-parse --show-toplevel)"
PRINCIPLES_DOC="docs/lab/sorter-architecture-principles/index.md"
LOG_DIR="$ROOT/.git/codex-principles-loop"
mkdir -p "$LOG_DIR"

codex_base_args=(exec --cd "$ROOT" --ephemeral)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  codex_base_args+=(-m "$CODEX_MODEL")
fi

if "$CODEX_BIN" exec --help 2>/dev/null | grep -q -- "--yolo"; then
  codex_base_args+=(--yolo)
else
  codex_base_args+=(--dangerously-bypass-approvals-and-sandbox --sandbox danger-full-access)
fi

require_clean_tree() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree is not clean; stopping before starting a new loop." >&2
    git status --short >&2
    exit 1
  fi
}

run_prompt() {
  cat <<'PROMPT'
Du bist eine frische Codex-Session in einem Mini-Ralph-Loop.

Ziel:
- Wähle genau einen konkreten Punkt im Projekt, der aktuell gegen docs/lab/sorter-architecture-principles/index.md verstößt.
- Behebe nur diesen einen Punkt.
- Committe genau einen Git-Commit.
- Beende danach die Session.

Pflichtlektüre zuerst:
- AGENTS.md
- docs/lab/sorter-architecture-principles/index.md

Auswahlregeln:
- Arbeite nicht an mehreren Hotspots gleichzeitig.
- Bevorzuge kleine, lokale Verbesserungen mit neutraler oder negativer Netto-LOC.
- Netto-positive Änderungen sind nur erlaubt, wenn sie einen klaren privaten Zugriff,
  eine klare Duplikation oder eine klare Ownership-Grenze beseitigen und im
  Commit-Body begründet wird, warum eine kleinere oder zeilensparende Lösung
  nicht sinnvoll war. Wenn der beste sichere Fix netto Code addiert und der
  Gewinn nicht eindeutig ist, mache NOOP.
- Bevorzuge Verstöße gegen: helpful mega-file, private-field archaeology, duplicated policy, hidden wiring behavior, empty wrappers, startup/maintenance branches in steady-state loops.
- Keine großen Architekturwürfe.
- Keine neue Dependency, außer der einzelne Verstoß ist ohne sie klar schlechter lösbar.
- Keine Format-only-, Rename-only- oder Kommentar-only-Commits.
- Fasse dieses Loop-Skript selbst nicht an.
- Fasse keine LabRun-/Handoff-/lokalen Artefaktordner an.
- Keine Live-Hardware-Aktionen, keine Stepper-/Servo-/Runtime-Start-Kommandos. Arbeite statisch und mit Tests.

Arbeitsweise:
1. Prüfe den Working Tree. Wenn er nicht sauber ist, stoppe ohne Änderung.
2. Suche einen kleinen konkreten Verstoß gegen die Principles.
3. Miss kurz den Ausgangspunkt, soweit passend: Datei/LOC/Duplizierung/Private-Field-Zugriffe.
4. Ändere die kleinste sinnvolle Einheit.
5. Führe fokussierte Tests oder statische Checks aus. Wenn kein Test sinnvoll ist, erkläre im Commit-Body warum.
6. Prüfe `git diff --stat` und `git diff --numstat`. Stelle sicher, dass der
   Scope klein geblieben ist und der Netto-LOC-Effekt bewusst ist.
7. Committe genau einen Commit mit einer präzisen Message.
8. Hinterlasse keinen dreckigen Working Tree.

Commit-Regeln:
- Genau ein Commit, wenn du etwas geändert hast.
- Commit-Message im Stil: `refactor: <konkreter kleiner punkt>` oder `chore: <konkreter kleiner punkt>`.
- Commit-Body muss enthalten:
  - Principle-Verstoß
  - Was geändert wurde
  - Verifikation
  - LOC/Scope-Hinweis
  - Bei Netto-Plus: kurze Begründung, warum das Plus die kleinste sinnvolle
    Verbesserung war

Wenn du keinen sicheren kleinen Punkt findest:
- Mache keine Änderung.
- Erzeuge keinen Commit.
- Antworte am Ende mit `NOOP: <kurzer Grund>`.

Ende:
- Nach Commit oder NOOP sofort final antworten. Keine Folgeaufgaben starten.
PROMPT
}

require_clean_tree

for ((run = 1; run <= MAX_RUNS; run++)); do
  before="$(git rev-parse HEAD)"
  log_file="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S)-$run.log"

  echo "== Codex principles loop $run/$MAX_RUNS =="
  echo "   before: $before"
  echo "   log:    $log_file"

  set +e
  run_prompt | "$CODEX_BIN" "${codex_base_args[@]}" - 2>&1 | tee "$log_file"
  status="${PIPESTATUS[1]}"
  set -e

  after="$(git rev-parse HEAD)"

  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Session left a dirty working tree; stopping." >&2
    git status --short >&2
    exit 1
  fi

  if [[ "$status" -ne 0 ]]; then
    echo "Codex exited with status $status; stopping." >&2
    exit "$status"
  fi

  if [[ "$after" == "$before" ]]; then
    echo "No commit created in loop $run."
    if [[ "${CONTINUE_ON_NO_COMMIT:-0}" != "1" ]]; then
      echo "Stopping. Set CONTINUE_ON_NO_COMMIT=1 to keep trying."
      exit 0
    fi
  else
    echo "   after:  $after"
    git log -1 --oneline
  fi
done

echo "Completed $MAX_RUNS Codex principles loop run(s)."
