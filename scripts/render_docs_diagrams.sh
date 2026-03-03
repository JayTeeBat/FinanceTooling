#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIAGRAM_DIR="${ROOT_DIR}/docs/diagrams"

if ! command -v plantuml >/dev/null 2>&1; then
  echo "plantuml is required to render diagrams." >&2
  echo "Install PlantUML and ensure \`plantuml\` is available in PATH." >&2
  exit 1
fi

plantuml -tsvg "${DIAGRAM_DIR}"/*.puml
echo "Rendered SVG diagrams in ${DIAGRAM_DIR}"
