"""CLI entrypoint for finance_tooling."""

from finance_tooling.core import healthcheck


def main() -> int:
    """Run a minimal CLI smoke command."""
    status = healthcheck()
    print(f"finance_tooling: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
