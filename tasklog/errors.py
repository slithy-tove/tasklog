"""Shared exception type.

Anything the user did wrong (bad ID, missing project, malformed date) raises TasklogError.
The CLI catches it and prints a one-line message instead of a traceback.
"""


class TasklogError(Exception):
    """A user-facing error. The message is shown as-is."""
