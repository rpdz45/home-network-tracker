"""Result presentation used by the session-bound HTTP confirmation boundary."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException

from nettracker.routers.control import AccessControlError
from nettracker.routers.livebox5 import LiveboxError
from nettracker.routers.livebox5_access import ScheduleState
from nettracker.routers.livebox5_control import ControlResult

FAILURE_DETAIL = "Commande refusée ou résultat incertain ; ne pas relancer automatiquement"


@dataclass(frozen=True)
class ControlResultView:
    title: str
    change: str
    schedule: str
    warning: str


def describe_control_result(result: object, *, blocked: bool) -> ControlResultView:
    """Validate the returned state against the server-owned action, not HTTP fields."""
    if (
        type(blocked) is not bool
        or not isinstance(result, ControlResult)
        or type(result.changed) is not bool
        or not isinstance(result.state, ScheduleState)
    ):
        raise AccessControlError("invalid control result")
    state = result.state
    desired = "Disable" if blocked else ""
    if (
        state.override != desired
        or state.value not in {"Enable", "Disable"}
        or (blocked and not state.blocked)
    ):
        raise AccessControlError("control result does not match the confirmed action")
    change = "Modification effectuée" if result.changed else "Etat déjà conforme, sans modification"
    if blocked:
        schedule = "Forçage de blocage présent ; calendrier lu : accès désactivé."
    elif state.blocked:
        schedule = "Aucun forçage ; calendrier lu : accès désactivé."
    else:
        schedule = "Aucun forçage ; calendrier lu : accès activé."
    return ControlResultView(
        title="Résultat du contrôle Livebox",
        change=change,
        schedule=schedule,
        warning="Cet état de calendrier ne prouve pas l'accès Internet effectif.",
    )


def confirmed_result_view(
    operation: Callable[[], ControlResult], *, blocked: bool
) -> ControlResultView:
    """Invoke once; callers must supply an already session-bound confirmation.

    This standalone helper does not authenticate, prepare, consume tokens or
    retry. HTTP routes instead use livebox_execution.confirm_livebox_result,
    which obtains the server-owned action from confirm_with_request and calls
    describe_control_result directly. Neither helper constructs an adapter.
    """
    if type(blocked) is not bool:
        raise HTTPException(409, FAILURE_DETAIL)
    try:
        return describe_control_result(operation(), blocked=blocked)
    except (AccessControlError, LiveboxError):
        raise HTTPException(409, FAILURE_DETAIL) from None
