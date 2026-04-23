from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Set

READ = "read"
NETWORK = "network"
WRITE_ARTIFACT = "write_artifact"
DESTRUCTIVE = "destructive"

DEFAULT_ALLOWED = {READ}
INTERACTIVE_PERMISSIONS = {NETWORK, WRITE_ARTIFACT}


class PermissionDenied(PermissionError):
    pass


@dataclass
class PermissionDecision:
    permission: str
    allowed: bool
    reason: str
    mode: str

    def to_dict(self) -> dict:
        return {
            "permission": self.permission,
            "allowed": self.allowed,
            "reason": self.reason,
            "mode": self.mode,
        }


class PermissionPolicy:
    def __init__(
        self,
        allowed: Optional[Iterable[str]] = None,
        interactive: bool = False,
        input_func: Callable[[str], str] = input,
        allow_destructive: bool = False,
    ) -> None:
        self.allowed: Set[str] = set(DEFAULT_ALLOWED)
        if allowed:
            self.allowed.update(item.strip() for item in allowed if item and item.strip())
        self.interactive = interactive
        self.input_func = input_func
        self.allow_destructive = allow_destructive
        self.decisions: List[PermissionDecision] = []

    @classmethod
    def from_csv(cls, raw: str, interactive: bool = False) -> "PermissionPolicy":
        values = [item.strip() for item in raw.split(",") if item.strip()]
        return cls(values, interactive=interactive)

    def require(self, permission: str, reason: str) -> None:
        if permission == DESTRUCTIVE and not self.allow_destructive:
            self._record(permission, False, reason, "blocked")
            raise PermissionDenied("Permission '{0}' is blocked by default: {1}".format(permission, reason))

        if permission in self.allowed:
            self._record(permission, True, reason, "allowed")
            return

        if self.interactive and permission in INTERACTIVE_PERMISSIONS:
            if self._ask(permission, reason):
                self.allowed.add(permission)
                self._record(permission, True, reason, "interactive")
                return
            self._record(permission, False, reason, "interactive")
            raise PermissionDenied("Permission '{0}' denied interactively: {1}".format(permission, reason))

        self._record(permission, False, reason, "denied")
        raise PermissionDenied(
            "Permission '{0}' is required: {1}. Use --allow {0} or --allow read,{0}.".format(permission, reason)
        )

    def to_trace(self) -> List[dict]:
        return [decision.to_dict() for decision in self.decisions]

    def _ask(self, permission: str, reason: str) -> bool:
        answer = self.input_func("Allow permission '{0}' for {1}? [y/N] ".format(permission, reason))
        return answer.strip().lower() in {"y", "yes"}

    def _record(self, permission: str, allowed: bool, reason: str, mode: str) -> None:
        self.decisions.append(PermissionDecision(permission, allowed, reason, mode))
