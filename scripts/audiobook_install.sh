#!/bin/bash
# Install a prepared audiobook package into the Audiobookshelf library.
#
# usage: bash audiobook_install.sh <package-dir>
#
# The package dir holds, next to this script:
#   pkg.tgz        the *.m4a files
#   md5.txt        "<md5>  <filename>" per file, from bili_album_verify.py
#   bookname.txt   the UTF-8 folder name to create (avoids argv encoding issues)
#   c1.jpg         the cover, installed as cover.jpg
#
# Build pkg.tgz with a file list, not with `$(ls *.m4a)`: part titles contain
# spaces, so shell word splitting shreds them.  tar -czf pkg.tgz -C <dir>
# --files-from=list.txt, then check `tar -tzf pkg.tgz | wc -l` against the count.
#
# The library folder is a watched path: a new folder is picked up by the
# scanner within a minute or two, no UI action needed.
set -u
P=$1
D_ROOT=/opt/audiobookshelf/audiobooks
NAME=$(tr -d '\r\n' < "$P/bookname.txt")
DEST="$D_ROOT/$NAME"
echo "PKG=$P NAME=$NAME"
if [ -e "$DEST" ]; then echo "ABORT already exists: $DEST"; exit 1; fi

X=$(mktemp -d)
tar -xzf "$P/pkg.tgz" -C "$X" || { echo "ABORT_TAR"; exit 1; }
n=$(find "$X" -maxdepth 1 -name '*.m4a' | wc -l)
want=$(wc -l < "$P/md5.txt")
echo "extracted=$n want=$want"
if [ "$n" -ne "$want" ]; then echo "ABORT_COUNT"; exit 1; fi

mkdir -p "$DEST"
mv "$X"/*.m4a "$DEST"/
install -m 644 -o root -g root "$P/c1.jpg" "$DEST/cover.jpg"
chown -R root:root "$DEST"
chmod 755 "$DEST"
rm -rf "$X"

cd "$DEST" || exit 1
OUT=/tmp/md5check_$(basename "$P").txt
LC_ALL=C md5sum -c "$P/md5.txt" > "$OUT" 2>&1
echo "md5_ok=$(grep -c ': OK$' "$OUT") md5_other=$(grep -c -v ': OK$' "$OUT")"
grep -v ': OK$' "$OUT" | head -10
echo "audio=$(ls -1 "$DEST"/*.m4a 2>/dev/null | wc -l) entries=$(ls -1 "$DEST" | wc -l)"
du -sh "$DEST"
