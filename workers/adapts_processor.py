"""Adapts job processor — generates image variants across multiple aspect ratios."""

import asyncio
import logging

import deps
from base_processor import JobProcessor

logger = logging.getLogger(__name__)

_IMAGE_GEN_COST = 0.039


class AdaptsProcessor(JobProcessor):
    """Processes pending adapt jobs."""

    @property
    def name(self) -> str:
        return "adapts"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_adapt_records(include_archived=False)

    def update_status(
        self, record_id: str, status: str, progress: int, **extra
    ) -> None:
        updates = {"status": status, "progress_pct": progress, **extra}
        self._set_completion_timestamp(updates, status)
        deps.firestore_svc.update_adapt_record(record_id, updates)

    def mark_failed(self, record_id: str, error_message: str) -> None:
        self.update_status(record_id, "failed", 0, error_message=error_message)

    def process(self, record) -> None:
        record_id = record.id
        self.update_status(record_id, "generating", 5)

        variants = [v.dict() for v in record.variants]
        pending_indices = [
            i for i, v in enumerate(variants) if v["status"] == "pending"
        ]

        if not pending_indices:
            self.update_status(record_id, "completed", 100)
            return

        total = len(variants)
        completed = 0
        failed = 0

        # Generate each variant and update progress after each one
        for step, idx in enumerate(pending_indices):
            v = variants[idx]
            try:
                result = asyncio.run(
                    self._generate_one(
                        record.source_gcs_uri,
                        record.source_mime_type,
                        v["aspect_ratio"],
                        record.template_gcs_uri,
                        record.prompt_id,
                    )
                )
                variants[idx]["status"] = "completed"
                variants[idx]["output_gcs_uri"] = result["image_url"]
                variants[idx]["prompt_text_used"] = result.get("prompt_text_used", "")
                completed += 1
            except Exception as e:
                variants[idx]["status"] = "failed"
                variants[idx]["error_message"] = str(e)
                failed += 1
                logger.error(
                    f"[adapts:{record_id}] variant {v['aspect_ratio']} failed: {e}"
                )

            # Update progress after each variant
            pct = int(((step + 1) / len(pending_indices)) * 90) + 5
            deps.firestore_svc.update_adapt_record(
                record_id, {"variants": variants, "progress_pct": pct}
            )

        # Final status
        total_completed = sum(1 for v in variants if v["status"] == "completed")
        total_failed = sum(1 for v in variants if v["status"] == "failed")

        if total_completed == total:
            status = "completed"
        elif total_failed == total:
            status = "failed"
        else:
            status = "partial"

        # Accumulate image generation costs
        usage = record.usage.dict()
        usage["image_generations"] = usage.get("image_generations", 0) + completed
        cost_add = completed * _IMAGE_GEN_COST
        usage["image_cost_usd"] = usage.get("image_cost_usd", 0) + cost_add
        usage["cost_usd"] = usage.get("cost_usd", 0) + cost_add

        updates = {
            "variants": variants,
            "status": status,
            "progress_pct": 100,
            "usage": usage,
        }
        self._set_completion_timestamp(updates, status)
        deps.firestore_svc.update_adapt_record(record_id, updates)
        logger.info(
            f"[adapts:{record_id}] {status}: {total_completed}/{total} variants"
        )

    async def _generate_one(
        self,
        source_gcs_uri,
        source_mime_type,
        aspect_ratio,
        template_gcs_uri,
        prompt_id,
    ):
        result = await deps.ai_svc.generate_adapt(
            source_gcs_uri=source_gcs_uri,
            source_mime_type=source_mime_type,
            aspect_ratio=aspect_ratio,
            template_gcs_uri=template_gcs_uri,
            prompt_id=prompt_id,
        )
        return result.data
