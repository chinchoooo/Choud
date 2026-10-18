"""Desktop sync client for the Personal Cloud server.

Talks to the server's HTTP API only (never the storage engine) and owns the
local half of synchronization: watching a folder, remembering what was last
synced, and reconciling it against the server. See docs/synchronization.md.
"""

__version__ = "0.4.0"
