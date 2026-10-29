#!/usr/bin/env bash
# Publish what release.sh built as GitHub Releases, which is what the mod's
# online updates read (src/frontend/app/updater, Tools > Updates):
#
#   ./publish.sh program    tag v<APP_VERSION>:      program-only installer, full setup,
#                           portable zip, SHA256SUMS, manifest.json
#   ./publish.sh data       tag data-<data_version>: data_manifest.json, data setup,
#                           tagged on the data commit the manifest names
#
# Needs the GitHub CLI (gh auth login). Repositories and tag prefixes come from
# src/update_sources.json, the same file the program reads: splitting the data
# into its own repository is a change there (and DATA= for release.sh).
#
# Env: OUT (default ~/r08-build/out)  NOTES (release notes file, else gh asks)
#      DRAFT=1 (create drafts: the mod never offers a draft, publish it by hand)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"
OUT="${OUT:-$HOME/r08-build/out}"
WHAT="${1:-}"
die() { echo "ERROR: $*" >&2; exit 1; }
src() { python3 -c "import json,sys; print(json.load(open('$SRC/update_sources.json'))['$1']['$2'])"; }
command -v gh >/dev/null || die "the GitHub CLI (gh) is needed"
notes=(); [ -n "${NOTES:-}" ] && notes=(--notes-file "$NOTES") || notes=(--generate-notes)
draft=(); [ -n "${DRAFT:-}" ] && draft=(--draft)

pushed() {  # repo dir, commit: the commit is on a remote branch (raw.githubusercontent.com can serve it)
  git -C "$1" fetch --quiet || true
  [ -n "$(git -C "$1" branch -r --contains "$2" 2>/dev/null)" ]
}

case "$WHAT" in
program)
  V="$(sed -n 's/^APP_VERSION *= *"\(.*\)"/\1/p' "$SRC/shared/version.py")"
  REPO="$(src program repo)"; TAG="$(src program tag_prefix)$V"
  INSTALLER="$(src program installer | sed "s/{version}/$V/")"
  [ -f "$OUT/$INSTALLER" ] || die "$OUT/$INSTALLER missing (run release.sh)"
  grep -q " \*\?$INSTALLER\$" "$OUT/SHA256SUMS" || die "$INSTALLER is not in SHA256SUMS"
  COMMIT="$(git -C "$SRC" rev-parse HEAD)"
  pushed "$SRC" "$COMMIT" || die "push $COMMIT first"
  files=("$OUT/$INSTALLER" "$OUT/SHA256SUMS" "$OUT/manifest.json")
  for f in "$OUT/R08Revival_${V}_setup.exe" "$OUT/R08Revival_${V}_portable.zip"; do [ -f "$f" ] && files+=("$f"); done
  gh release create "$TAG" "${files[@]}" --repo "$REPO" --target "$COMMIT" \
    --title "Rugby 08 Revival $V" "${notes[@]}" "${draft[@]}"
  ;;
data)
  M="$OUT/data_manifest.json"
  [ -f "$M" ] || die "$M missing (run release.sh data)"
  read -r DV REPO COMMIT < <(python3 -c "import json; m=json.load(open('$M')); print(m['data_version'], m['source']['repo'], m['source']['commit'])")
  [ "$REPO" = "$(src data repo)" ] || die "the manifest names $REPO, update_sources.json says $(src data repo)"
  TAG="$(src data tag_prefix)$DV"
  DATA_DIR="${R08_DATA:-$SRC/../data}"
  pushed "$DATA_DIR" "$COMMIT" || die "push the data commit $COMMIT first"
  files=("$M")
  [ -f "$OUT/R08Revival_data_${DV}_setup.exe" ] && files+=("$OUT/R08Revival_data_${DV}_setup.exe")
  gh release create "$TAG" "${files[@]}" --repo "$REPO" --target "$COMMIT" \
    --title "Data $DV" "${notes[@]}" "${draft[@]}"
  ;;
*)
  sed -n '2,17p' "$0"; exit 1 ;;
esac
