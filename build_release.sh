#!/usr/bin/env bash
# Builds the two release downloads into build_release/:
#   BossTracker.exe  - single file (also copied over ./BossTracker.exe)
#   BossTracker.zip  - unpacked build (exe + _internal) with the assets, boss and sources folders
# Usage: PY=path/to/python ./build_release.sh
set -e
cd "$(dirname "$0")"
PY=${PY:-python}
OUT=build_release
rm -rf "$OUT"
common=(--noconsole --noupx --name BossTracker --icon="$PWD/icon.ico" --workpath "$OUT/work" --specpath "$OUT" -y main.py)

"$PY" -m PyInstaller --onefile --distpath "$OUT/onefile" "${common[@]}"
"$PY" -m PyInstaller --onedir --distpath "$OUT/onedir" "${common[@]}"

# Only git-tracked images go in the zip, never boss_tracker_data.json or local extras.
git ls-files assets boss sources | while read -r f; do
    mkdir -p "$OUT/onedir/BossTracker/$(dirname "$f")"
    cp "$f" "$OUT/onedir/BossTracker/$f"
done

cp "$OUT/onefile/BossTracker.exe" "$OUT/BossTracker.exe"
cp "$OUT/onefile/BossTracker.exe" BossTracker.exe || echo "WARNING: ./BossTracker.exe is open - close the app and copy it from $OUT"
(cd "$OUT/onedir" && "$PY" -m zipfile -c ../BossTracker.zip BossTracker/)
ls -la "$OUT/BossTracker.exe" "$OUT/BossTracker.zip"
