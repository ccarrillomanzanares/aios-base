"""Punto de entrada de `aios`: reparte a los espacios (net, ui...)."""
import argparse
import sys

from . import ai, audio, bt, net, sys as aios_sys, ui, update
from .result import fail


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(f"{self.prog}: {message}")


def build_parser():
    p = Parser(prog="aios", description="AIOS system command line")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="space", required=True)
    for space in (ai, audio, bt, net, aios_sys, ui, update):
        space.register(sub)
    return p


def validate(argv):
    """None si la orden existe y sus argumentos son válidos; si no, el error.
    El agente lo usa antes de pedir confirmación: no se pregunta por órdenes
    que no existen, y el modelo recibe el error para corregirse."""
    try:
        build_parser().parse_args([a for a in argv if a != "--json"])
        return None
    except UsageError as e:
        return str(e)
    except SystemExit:  # --help y similares
        return "help requested"


def main(argv=None):
    p = build_parser()
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
