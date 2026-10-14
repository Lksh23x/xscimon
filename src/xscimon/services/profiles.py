import math
from sqlmodel import Session
from ..adapters.base import XAPIAdapter
from ..models import Account, LogEventType
from ..repositories import AccountRepo, LogRepo

# X API v2 GET /2/users/by accepts at most 100 usernames per request.
USERS_PER_LOOKUP = 100


def lookup_cost(n_accounts: int) -> int:
    """API calls needed to batch-look-up n accounts."""
    return math.ceil(n_accounts / USERS_PER_LOOKUP)


class ProfileService:
    """Batch-resolves X profiles (user id, bio, followers) for stored accounts."""

    def __init__(self, session: Session, x_api: XAPIAdapter):
        self._x = x_api
        self._accounts = AccountRepo(session)
        self._log = LogRepo(session)

    def refresh(self, accounts: list[Account], domain_id: int | None = None,
                reason: str = "Profile lookup") -> dict:
        """Look up `accounts` in batches of 100 and store x_user_id and followers.
        A bio is only filled in when the account has none, so imported or edited
        descriptions are kept. X API errors propagate to the caller."""
        if not accounts:
            return {"found": 0, "not_found": [], "api_calls": 0}

        profiles, calls = self._x.lookup_users([a.handle for a in accounts])
        self._log.write(LogEventType.api_call,
                        f"{reason}: looked up {len(accounts)} account(s) "
                        f"in {calls} call(s)",
                        domain_id=domain_id, call_count=calls)

        found, not_found = 0, []
        for account in accounts:
            profile = profiles.get(account.handle.lower())
            if profile is None:
                not_found.append(account.handle)
                continue
            self._accounts.update_profile(
                account.id,
                profile.description if account.description is None else None,
                profile.user_id,
                profile.followers_count,
            )
            found += 1

        if not_found:
            self._log.write(LogEventType.error,
                            f"{reason}: not found on X: "
                            + ", ".join(f"@{h}" for h in not_found),
                            domain_id=domain_id)
        return {"found": found, "not_found": not_found, "api_calls": calls}
