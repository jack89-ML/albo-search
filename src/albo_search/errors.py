"""Error taxonomy for albo-search.

Exit-code contract (POSIX):
  0  search completed, >= 1 match
  1  search completed, zero matches (verified negative)
  2  operational error
"""

from __future__ import annotations


class RegistryError(Exception):
    """Operational failure: network, upstream block, invalid input, parse failure.

    Always maps to exit code 2. Never used for a verified empty result.
    """


class TransportMissing(RegistryError):
    """A source requires the optional browser extra (playwright)."""


class ParseFailure(RegistryError):
    """Upstream responded but the response could not be understood.

    Raised instead of reporting a (possibly wrong) 'zero matches'.
    """


class UpstreamBlocked(RegistryError):
    """Upstream refused the request (timeout / anti-bot / HTTP error)."""


def exit_code(completed: bool, found: int) -> int:
    """Map a finished search to its exit code."""
    if not completed:
        return 2
    return 0 if found > 0 else 1
