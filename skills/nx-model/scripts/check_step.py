# =============================================================================
#  STEP content checker - stdlib only, run with any Python
#
#  Files must be checked for CONTENT, not existence. A STEP file can be a
#  perfectly valid, plausibly-sized ISO-10303-21 document that contains no solid
#  at all - which is exactly what NX's in-process DexManager exporter produces
#  under run_journal.exe.
#
#    python check_step.py out/part.step
#
#  Exit code 0 = geometry present, 1 = empty/geometry-less.
# =============================================================================
import re
import sys

SOLID = "MANIFOLD_SOLID_BREP("
FACE = "ADVANCED_FACE("
SHELL = "CLOSED_SHELL("
# a solid exported as a set of open surfaces instead of a body still has faces
REQUIRED = ((SOLID, 1),)


def check(path):
    try:
        with open(path, "r", encoding="latin-1", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print("FAIL  cannot open %s: %s" % (path, exc))
        return 1

    counts = {
        SOLID: text.count(SOLID),
        FACE: text.count(FACE),
        SHELL: text.count(SHELL),
        "CARTESIAN_POINT(": text.count("CARTESIAN_POINT("),
        "CYLINDRICAL_SURFACE(": text.count("CYLINDRICAL_SURFACE("),
        "CONICAL_SURFACE(": text.count("CONICAL_SURFACE("),
    }
    header = re.search(r"FILE_DESCRIPTION\((.*?)\);", text, re.S)
    print("FILE : %s  (%d bytes)" % (path, len(text)))
    if header:
        print("DESC : %s" % " ".join(header.group(1).split())[:120])
    for k, v in counts.items():
        print("  %-26s %d" % (k.rstrip("("), v))

    bad = [name for name, minimum in REQUIRED if counts[name] < minimum]
    if bad:
        print("VERDICT: NO GEOMETRY - missing %s. This export is a shell."
              % ", ".join(bad))
        return 1

    print("VERDICT: OK - %d solid(s), %d face(s)" % (counts[SOLID], counts[FACE]))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    rc = 0
    for p in sys.argv[1:]:
        rc |= check(p)
    sys.exit(rc)
