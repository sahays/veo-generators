"""Production cost accumulation utilities."""

import deps


def accumulate_cost(production_id: str, cost_usd: float):
    """Add cost to the production's total_usage."""
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    current = production.total_usage.cost_usd if production.total_usage else 0.0
    deps.firestore_svc.update_production(
        production_id, {"total_usage.cost_usd": current + cost_usd}
    )


def accumulate_image_cost(production_id: str, cost_per_image: float):
    """Track image generation cost breakdown on total_usage."""
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    usage = production.total_usage
    deps.firestore_svc.update_production(
        production_id,
        {
            "total_usage.cost_usd": (usage.cost_usd if usage else 0.0) + cost_per_image,
            "total_usage.image_generations": (usage.image_generations if usage else 0)
            + 1,
            "total_usage.image_cost_usd": (usage.image_cost_usd if usage else 0.0)
            + cost_per_image,
        },
    )


def accumulate_veo_cost(production_id: str, duration_seconds: int, unit_cost: float):
    """Track Veo video generation cost breakdown on total_usage."""
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    usage = production.total_usage
    veo_cost = duration_seconds * unit_cost
    deps.firestore_svc.update_production(
        production_id,
        {
            "total_usage.cost_usd": (usage.cost_usd if usage else 0.0) + veo_cost,
            "total_usage.veo_videos": (usage.veo_videos if usage else 0) + 1,
            "total_usage.veo_seconds": (usage.veo_seconds if usage else 0)
            + duration_seconds,
            "total_usage.veo_unit_cost": unit_cost,
            "total_usage.veo_cost_usd": (usage.veo_cost_usd if usage else 0.0)
            + veo_cost,
        },
    )
