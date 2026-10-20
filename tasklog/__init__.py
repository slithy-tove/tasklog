"""tasklog: an offline, on-demand command-line time tracker.

Modules, in rough dependency order:
  errors.py    the one exception type used for user-facing errors
  store.py     reading and writing the data files (the only module that touches disk)
  lookup.py    name validation, project-path resolution, ID matching
  timeparse.py date and time string parsing
  report.py    the `report` command (sums, filters, sweeps)
  commands.py  the other commands (cd, ls, create, start, stop, ...)
  helpdocs.py  long-form help text
  cli.py       argument parsing and dispatch; `main()` is the entry point
"""
__version__ = "0.1.0"
