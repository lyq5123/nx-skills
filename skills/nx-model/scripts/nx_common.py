# =============================================================================
#  nx_common - shared plumbing for the nx-model journals
#
#  Sibling import works in the NX embedded interpreter: run_journal.exe puts the
#  script's own directory on sys.path[0] and defines __file__. Verified on NX 2406.
#
#  Deliberately stdlib-only: NX ships CPython 3.10 with no site-packages.
# =============================================================================
import json
import os
import sys
import time

# -----------------------------------------------------------------------------
# spec defaults - running a journal with no arguments reproduces the old
# hardcoded behaviour exactly, so existing invocations keep working.
# -----------------------------------------------------------------------------
# Default output location. Home-based rather than a bare relative name, because
# under run_journal.exe the current directory is the script's own directory -
# a relative default would scatter parts into the skill tree. Override per run
# with "out_dir" in a spec.
DEFAULT_OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")

DEFAULT_PLATE = {
    "part_name": "mounting_plate_demo",
    "out_dir": DEFAULT_OUT_DIR,
    "part": "mounting_plate",
    "params": {
        "plate_w": 120.0,
        "plate_h": 80.0,
        "plate_t": 10.0,
        "hole_d": 6.6,
        "hole_inset": 12.0,
        "bore_d": 30.0,
        "fillet_r": 0.0,
    },
    "export": {"step": True, "log_file": True},
}

PARAM_KEYS = ("plate_w", "plate_h", "plate_t", "hole_d", "hole_inset", "bore_d", "fillet_r")

# -----------------------------------------------------------------------------
# part recipes (nx_recipes.py) - everything that is specific to one part type:
# parameters, validation rules, analytic volume and face counts.
#
# Imported defensively: this directory is put on sys.path explicitly so the
# recipes also resolve when a journal is played from inside the NX GUI, where
# sys.path[0] is not guaranteed to be the script directory. Still stdlib-only
# and still a flat sibling import - no package, no relative imports.
# -----------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import nx_recipes as recipes


class SpecError(Exception):
    """Bad spec: raised before any NX geometry is touched."""


# -----------------------------------------------------------------------------
# logging
# -----------------------------------------------------------------------------
class Log:
    """Console + optional file log, with a failure tally.

    Every line is prefixed so a caller can grep the log, and errors are counted
    so the journal cannot end 'successfully' after reporting a problem.
    """

    def __init__(self, path=None):
        self.lines = []
        self.errors = []
        self.warnings = []
        self.path = path
        self._fh = None
        if path:
            try:
                self._fh = open(path, "w", encoding="utf-8")
            except OSError as exc:
                self.path = None
                self.warn("cannot open log file %s: %s" % (path, exc))

    def _emit(self, tag, msg):
        line = "%s %s" % (tag, msg)
        print(line)
        sys.stdout.flush()
        self.lines.append(line)
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()

    def ok(self, msg):
        self._emit("[ok]  ", msg)

    def chk(self, msg):
        self._emit("[chk] ", msg)

    def warn(self, msg):
        self._emit("[WARN]", msg)
        self.warnings.append(msg)

    def err(self, msg):
        self._emit("[FAIL]", msg)
        self.errors.append(msg)

    def info(self, msg):
        self._emit("[..]  ", msg)

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


# -----------------------------------------------------------------------------
# environment
# -----------------------------------------------------------------------------
def base_dir():
    """$UGII_BASE_DIR, or a message a human can act on."""
    d = os.environ.get("UGII_BASE_DIR")
    if not d:
        raise SpecError(
            "UGII_BASE_DIR is not set. Run the journal through NX "
            "($UGII_BASE_DIR/NXBIN/run_journal.exe) or export UGII_BASE_DIR first."
        )
    if not os.path.isdir(d):
        raise SpecError("UGII_BASE_DIR points at a missing directory: %s" % d)
    return d


# -----------------------------------------------------------------------------
# spec loading
# -----------------------------------------------------------------------------
def load_spec(argv, default=None):
    """Build a spec from an optional JSON file named on the command line.

    argv is sys.argv. With no arguments the default spec is returned unchanged,
    which is what keeps old invocations working.
    """
    spec = json.loads(json.dumps(default or DEFAULT_PLATE))  # deep copy
    rest = list(argv[1:])
    # Unknown options are REJECTED rather than ignored. Silently dropping them
    # meant a typo like `-arg spec.json` fell through to the built-in defaults and
    # quietly built the wrong part - exactly the silent-wrong-model failure this
    # skill exists to prevent. run_journal.exe passes user arguments through
    # untouched, so anything starting with "-" here is a mistake.
    bad = [a for a in rest if a.startswith("-")]
    if bad:
        raise SpecError("unexpected option %r - this takes at most one spec file "
                        "path and nothing else" % bad[0])
    if not rest:
        return spec, "built-in defaults"
    if len(rest) > 1:
        raise SpecError("expected at most one spec file, got %d: %r" % (len(rest), rest))
    path = rest[0]
    if not os.path.isfile(path):
        raise SpecError("spec file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
    except ValueError as exc:
        raise SpecError("spec file is not valid JSON: %s (%s)" % (path, exc))
    if not isinstance(loaded, dict):
        raise SpecError("spec file must contain a JSON object: %s" % path)
    return _merge(spec, loaded), path


def _merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


# -----------------------------------------------------------------------------
# validation - catch parameter conflicts before NX sees them
#
# Everything here delegates to the recipe registered for the spec's part type,
# so adding a second part type means registering it in nx_recipes.py: no
# journal changes. The part-generic entry points below are what journals should
# call; validate_plate / plate_metrics are kept as thin aliases for old callers.
# -----------------------------------------------------------------------------
def known_parts():
    """Part types this skill can build."""
    return recipes.known_parts()


def part_type_of(spec):
    """The recipe name a spec asks for, defaulting to the mounting plate."""
    return spec.get("part") or recipes.DEFAULT_PART


def validate_part(spec):
    """Problems with a spec as human-readable strings. Empty list = buildable.

    It takes the whole spec rather than just params, so an unknown part type is
    reported through the same channel as a bad parameter - one list of strings -
    instead of an exception the journals would have to remember to catch.
    """
    part_type = part_type_of(spec)
    if not recipes.has_recipe(part_type):
        return [recipes.unknown_part_message(part_type)]

    params = spec.get("params")
    if params is None:
        params = {}
    elif not isinstance(params, dict):
        return ["'params' must be an object mapping parameter names to numbers, "
                "got %s" % type(params).__name__]

    return recipes.validate(part_type, params)


def part_metrics(spec):
    """Analytic (volume, face count) for this spec's part type."""
    return _recipe_call(spec, recipes.metrics, "expected geometry")


def cylindrical_faces(spec):
    """How many cylindrical faces the verifier should find, per the recipe."""
    return _recipe_call(spec, recipes.cylindrical_faces, "cylindrical face count")


def _recipe_call(spec, fn, what):
    part_type = part_type_of(spec)
    try:
        params = spec["params"]
    except KeyError:
        raise SpecError("spec has no 'params', so %s cannot be computed" % what)
    try:
        return fn(part_type, params)
    except recipes.RecipeError as exc:
        raise SpecError(str(exc))


def validate_plate(params):
    """Deprecated alias: validate mounting-plate parameters alone."""
    return recipes.validate(recipes.PLATE, params)


def plate_metrics(params):
    """Deprecated alias: analytic (volume, faces) for the mounting plate."""
    return recipes.metrics(recipes.PLATE, params)


# -----------------------------------------------------------------------------
# output paths and structured result
# -----------------------------------------------------------------------------
def resolve_out_dir(spec):
    """Absolute output directory for a spec.

    Expands `~` and anchors relative paths, so a spec can say "~/nx_out" or
    "./out" and get what a person expects. Without this, "~/nx_out" is taken
    literally and creates a directory actually named "~". A relative path is
    resolved against the CURRENT directory, which under run_journal.exe is the
    script's own directory - so the default spec uses an absolute, home-based
    path rather than a bare name.
    """
    raw = spec["out_dir"]
    if not isinstance(raw, str) or not raw.strip():
        raise SpecError("'out_dir' must be a non-empty string, got %r" % (raw,))
    return os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))


def paths_for(spec):
    out_dir = resolve_out_dir(spec)
    name = spec["part_name"]
    return {
        "out_dir": out_dir,
        "prt": os.path.join(out_dir, name + ".prt"),
        "step": os.path.join(out_dir, name + ".step"),
        # .run.log, not .log: step214ug.exe writes its own sidecar <basename>.log
        # next to the .step, and holding a handle to that same path breaks it.
        "log": os.path.join(out_dir, name + ".run.log"),
        "result": os.path.join(out_dir, name + ".result.json"),
        "result_verify": os.path.join(out_dir, name + ".verify.result.json"),
    }


def write_result(path, payload):
    payload = dict(payload)
    payload["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
        return True
    except OSError as exc:
        print("[WARN] cannot write result file %s: %s" % (path, exc))
        return False


def finish(log, result_path, payload, started):
    """Write the result file, then exit non-zero if anything failed.

    sys.exit(non-zero) becomes shell exit code 1 under run_journal.exe - the exact
    number is not propagated, so the result JSON carries the detail instead.
    """
    payload.setdefault("warnings", list(log.warnings))
    payload["errors"] = list(log.errors)
    payload["seconds"] = round(time.time() - started, 3)
    payload["status"] = "failed" if log.errors else "ok"
    write_result(result_path, payload)
    log.close()
    if log.errors:
        print("[FAIL] %d error(s) - see %s" % (len(log.errors), result_path))
        sys.stdout.flush()
        sys.exit(1)
    return payload
