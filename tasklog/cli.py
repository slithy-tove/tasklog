"""Command-line entry point: builds the argument parsers and dispatches commands.

Two syntaxes are supported:
  tasklog COMMAND ...     e.g.  tasklog cd work        tasklog report -d today
  tasklog ID VERB ...     e.g.  tasklog 3f start       tasklog 3f manual 09:00:00 10:30:00

To add a new top-level command: write cmd_* in commands.py, add a subparser in
build_main_parser(), and add it to HANDLERS.
"""
import argparse
import sys

from . import commands, helpdocs
from .errors import TasklogError
from .store import Store

ID_VERBS = ("start", "stop", "manual", "label", "complete", "reopen", "edit",
            "desc", "rename", "move", "delete", "info", "upload", "download")

HANDLERS = {
    "cd": commands.cmd_cd,
    "ls": commands.cmd_ls,
    "create": commands.cmd_create,
    "report": commands.cmd_report,
}

ID_HANDLERS = {
    "start": commands.cmd_start,
    "stop": commands.cmd_stop,
    "manual": commands.cmd_manual,
    "label": commands.cmd_label,
    "complete": commands.cmd_complete,
    "reopen": commands.cmd_reopen,
    "edit": commands.cmd_edit,
    "desc": commands.cmd_desc,
    "rename": commands.cmd_rename,
    "move": commands.cmd_move,
    "delete": commands.cmd_delete,
    "info": commands.cmd_info,
    "upload": commands.cmd_upload,
    "download": commands.cmd_download,
}


def build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasklog",
        description="Offline, on-demand command-line time tracker. "
                    "Run 'tasklog help' for concepts and detailed documentation.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    cd = sub.add_parser("cd", help="move the current-project pointer",
                        description="Move the pointer to a project. No argument returns to root.")
    cd.add_argument("project", nargs="?", default="", metavar="PROJECT",
                    help="slash-separated project path, e.g. work/client1; '..' goes up; "
                         "a leading '/' starts from root")

    sub.add_parser("ls", help="list projects and tasks here",
                   description="List the projects and tasks in the current project, with IDs and labels.")

    create = sub.add_parser("create", help="create a project or task here",
                            description="Create a project or a task in the current project.")
    group = create.add_mutually_exclusive_group(required=True)
    group.add_argument("-p", "--project", metavar="NAME", help="name of the new project")
    group.add_argument("-t", "--task", metavar="NAME", help="name of the new task")
    create.add_argument("-l", "--label", metavar="LABEL",
                        help="label for a new task (tasks only; 'none' means no label)")

    report = sub.add_parser(
        "report", help="total time, with filters and sweeps",
        description="Sum tracked time. Filters narrow it; sweeps split it into rows. "
                    "See 'tasklog help report' for the full explanation.",
        epilog="examples:\n"
               "  tasklog report -d today yesterday -l billing\n"
               "  tasklog report -p work -sl\n"
               "  tasklog report -dr 2026-10-15::today -p work/site -sd",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dates = report.add_mutually_exclusive_group()
    dates.add_argument("-d", "--date", nargs="+", metavar="DAY", help="one or more single days")
    dates.add_argument("-dr", "--date-range", nargs=2, metavar=("FROM", "TO"),
                       help="inclusive date range")
    report.add_argument("-l", "--label", nargs="+", metavar="LABEL", help="filter by label(s)")
    report.add_argument("-t", "--task", nargs="+", metavar="ID", help="filter by task ID(s)")
    report.add_argument("-p", "--project", nargs="+", metavar="PROJECT",
                        help="filter by project(s), including subprojects")
    report.add_argument("-sd", "--sweep-date", action="store_true", help="one row per day")
    report.add_argument("-sl", "--sweep-label", action="store_true", help="one row per label")
    report.add_argument("-sp", "--sweep-project", action="store_true", help="one row per project")
    report.add_argument("-st", "--sweep-task", action="store_true", help="one row per task")

    help_cmd = sub.add_parser("help", help="detailed documentation",
                              description="Show detailed documentation, optionally for one topic.")
    help_cmd.add_argument("topic", nargs="?", metavar="TOPIC",
                          help="one of: " + ", ".join(sorted(helpdocs.TOPICS)))
    return parser


def build_id_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasklog ID",
        description="Actions on one task. Put the task ID first, e.g. 'tasklog 3f start'. "
                    "A unique prefix of the ID is enough, and ACTIVE means the running task.",
    )
    sub = parser.add_subparsers(dest="verb", metavar="VERB", required=True)

    sub.add_parser("start", help="start tracking this task")
    sub.add_parser("stop", help="stop tracking this task")

    manual = sub.add_parser("manual", help="add a finished time block",
                            description="Add a time block. Times accept forms such as "
                                        "17:00:00, today::17:00:00, or 2026-10-17::17:00:00. "
                                        "See 'tasklog help dates'.")
    manual.add_argument("start_time", metavar="START")
    manual.add_argument("end_time", metavar="END")

    label = sub.add_parser("label", help="set the label (one per task)",
                           description="Set the label, replacing any previous one. "
                                       "Use 'none' to clear it.")
    label.add_argument("label", metavar="LABEL")

    sub.add_parser("complete", help="mark this task as complete",
                   description="Mark a task complete. A project's completion percentage is "
                               "shown by 'info' on the project.")

    sub.add_parser("reopen", help="mark this task as not complete again")

    sub.add_parser("edit", help="edit this task's time blocks as JSON in the editor",
                   description="Open every time block of a task as a JSON list of "
                               "{\"start\": ..., \"end\": ...} entries in $VISUAL or $EDITOR. "
                               "Blocks can be changed, added or removed. Nothing is saved "
                               "if the JSON is invalid or a block overlaps other time.")

    sub.add_parser("info", help="show details and time blocks (task or project)",
                   description="For a task: its project, label, status, total time and every "
                               "time block. For a project: its contents, completion percentage, "
                               "a completion line for each item directly inside it, and the "
                               "total time and blocks of every task inside it. The "
                               "description is not shown; use 'desc' for it. Both list the "
                               "attached files.")

    upload = sub.add_parser("upload", help="attach files to this task or project",
                            description="Copy files into tasklog's store, keeping their names. "
                                        "Refuses to replace an attached file unless -f is given.")
    upload.add_argument("files", nargs="+", metavar="FILE", help="file(s) to attach")
    upload.add_argument("-f", "--force", action="store_true", help="replace files with the same name")

    download = sub.add_parser("download", help="copy attached files into the current folder",
                              description="Copy attached files (named as shown by 'info') into the "
                                          "folder you are in, so they can be opened. Refuses to "
                                          "overwrite a file here unless -f is given.")
    download.add_argument("names", nargs="+", metavar="FILE", help="attached file name(s)")
    download.add_argument("-f", "--force", action="store_true", help="overwrite files already here")

    sub.add_parser("desc", help="edit the long description (task or project)",
                   description="Open the description in $VISUAL or $EDITOR (default: vim). "
                               "Works on tasks and projects.")

    rename = sub.add_parser("rename", help="rename this task or project",
                            description="Rename a task or project. Renaming a project also "
                                        "updates the paths of everything inside it.")
    rename.add_argument("new_name", metavar="NEW_NAME")

    move = sub.add_parser("move", help="move this task or project into another project",
                          description="Move a task or project into a different project. Moving a "
                                      "project moves everything inside it. A project cannot be "
                                      "moved into itself.")
    move.add_argument("destination", metavar="DESTINATION",
                      help="project to move into: a path such as work/client, '..' for the "
                           "parent, or '/' for root")

    delete = sub.add_parser("delete", help="delete this task or empty project",
                            description="Delete a task (with its time blocks and description) "
                                        "or an empty project. Asks first unless -y/--yes is given.")
    delete.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    store = Store()
    try:
        if argv and argv[0] in ("-h", "--help"):
            print(helpdocs.topic())
            return 0
        if not argv:
            argv = ["ACTIVE", "info"]        # bare `tasklog` shows the running task

        if argv[0] == "help":
            args = build_main_parser().parse_args(argv)
            print(helpdocs.topic(args.topic))
            return 0

        if argv[0] in HANDLERS:
            args = build_main_parser().parse_args(argv)
            HANDLERS[args.command](store, args)
            return 0

        # Otherwise the first word should be a task ID: `tasklog ID VERB ...`
        if argv[0] in ID_VERBS:
            raise TasklogError(f"put the task ID first, e.g. 'tasklog <ID> {argv[0]}'")
        if argv[0].startswith("-"):
            raise TasklogError(f"unknown option '{argv[0]}'. Run 'tasklog help' for usage.")

        args = build_id_parser().parse_args(argv[1:])
        args.id = argv[0]
        ID_HANDLERS[args.verb](store, args)
        return 0
    except TasklogError as err:
        print(f"tasklog: error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
