"""
Unified Worker — polls Firestore for pending jobs and dispatches to processors.
Runs as a standalone Cloud Run service.
"""

import sys
from pathlib import Path

# Add api/ to Python path so processors can import deps, models, etc.
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

import logging
import os
import time
import traceback

from base_processor import JobProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL", "5"))
MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "1"))


class UnifiedWorker:
    """Polls Firestore for pending jobs and dispatches to registered processors."""

    def __init__(self, processors: list[JobProcessor]) -> None:
        self.processors = processors
        self.running = False

    def start(self) -> None:
        self.running = True
        names = [p.name for p in self.processors]
        logger.info(
            f"VeoGen Worker Started (poll={POLL_INTERVAL}s, max_concurrent={MAX_CONCURRENT}, processors={names})",
            extra={
                "who": "unified_worker",
                "where": "start",
                "what": "worker_start",
                "why": "service_boot",
                "how": "poll_loop",
            },
        )
        try:
            while self.running:
                self._poll_cycle()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info(
                "Received shutdown signal",
                extra={
                    "who": "unified_worker",
                    "where": "start",
                    "what": "sigint",
                    "why": "keyboard_interrupt",
                    "how": "stop",
                },
            )
            self.stop()

    def stop(self) -> None:
        self.running = False
        logger.info(
            "VeoGen Worker Stopped",
            extra={
                "who": "unified_worker",
                "where": "stop",
                "what": "worker_stop",
                "why": "shutdown",
                "how": "flag_reset",
            },
        )

    def _poll_cycle(self) -> None:
        for processor in self.processors:
            try:
                records = processor.get_pending_records()
                pending = [r for r in records if r.status == "pending"]
                for record in pending[:MAX_CONCURRENT]:
                    logger.info(
                        f"[{processor.name}:{record.id}] Picking up job",
                        extra={
                            "who": processor.name,
                            "where": "_poll_cycle",
                            "what": f"pickup:{record.id}",
                            "why": "pending_record",
                            "how": "process",
                        },
                    )
                    try:
                        processor.process(record)
                    except Exception as e:
                        tb = traceback.format_exc()
                        logger.error(
                            f"[{processor.name}:{record.id}] Failed: {e}\n{tb}",
                            extra={
                                "who": processor.name,
                                "where": "_poll_cycle",
                                "what": f"failed:{record.id}",
                                "why": str(e),
                                "how": "mark_failed",
                            },
                        )
                        processor.mark_failed(record.id, str(e))
            except Exception as e:
                logger.error(
                    f"Error polling {processor.name}: {e}\n{traceback.format_exc()}",
                    extra={
                        "who": processor.name,
                        "where": "_poll_cycle",
                        "what": "poll_error",
                        "why": str(e),
                        "how": "skip_cycle",
                    },
                )


def main() -> None:
    from health import start_health_server

    start_health_server()
    import deps

    deps.init_services()
    try:
        reclaimed = deps.firestore_svc.reclaim_orphan_avatar_turns()
        if reclaimed:
            logger.info(
                f"Reclaimed {reclaimed} orphan avatar turn(s)",
                extra={
                    "who": "unified_worker",
                    "where": "main",
                    "what": f"reclaimed={reclaimed}",
                    "why": "worker_restart",
                    "how": "reclaim_orphan_avatar_turns",
                },
            )
    except Exception as e:
        logger.warning(
            f"Avatar orphan reclaim failed: {e}",
            extra={
                "who": "unified_worker",
                "where": "main",
                "what": "reclaim_failed",
                "why": str(e),
                "how": "ignore_and_continue",
            },
        )

    from adapts_processor import AdaptsProcessor
    from avatar_processor import AvatarProcessor
    from dubbing_processor import DubbingProcessor
    from promo_processor import PromoProcessor
    from reframe_processor import ReframeProcessor

    worker = UnifiedWorker(
        [
            ReframeProcessor(),
            PromoProcessor(),
            AdaptsProcessor(),
            AvatarProcessor(),
            DubbingProcessor(),
        ]
    )
    worker.start()


if __name__ == "__main__":
    main()
