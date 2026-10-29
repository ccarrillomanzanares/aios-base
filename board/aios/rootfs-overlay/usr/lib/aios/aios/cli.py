"""Punto de entrada de `aios`: reparte a los espacios (net, ui...)."""
import argparse
import sys

from . import ai, net, ui, update
from .result import fail


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(f"{self.prog}: {message}")


def main(argv=None):
    p = Parser(prog="aios", description="AIOS system command line")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="space", required=True)
    ai.register(sub)
    net.register(sub)
    ui.register(sub)
    update.register(sub)
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv  # vale en cualquier posición: aios net status --json
    try:
        args = p.parse_args([a for a in argv if a != "--json"])
    except UsageError as e:
        return fail("USAGE", "Run: aios --help", {"error": str(e)}, text=str(e)).emit(as_json)
    args.json = as_json
    try:
        result = args.func(args)
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as e:  # el contrato JSON se mantiene aunque algo falle
        result = fail("INTERNAL_ERROR", "Run: aios-diag", {"error": f"{type(e).__name__}: {e}"})
    return result.emit(args.json)


if __name__ == "__main__":
    sys.exit(main())
