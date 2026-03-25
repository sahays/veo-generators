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

    def __init__(self, processors: list[JobProcessor]):
        self.processors = processors
        self.running = False

    def start(self) -> None:
        self.running = True

        logger.info("=" * 60)
        logger.info("VeoGen Worker Started")
        logger.info(f"Poll interval: {POLL_INTERVAL}s")
        logger.info(f"Max concurrent: {MAX_CONCURRENT}")
        logger.info(f"Processors: {[p.name for p in self.processors]}")
        logger.info("=" * 60)

        try:
            while self.running:
                self._poll_cycle()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.stop()

    def stop(self) -> None:
        self.running = False
        logger.info("VeoGen Worker Stopped")

    def _poll_cycle(self) -> None:
        for processor in self.processors:
            try:
                records = processor.get_pending_records()
                pending = [r for r in records if r.status == "pending"]

                for record in pending[:MAX_CONCURRENT]:
                    logger.info(f"[{processor.name}:{record.id}] Picking up job")
                    try:
                        processor.process(record)
                    except Exception as e:
                        tb = traceback.format_exc()
                        logger.error(
                            f"[{processor.name}:{record.id}] Failed: {e}\n{tb}"
                        )
                        processor.mark_failed(record.id, str(e))
            except Exception as e:
                logger.error(f"Error polling {processor.name}: {e}")
                logger.error(traceback.format_exc())


def main() -> None:
    from health import start_health_server

    start_health_server()

    import deps

    deps.init_services()

    from reframe_processor import ReframeProcessor
    from promo_processor import PromoProcessor

    worker = UnifiedWorker([ReframeProcessor(), PromoProcessor()])
    worker.start()


if __name__ == "__main__":
    main()
