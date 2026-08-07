"""Foundation entry point for the scheduled dispatcher."""

import structlog

logger = structlog.get_logger()


def main() -> None:
    """Exit successfully until persistent job leases are introduced in Phase 3."""

    logger.info("dispatcher_ready", claimed_jobs=0)


if __name__ == "__main__":
    main()
