#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


class DevTasksError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_dev_tasks_payload() -> dict[str, Any]:
    script_path = str(Path(__file__).resolve())
    return {
        "_note": f"Runtime file (gitignored). Update via: python3 {script_path} ...",
        "version": 1,
        "milestones": [],
    }


def _ensure_dev_tasks_file(path: Path) -> None:
    """
    Ensure the dev-tasks.json file exists on disk.

    Reason: control tower may call `get` on a fresh repo/worktree; we want `get`/`update` to auto-init.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive create: if another process already created it, do nothing.
        with path.open("x", encoding="utf-8") as f:
            json.dump(_default_dev_tasks_payload(), f, ensure_ascii=False, indent=2)
            f.write("\n")
    except FileExistsError:
        return


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _resolve_real_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


@dataclass(frozen=True)
class Lock:
    dir_path: Path
    owner_file: Path


_VALID_STATUSES = {"READY", "RUNNING", "DONE", "BLOCKED", "FAILED"}


def _normalize_status(value: str) -> str:
    v = value.strip().upper()
    if v not in _VALID_STATUSES:
        raise DevTasksError(f"Invalid status: {value} (expected one of: {', '.join(sorted(_VALID_STATUSES))})")
    return v


def _normalize_status_list(values: list[str] | None) -> set[str] | None:
    if values is None:
        return None
    out: list[str] = []
    for v in values:
        out.append(_normalize_status(v))
    return set(_unique(out))


def _acquire_lock(lock_dir: Path, timeout_s: float) -> Lock:
    lock_dir = lock_dir
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_s
    owner_file = lock_dir / "owner.json"
    payload = {
        "pid": os.getpid(),
        "host": platform.node(),
        "started_at": _now_iso(),
    }
    while True:
        try:
            lock_dir.mkdir(parents=False, exist_ok=False)
            owner_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return Lock(dir_path=lock_dir, owner_file=owner_file)
        except FileExistsError:
            if time.time() >= deadline:
                raise DevTasksError(f"Lock busy: {lock_dir}")
            time.sleep(0.1)


def _release_lock(lock: Lock) -> None:
    try:
        if lock.owner_file.exists():
            lock.owner_file.unlink()
    finally:
        try:
            lock.dir_path.rmdir()
        except FileNotFoundError:
            return


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_dev_tasks_payload()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _default_dev_tasks_payload()
    raw = raw.strip()
    if raw == "":
        raise DevTasksError(f"Empty JSON file: {path}")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise DevTasksError("dev-tasks.json must be a JSON object")
    milestones = data.get("milestones")
    if not isinstance(milestones, list):
        raise DevTasksError("dev-tasks.json must contain 'milestones' as a list")
    return data


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _find_milestone(milestones: list[dict[str, Any]], milestone_id: str) -> tuple[int, dict[str, Any]] | None:
    for idx, milestone in enumerate(milestones):
        if milestone.get("milestone_id") == milestone_id:
            if not isinstance(milestone, dict):
                raise DevTasksError(f"Invalid milestone entry for id={milestone_id}")
            return idx, milestone
    return None


def _status_transition_ok(old: str, new: str) -> bool:
    allowed: dict[str, set[str]] = {
        "READY": {"RUNNING", "BLOCKED"},
        "RUNNING": {"READY", "DONE", "BLOCKED", "FAILED"},
        "BLOCKED": {"READY", "RUNNING"},
        "FAILED": {"READY", "RUNNING"},
        "DONE": set(),
    }
    if old == new:
        return True
    return new in allowed.get(old, set())


def _normalize_blocked_by(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise DevTasksError("blocked_by must be a list of strings or null")
            item = item.strip()
            if item:
                out.append(item)
        return _unique(out)
    raise DevTasksError("blocked_by must be a list of strings or null")


def _reconcile(data: dict[str, Any]) -> int:
    milestones: list[dict[str, Any]] = data["milestones"]
    index: dict[str, dict[str, Any]] = {}
    for milestone in milestones:
        mid = milestone.get("milestone_id")
        if isinstance(mid, str) and mid:
            index[mid] = milestone

    changed = 0
    done_ids = {mid for mid, m in index.items() if m.get("status") == "DONE"}
    now = _now_iso()

    for milestone in milestones:
        before = json.dumps(milestone, sort_keys=True, ensure_ascii=False)

        blocked_by = _normalize_blocked_by(milestone.get("blocked_by"))
        milestone["blocked_by"] = blocked_by

        if isinstance(blocked_by, list):
            new_blocked_by = [dep for dep in blocked_by if dep not in done_ids]
            if new_blocked_by != blocked_by:
                milestone["blocked_by"] = new_blocked_by

        status = milestone.get("status")
        blocked_reason = milestone.get("blocked_reason")
        if not isinstance(blocked_reason, str):
            blocked_reason = None

        blocked_by = milestone.get("blocked_by")
        has_deps = (blocked_by is None) or (isinstance(blocked_by, list) and len(blocked_by) > 0)

        if status == "BLOCKED":
            # Auto-unblock only when the block was purely dependency-driven.
            if not has_deps and not blocked_reason:
                milestone["status"] = "READY"
                milestone["status_changed_at"] = now
        elif status == "READY":
            # READY with deps is inconsistent; normalize to BLOCKED.
            if has_deps:
                milestone["status"] = "BLOCKED"
                milestone["status_changed_at"] = now

        after = json.dumps(milestone, sort_keys=True, ensure_ascii=False)
        if after != before:
            milestone["updated_at"] = now
            changed += 1

    return changed


def cmd_get(args: argparse.Namespace) -> int:
    path = _resolve_real_path(Path(args.path))
    _ensure_dev_tasks_file(path)
    data = _load_json(path)
    if args.milestone_id and args.status:
        raise DevTasksError("get: --milestone-id and --status are mutually exclusive")
    if args.milestone_id:
        found = _find_milestone(data["milestones"], args.milestone_id)
        if not found:
            raise DevTasksError(f"milestone_id not found: {args.milestone_id}")
        _, milestone = found
        print(json.dumps(milestone, ensure_ascii=False, indent=2) + "\n")
        return 0
    status_set = _normalize_status_list(args.status)
    milestones: list[dict[str, Any]] = data.get("milestones", [])
    if status_set is not None:
        filtered: list[dict[str, Any]] = []
        for m in milestones:
            s = m.get("status")
            if not isinstance(s, str):
                continue
            if s.strip().upper() in status_set:
                filtered.append(m)
        milestones = filtered

    # 结果过多时改为紧凑文本列表，避免 JSON 占用过多上下文。
    if (args.status is not None or status_set is None) and len(milestones) > 10:
        _eprint(
            f"info: {len(milestones)} milestones matched; showing compact list. "
            "Use: dev_tasks.py get --milestone-id <id> for full details."
        )
        id_width = max(len(str(m.get("milestone_id") or "")) for m in milestones)
        status_width = max(len(str(m.get("status") or "")) for m in milestones)
        print("[id] [status] title")
        print()
        for m in milestones:
            milestone_id = str(m.get("milestone_id") or "-")
            status = str(m.get("status") or "-")
            title = str(m.get("title") or "")
            print(f"{milestone_id:<{id_width}} {status:<{status_width}} {title}")
        print()
        return 0

    out = dict(data)
    out["milestones"] = milestones
    print(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    real_path = _resolve_real_path(Path(args.path))
    lock_dir = Path(args.lock_dir) if args.lock_dir else (real_path.parent / "locks" / "dev-tasks.lock")
    lock = _acquire_lock(lock_dir, timeout_s=args.lock_timeout_s)
    try:
        _ensure_dev_tasks_file(real_path)
        data = _load_json(real_path)
        milestones: list[dict[str, Any]] = data["milestones"]

        found = _find_milestone(milestones, args.milestone_id)
        now = _now_iso()

        if not found:
            if not args.create:
                raise DevTasksError(
                    f"milestone_id not found: {args.milestone_id} (use --create to create a new milestone)"
                )
            if not args.title or not args.goal or not args.exit_criteria:
                raise DevTasksError("--create requires --title, --goal, and --exit-criteria")
            milestone: dict[str, Any] = {
                "milestone_id": args.milestone_id,
                "title": args.title,
                "goal": args.goal,
                "exit_criteria": args.exit_criteria,
                "status": "READY",
                "blocked_by": [],
                "claimed_by": None,
                "claimed_at": None,
                "status_changed_at": now,
                "updated_at": now,
            }
            milestones.append(milestone)
        else:
            _, milestone = found

        before_status = milestone.get("status")
        if not isinstance(before_status, str) or before_status.strip() == "":
            before_status = "READY"
        before_status = before_status.strip().upper()
        milestone["status"] = before_status

        blocked_by = _normalize_blocked_by(milestone.get("blocked_by"))
        milestone["blocked_by"] = blocked_by

        # Field updates
        if args.title is not None:
            milestone["title"] = args.title
        if args.goal is not None:
            milestone["goal"] = args.goal
        if args.exit_criteria is not None:
            milestone["exit_criteria"] = args.exit_criteria
        if args.execution_mode is not None:
            milestone["execution_mode"] = args.execution_mode
        if args.use_worktree is not None:
            milestone["use_worktree"] = args.use_worktree
        if args.worktree_dir is not None:
            milestone["worktree_dir"] = args.worktree_dir
        if args.branch is not None:
            milestone["branch"] = args.branch
        if args.blocked_reason is not None:
            milestone["blocked_reason"] = args.blocked_reason

        # blocked_by updates
        if args.blocked_by_pending:
            milestone["blocked_by"] = None
        if args.blocked_by is not None:
            milestone["blocked_by"] = _unique(args.blocked_by)
        if args.blocked_by_add is not None:
            current = _normalize_blocked_by(milestone.get("blocked_by"))
            if current is None:
                raise DevTasksError("blocked_by is null (pending); cannot add deps unless you set it to a list first")
            milestone["blocked_by"] = _unique([*current, *args.blocked_by_add])
        if args.blocked_by_remove is not None:
            current = _normalize_blocked_by(milestone.get("blocked_by"))
            if current is None:
                raise DevTasksError("blocked_by is null (pending); cannot remove deps unless you set it to a list first")
            remove = set(args.blocked_by_remove)
            milestone["blocked_by"] = [dep for dep in current if dep not in remove]

        # Status update
        if args.status is not None:
            new_status = args.status.strip().upper()
            if not args.force and not _status_transition_ok(before_status, new_status):
                raise DevTasksError(f"Invalid status transition: {before_status} -> {new_status}")

            milestone["status"] = new_status
            if before_status != new_status:
                milestone["status_changed_at"] = now

            if new_status == "RUNNING":
                if args.claimed_by is not None:
                    milestone["claimed_by"] = args.claimed_by
                if not milestone.get("claimed_by"):
                    raise DevTasksError("RUNNING requires --claimed-by (or an existing claimed_by)")
                milestone["claimed_at"] = now
            elif new_status == "READY":
                milestone["claimed_by"] = None
                milestone["claimed_at"] = None

        if args.claimed_by is not None and (args.status is None or milestone.get("status") != "RUNNING"):
            milestone["claimed_by"] = args.claimed_by

        if args.clear_claim:
            milestone["claimed_by"] = None
            milestone["claimed_at"] = None

        # Basic invariants (unless forced)
        status = milestone.get("status")
        blocked_by = _normalize_blocked_by(milestone.get("blocked_by"))
        milestone["blocked_by"] = blocked_by
        blocked_reason = milestone.get("blocked_reason")
        if not isinstance(blocked_reason, str):
            blocked_reason = None

        has_deps = (blocked_by is None) or (isinstance(blocked_by, list) and len(blocked_by) > 0)
        if not args.force:
            if status == "READY" and has_deps:
                raise DevTasksError("READY requires blocked_by=[] (or clear blocked_reason); current has dependencies")
            if status == "RUNNING" and has_deps:
                raise DevTasksError("RUNNING requires blocked_by=[]; current has dependencies")

        # result
        if args.result_json is not None:
            milestone["result"] = json.loads(args.result_json)
        if args.result_file is not None:
            milestone["result"] = json.loads(Path(args.result_file).read_text(encoding="utf-8"))

        milestone["updated_at"] = now

        if args.reconcile:
            _reconcile(data)

        _write_json_atomic(real_path, data)
        return 0
    finally:
        _release_lock(lock)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev_tasks.py",
        description="Manage data/dev-tasks.json (milestone-level) with locking and reconcile.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="Print all milestones or one milestone")
    p_get.add_argument("--path", default="data/dev-tasks.json", help="Path to dev-tasks.json (may be a symlink)")
    p_get.add_argument("--milestone-id", help="If set, print only this milestone")
    p_get.add_argument(
        "--status",
        type=_parse_csv,
        help="Comma-separated statuses to filter by (READY|RUNNING|DONE|BLOCKED|FAILED). Mutually exclusive with --milestone-id.",
    )
    p_get.set_defaults(func=cmd_get)

    p_update = sub.add_parser("update", help="Update a milestone (status/fields) and auto-reconcile")
    p_update.add_argument("--path", default="data/dev-tasks.json", help="Path to dev-tasks.json (may be a symlink)")
    p_update.add_argument("--lock-dir", help="Lock dir path (default: <dev-tasks-dir>/locks/dev-tasks.lock)")
    p_update.add_argument("--lock-timeout-s", type=float, default=30.0, help="Lock acquisition timeout seconds")

    p_update.add_argument("--milestone-id", required=True, help="Milestone id, e.g. M12")
    p_update.add_argument("--create", action="store_true", help="Create milestone if missing")

    p_update.add_argument("--title")
    p_update.add_argument("--goal")
    p_update.add_argument("--exit-criteria")

    p_update.add_argument("--status", help="READY|RUNNING|DONE|BLOCKED|FAILED")
    p_update.add_argument("--claimed-by")
    p_update.add_argument("--clear-claim", action="store_true")

    p_update.add_argument("--execution-mode", choices=["serial", "parallel"])
    p_update.add_argument("--use-worktree", type=lambda s: s.lower() in {"1", "true", "yes", "y"})
    p_update.add_argument("--worktree-dir")
    p_update.add_argument("--branch")

    p_update.add_argument("--blocked-reason")
    p_update.add_argument("--blocked-by", type=_parse_csv, help="Comma-separated milestone ids")
    p_update.add_argument("--blocked-by-pending", action="store_true", help="Set blocked_by=null (pending)")
    p_update.add_argument("--blocked-by-add", type=_parse_csv, help="Comma-separated milestone ids to add")
    p_update.add_argument("--blocked-by-remove", type=_parse_csv, help="Comma-separated milestone ids to remove")

    p_update.add_argument("--result-json", help="JSON string to store under 'result'")
    p_update.add_argument("--result-file", help="Path to a JSON file to store under 'result'")

    p_update.add_argument("--no-reconcile", dest="reconcile", action="store_false", help="Disable reconcile")
    p_update.set_defaults(reconcile=True)

    p_update.add_argument("--force", action="store_true", help="Bypass some safety checks")
    p_update.set_defaults(func=cmd_update)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except DevTasksError as exc:
        _eprint(f"error: {exc}")
        raise SystemExit(2)
