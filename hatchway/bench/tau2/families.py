"""Scenario families and primary-action incidence of τ² tasks, for the targeted experiment.

A **scenario family** groups the tasks that share an underlying scenario, so that a train/test
split never puts two variants of one scenario on opposite sides:

- telecom: the task id without its persona. A telecom id is `[category]issue|issue…[PERSONA:p]`;
  persona variants of one issue combination are the same scenario. (Every telecom task runs on
  the same customer, C1001, so the customer is no family.)
- retail: the user who owns the orders the reference plan acts on, read from the domain's
  initial database. One user's tasks share their orders and payment methods.

**Primary-action incidence** is which primary actions a task's reference plan has the
assistant call. It comes from the task definition alone, never from a run.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache
from typing import Any

PRIMARY_ACTIONS = ("return_delivered_order_items", "enable_roaming", "refuel_data")
DESCRIPTIVE_ACTIONS = ("send_payment_request",)
DOMAIN_OF = {
    "return_delivered_order_items": "retail",
    "enable_roaming": "telecom",
    "refuel_data": "telecom",
    "send_payment_request": "telecom",
}

_PERSONA = re.compile(r"\[PERSONA:[^\]]*\]$")


def reference_actions(task: Any, actions: Iterable[str]) -> tuple[str, ...]:
    """The listed actions the task's reference plan has the assistant call, sorted."""
    wanted = set(actions)
    return tuple(
        sorted(
            {
                a.name
                for a in (task.evaluation_criteria.actions or [])
                if a.requestor == "assistant" and a.name in wanted
            }
        )
    )


def incidence(task: Any) -> tuple[str, ...]:
    """Primary actions in the task's reference plan."""
    return reference_actions(task, PRIMARY_ACTIONS)


@cache
def _retail_order_owners() -> dict[str, str]:
    from tau2.registry import registry

    db = registry.get_env_constructor("retail")().tools.db
    return {order_id: order.user_id for order_id, order in db.orders.items()}


def scenario_family(domain: str, task: Any) -> str:
    """The task's scenario family id (see the module docstring)."""
    if domain == "telecom":
        return f"telecom/{_PERSONA.sub('', task.id)}"
    if domain == "retail":
        owners = _retail_order_owners()
        users = {
            owners[a.arguments["order_id"]]
            for a in (task.evaluation_criteria.actions or [])
            if a.requestor == "assistant" and a.arguments.get("order_id") in owners
        }
        if len(users) != 1:
            raise ValueError(f"retail task {task.id}: reference orders of {sorted(users)} users")
        return f"retail/user:{users.pop()}"
    raise ValueError(f"no scenario family rule for domain {domain!r}")
