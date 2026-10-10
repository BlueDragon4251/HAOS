"""Refuse model/gateway execution before a protected, separate owner is enrolled."""

import os

from .owner_recovery import RecoveryCodes, enrolled_owner, owners


def main():
    if os.geteuid() != 0:
        raise PermissionError("owner readiness is checked only by the privileged service boundary")
    records = owners()
    if not records:
        raise PermissionError("complete initial owner onboarding at the recovery console before enabling Hermes")
    recovery = RecoveryCodes()._load()
    for record in records:
        entry = enrolled_owner(record["username"])
        if not recovery["owners"].get(str(entry.pw_uid), {}).get("hashes"):
            raise PermissionError("issue and store owner recovery codes before autonomous execution")


if __name__ == "__main__":
    main()
