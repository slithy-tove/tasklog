# tasklog

An offline, on-demand command-line time tracker. It has no daemon, needs no network,
and does nothing unless you run it.

## Install

```
pip install -e .
tasklog help
```

## Quick start

```
tasklog create -p work            # project "work"
tasklog cd work
tasklog create -t website         # prints the new task's ID, e.g. 3f9a2c
tasklog 3f start                  # partial IDs work
tasklog 3f stop
tasklog 3f label billing
tasklog 3f manual today::09:00:00 today::10:30:00
tasklog                           # details of the running task (same as: tasklog ACTIVE info)
tasklog ACTIVE stop               # ACTIVE means whatever task is running
tasklog 3f info                   # details and time blocks for a task
tasklog 3f complete               # mark a task done (tasklog 3f reopen undoes it)
tasklog 3f edit                   # edit the task's time blocks as JSON in $VISUAL/$EDITOR
tasklog 3f upload notes.pdf       # attach files to a task or project
tasklog 3f download notes.pdf     # copy an attached file into the current folder
tasklog 3f desc                   # opens $VISUAL/$EDITOR (default: vim)
tasklog 3f rename website-v2      # works for projects too
tasklog 3f move /archive          # move a task or project into another project
tasklog 3f delete                 # asks first; -y skips the prompt
tasklog cd
tasklog report -p work -sl        # time on work, split by label
```

Run `tasklog help` for concepts and `tasklog help report` for the report options.
Run `tasklog COMMAND -h` for one command's options.

## Where data lives

`~/.tasklog/` (or `$TASKLOG_HOME`):

| File | Contents | Written when |
|---|---|---|
| `index.jsonl` | project and task headers, including each task's status | creating items, changing labels, completing tasks |
| `blocks.jsonl` | finished time blocks | starting or stopping a timer, adding manual blocks; rewritten by `ID edit` and `ID delete` |
| `state.json` | pointer and running timer | `cd`, `start`, `stop` |
| `desc/<id>.txt` | long descriptions | `ID desc` |
| `files/<id>/` | files attached to a task or project | `ID upload` |

## Upgrading an existing data folder

Data created before task status existed needs one conversion. Run it once, from any folder:

```
python3 /path/to/tasklog/migrate_add_status.py --dry-run   # report only
python3 /path/to/tasklog/migrate_add_status.py             # convert; keeps a backup copy
```

It sets every task's status to `open` and copies the whole data folder to a
`<folder>.backup-<timestamp>` sibling before writing. Running it again is harmless.

## Code map

| Module | Purpose |
|---|---|
| `cli.py` | argument parsing and dispatch |
| `commands.py` | each command's behavior |
| `report.py` | the `report` command: filters, sweeps, output |
| `store.py` | all file reads and writes |
| `lookup.py` | name validation, project paths, partial ID matching |
| `timeparse.py` | date and time strings |
| `helpdocs.py` | long-form help text |
