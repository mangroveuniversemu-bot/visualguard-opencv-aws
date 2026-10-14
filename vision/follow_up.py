"""Non-executing workflow adapter for bounded OpenCV inspection evidence."""

from __future__ import annotations


def plan_follow_up(
    inspection_result: object,
    *,
    consequence_result: object | None = None,
) -> dict[str, object]:
    """Convert vision evidence into a fail-closed follow-up plan.

    The adapter makes the judging-relevant dependency explicit: OpenCV output
    changes the next workflow action. It never performs an external or physical
    action, and malformed or contradictory evidence fails closed.
    """
    if not isinstance(inspection_result, dict):
        return _hold("INVALID_INSPECTION_RESULT")
    decision = inspection_result.get("decision")
    reason = inspection_result.get("reason")
    if not isinstance(reason, str) or decision not in {
        "REVIEW",
        "REQUEST_VIEW",
        "STOP",
    }:
        return _hold("INVALID_INSPECTION_RESULT")
    if consequence_result is not None:
        if not isinstance(consequence_result, dict):
            return _hold("INVALID_CONSEQUENCE_RESULT")
        if consequence_result.get("closure") != "MATCH":
            consequence_reason = consequence_result.get("reason")
            return _hold(
                consequence_reason
                if isinstance(consequence_reason, str)
                else "INVALID_CONSEQUENCE_RESULT"
            )
    action_by_decision = {
        "REVIEW": "QUEUE_HUMAN_REVIEW",
        "REQUEST_VIEW": "REQUEST_NEW_CAPTURE",
        "STOP": "HOLD_AUTOMATION",
    }
    return {
        "planned_action": action_by_decision[decision],
        "trigger": reason,
        "action_executed": False,
        "physical_action": "NONE",
    }


def _hold(trigger: str) -> dict[str, object]:
    return {
        "planned_action": "HOLD_AUTOMATION",
        "trigger": trigger,
        "action_executed": False,
        "physical_action": "NONE",
    }
