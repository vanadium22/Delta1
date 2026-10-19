"""Compatibility command for exporting the public market-dashboard source archive."""
import argparse

try:
    from .build_public_repository import build_archive
except ImportError:
    from build_public_repository import build_archive


def build(destination=None):
    return build_archive(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    print(build(parser.parse_args().output))
