# =============================================================================
#  show_in_nx - open a built part in the NX session the user already has open
#
#  WHY THIS EXISTS
#    A journal builds a .prt; it does not appear in a window the user is looking
#    at. This is the last step that closes that gap, and it deliberately uses the
#    operating system's file association rather than NX's own UI, because:
#      * NX exposes no API to start journal playback in a live session
#        (JournalManager has IsJournalRunning / StartRecording, no PlayJournal),
#      * run_journal.exe cannot attach to an already-running session,
#      * and NX's own Ctrl+O / File menu are not automatable.
#    `os.startfile` needs none of that, so ANY agent that can run a command can
#    use it - no Computer Use, no screenshots, no clicking.
#
#  RUN with plain Python 3 - this is NOT a journal and does not import NXOpen:
#      python show_in_nx.py my_spec.json        # out_dir/part_name from the spec
#      python show_in_nx.py path/to/part.prt    # or point it straight at a part
#
#  If NX is already running the part opens in that session; if not, NX starts.
# =============================================================================
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import nx_common as nxc


def part_path_from(argument):
    """Accept either a spec file or a .prt path; return the .prt to open."""
    if argument.startswith("-"):
        raise nxc.SpecError("unexpected option %r - pass a spec file or a .prt path"
                            % argument)
    if argument.lower().endswith(".prt"):
        return os.path.abspath(os.path.expanduser(argument))
    spec, source = nxc.load_spec(["show_in_nx", argument])
    paths = nxc.paths_for(spec)
    print("[..]   spec   : %s" % source)
    print("[..]   part   : %s" % paths["prt"])
    return paths["prt"]


def open_with_os(path):
    """Hand the file to the OS so the registered application (NX) opens it."""
    if hasattr(os, "startfile"):                      # Windows
        os.startfile(path)                            # noqa: S606 - intended
        return "os.startfile"
    # Portable fallbacks, in the order most likely to hand off to a running app
    for cmd in (["cmd", "/c", "start", "", path],
                ["xdg-open", path],
                ["open", path]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return " ".join(cmd[:2])
        except OSError:
            continue
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: python show_in_nx.py <spec.json | part.prt>")
        return 2

    try:
        part = part_path_from(sys.argv[1])
    except (nxc.SpecError, ValueError) as exc:
        print("[FAIL] %s" % exc)
        return 1

    if not os.path.isfile(part):
        print("[FAIL] no such part: %s" % part)
        if sys.argv[1].lower().endswith(".prt"):
            print("       build that part first, or pass the spec it was built from")
        else:
            # Which journal depends on the spec's "part", so name no particular one:
            # suggesting build_plate.py for a flange spec would be wrong.
            print("       build it first, e.g.")
            print('       "$UGII_BASE_DIR/NXBIN/run_journal.exe" <build_*.py> -args %s'
                  % sys.argv[1])
        return 1

    how = open_with_os(part)
    if how is None:
        print("[FAIL] could not hand %s to the operating system" % part)
        return 1

    size_kb = os.path.getsize(part) / 1024.0
    print("[ok]   opened %s (%.1f KB) via %s" % (os.path.basename(part), size_kb, how))
    # Say only what this line knows. os.startfile hands the path to the file
    # association and returns immediately - it does not wait for NX, and NX takes
    # tens of seconds to come up when it was not already running. Claiming the part
    # is on screen would be the unverified assertion this skill refuses elsewhere.
    # (That NX does end up showing the part and its feature tree was verified by
    # observation and is recorded in SKILL.md; it is just not knowable here.)
    print("[..]   handed to NX; it shows up once the session has loaded it")
    base, _ext = os.path.splitext(part)
    step_path = base + ".step"
    if os.path.isfile(step_path):
        print("[..]   STEP alongside it: %s" % os.path.basename(step_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
