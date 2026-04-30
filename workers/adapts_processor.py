"""Adapts job processor — generates image variants across multiple aspect ratios."""

import logging

import deps
from base_processor import JobProcessor

logger = logging.getLogger(__name__)


class AdaptsProcessor(JobProcessor):
    """Processes pending adapt jobs."""

    @property
    def name(self) -> str:
        return "adapts"

    @property
    def firestore_update_method(self) -> str:
        return "update_adapt_record"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_adapt_records(include_archived=False)

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

        usage_acc = self._generate_variants(
            record, record_id, variants, pending_indices
        )
        status = self._resolve_status(variants)
        usage = self._merge_usage(record, usage_acc)

        updates = {
            "variants": variants,
            "status": status,
            "progress_pct": 100,
            "usage": usage,
        }
        self._set_completion_timestamp(updates, status)
        deps.firestore_svc.update_adapt_record(record_id, updates)
        logger.info(
            f"[adapts:{record_id}] {status}: "
            f"{sum(1 for v in variants if v['status'] == 'completed')}"
            f"/{len(variants)} variants"
        )

    def _generate_variants(self, record, record_id, variants, pending_indices):
        """Generate each variant sequentially, accumulating per-variant usage."""
        acc = {
            "image_generations": 0,
            "image_input_tokens": 0,
            "image_output_tokens": 0,
            "image_cost_usd": 0.0,
            "cost_usd": 0.0,
            "model_name": "",
        }
        for step, idx in enumerate(pending_indices):
            variant_usage = self._generate_single_variant(
                record, record_id, variants, idx
            )
            if variant_usage:
                acc["image_generations"] += 1
                acc["image_input_tokens"] += variant_usage.get("image_input_tokens", 0)
                acc["image_output_tokens"] += variant_usage.get(
                    "image_output_tokens", 0
                )
                acc["image_cost_usd"] += variant_usage.get("image_cost_usd", 0.0)
                acc["cost_usd"] += variant_usage.get("cost_usd", 0.0)
                acc["model_name"] = (
                    variant_usage.get("model_name", "") or acc["model_name"]
                )
            self._update_progress(record_id, variants, step + 1, len(pending_indices))
        return acc

    def _generate_single_variant(self, record, record_id, variants, idx):
        """Generate one aspect-ratio variant. Returns usage dict on success, None on failure."""
        v = variants[idx]
        try:
            wrapper = self._run_async(
                self._call_gemini(
                    record.source_gcs_uri,
                    record.source_mime_type,
                    v["aspect_ratio"],
                    record.template_gcs_uri,
                    record.prompt_id,
                    model_id=getattr(record, "model_id", None),
                    region=getattr(record, "region", None),
                )
            )
            data = wrapper.data
            variants[idx]["status"] = "completed"
            variants[idx]["output_gcs_uri"] = data["image_url"]
            variants[idx]["prompt_text_used"] = data.get("prompt_text_used", "")
            return wrapper.usage.dict()
        except Exception as e:
            variants[idx]["status"] = "failed"
            variants[idx]["error_message"] = str(e)
            logger.error(
                f"[adapts:{record_id}] variant {v['aspect_ratio']} failed: {e}"
            )
            return None

    def _update_progress(self, record_id, variants, step, total_steps):
        """Persist variant state and progress percentage to Firestore."""
        pct = int((step / total_steps) * 90) + 5
        deps.firestore_svc.update_adapt_record(
            record_id, {"variants": variants, "progress_pct": pct}
        )

    @staticmethod
    def _resolve_status(variants) -> str:
        """Determine aggregate status from individual variant statuses."""
        total = len(variants)
        total_completed = sum(1 for v in variants if v["status"] == "completed")
        total_failed = sum(1 for v in variants if v["status"] == "failed")
        if total_completed == total:
            return "completed"
        if total_failed == total:
            return "failed"
        return "partial"

    @staticmethod
    def _merge_usage(record, acc: dict) -> dict:
        """Merge per-run accumulator into the record's existing usage dict."""
        usage = record.usage.dict()
        usage["image_generations"] = (
            usage.get("image_generations", 0) + acc["image_generations"]
        )
        usage["image_input_tokens"] = (
            usage.get("image_input_tokens", 0) + acc["image_input_tokens"]
        )
        usage["image_output_tokens"] = (
            usage.get("image_output_tokens", 0) + acc["image_output_tokens"]
        )
        usage["image_cost_usd"] = (
            usage.get("image_cost_usd", 0.0) + acc["image_cost_usd"]
        )
        usage["cost_usd"] = usage.get("cost_usd", 0.0) + acc["cost_usd"]
        if acc.get("model_name"):
            usage["model_name"] = acc["model_name"]
        return usage

    async def _call_gemini(
        self,
        source_gcs_uri,
        source_mime_type,
        aspect_ratio,
        template_gcs_uri,
        prompt_id,
        model_id=None,
        region=None,
    ):
        """Call Gemini to generate a single adapt variant. Returns the full response wrapper."""
        return await deps.ai_svc.generate_adapt(
            source_gcs_uri=source_gcs_uri,
            source_mime_type=source_mime_type,
            aspect_ratio=aspect_ratio,
            template_gcs_uri=template_gcs_uri,
            prompt_id=prompt_id,
            model_id=model_id,
            region=region,
        )
