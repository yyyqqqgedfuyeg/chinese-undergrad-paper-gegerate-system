"""可复现实验用参考实现：固定时隙的设备预约，非生产 Web 服务。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import threading


SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('student','admin')));
CREATE TABLE resources(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE slots(id INTEGER PRIMARY KEY, starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL,
 CHECK(ends_at > starts_at));
CREATE TABLE bookings(id INTEGER PRIMARY KEY, resource_id INTEGER NOT NULL REFERENCES resources(id),
 slot_id INTEGER NOT NULL REFERENCES slots(id), user_id INTEGER NOT NULL REFERENCES users(id),
 status TEXT NOT NULL CHECK(status IN ('pending','confirmed','cancelled','rejected')));
CREATE UNIQUE INDEX one_active_booking ON bookings(resource_id,slot_id)
 WHERE status IN ('pending','confirmed');
INSERT INTO users VALUES(1,'student'),(2,'student'),(9,'admin');
INSERT INTO resources VALUES(1,'示波器 A'),(2,'显微镜 B');
INSERT INTO slots VALUES(1,2000,2600),(2,2600,3200);
"""


class BookingService:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self):
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)

    def book(self, actor, resource, slot, now=1000):
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                user = conn.execute("SELECT role FROM users WHERE id=?", (actor,)).fetchone()
                window = conn.execute("SELECT starts_at FROM slots WHERE id=?", (slot,)).fetchone()
                if user is None or user["role"] != "student":
                    raise ValueError("forbidden")
                if window is None or now >= window["starts_at"]:
                    raise ValueError("too_late")
                if not conn.execute("SELECT id FROM resources WHERE id=?", (resource,)).fetchone():
                    raise ValueError("resource_not_found")
                booking = conn.execute("INSERT INTO bookings(resource_id,slot_id,user_id,status) VALUES(?,?,?,'pending')",
                                       (resource, slot, actor)).lastrowid
                conn.commit()
                return {"result": "created", "id": booking}
            except sqlite3.IntegrityError:
                conn.rollback()
                return {"result": "conflict"}
            except ValueError as exc:
                conn.rollback()
                return {"result": str(exc)}
            except sqlite3.OperationalError:
                conn.rollback()
                return {"result": "database_error"}

    def transition(self, actor, booking, action, now=1000):
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                user = conn.execute("SELECT role FROM users WHERE id=?", (actor,)).fetchone()
                row = conn.execute("SELECT b.*, s.starts_at FROM bookings b JOIN slots s ON b.slot_id=s.id WHERE b.id=?",
                                   (booking,)).fetchone()
                if row is None:
                    raise ValueError("not_found")
                if user is None:
                    raise ValueError("forbidden")
                if action == "cancel":
                    if user["role"] != "student" or row["user_id"] != actor:
                        raise ValueError("forbidden")
                    if row["status"] not in ("pending", "confirmed"):
                        raise ValueError("invalid_state")
                    target = "cancelled"
                elif action in ("confirm", "reject"):
                    if user["role"] != "admin":
                        raise ValueError("forbidden")
                    if row["status"] != "pending":
                        raise ValueError("invalid_state")
                    target = "confirmed" if action == "confirm" else "rejected"
                else:
                    raise ValueError("invalid_action")
                if now >= row["starts_at"]:
                    raise ValueError("too_late")
                conn.execute("UPDATE bookings SET status=? WHERE id=?", (target, booking))
                conn.commit()
                return {"result": target}
            except ValueError as exc:
                conn.rollback()
                return {"result": str(exc)}
            except sqlite3.OperationalError:
                conn.rollback()
                return {"result": "database_error"}

    def snapshot(self):
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM bookings ORDER BY id")]


def run_evidence(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    cases = []

    def fresh(name):
        path = directory / f"{name}.sqlite"
        if path.exists():
            path.unlink()
        service = BookingService(path)
        service.initialize()
        return service

    def record(code, name, expected, observed, service):
        assert observed == expected, (code, observed, expected)
        cases.append({"id": code, "name": name, "expected": expected, "observed": observed,
                      "passed": True, "snapshot": service.snapshot()})

    service = fresh("state")
    first = service.book(1, 1, 1)
    observed = [first["result"], service.transition(9, first["id"], "confirm")["result"],
                service.transition(1, first["id"], "cancel")["result"], service.book(2, 1, 1)["result"]]
    record("T1", "提交、确认、取消后释放名额", ["created", "confirmed", "cancelled", "created"], observed, service)
    service = fresh("ownership")
    first = service.book(1, 1, 1)
    observed = [service.transition(2, first["id"], "cancel")["result"], service.snapshot()[0]["status"]]
    record("T2", "越权取消被拒绝且状态不变", ["forbidden", "pending"], observed, service)
    service = fresh("terminal")
    first = service.book(1, 1, 1)
    observed = [service.transition(1, first["id"], "confirm")["result"],
                service.transition(9, first["id"], "reject")["result"],
                service.transition(9, first["id"], "confirm")["result"], service.book(2, 1, 1)["result"]]
    record("T3", "审核权限、拒绝终态与名额释放", ["forbidden", "rejected", "invalid_state", "created"], observed, service)
    service = fresh("boundary")
    first = service.book(1, 1, 1)
    observed = [service.transition(1, first["id"], "cancel", now=2000)["result"],
                service.transition(9, first["id"], "confirm", now=2000)["result"],
                service.book(2, 2, 1, now=2000)["result"], service.snapshot()[0]["status"]]
    record("T4", "开始时刻边界禁止提交与状态变更", ["too_late", "too_late", "too_late", "pending"], observed, service)
    service = fresh("resources")
    observed = [service.book(1, 1, 1)["result"], service.book(2, 1, 1)["result"],
                service.book(1, 2, 1)["result"]]
    record("T5", "同资源同槽互斥、不同资源独立", ["created", "conflict", "created"], observed, service)
    rounds = []
    for number in range(20):
        service = fresh(f"race-{number:02d}")
        barrier = threading.Barrier(2)

        def compete(actor):
            barrier.wait(timeout=10)
            return service.book(actor, 1, 1)["result"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(compete, [1, 2]))
        rows = service.snapshot()
        active = sum(r["status"] in ("pending", "confirmed") for r in rows)
        assert results == ["conflict", "created"] and active == 1
        rounds.append({"round": number + 1, "results": results, "active_count": active})
    record("T6", "双连接并发抢占固定时隙", {"rounds": 20, "created": 20, "conflict": 20, "violations": 0},
           {"rounds": len(rounds), "created": sum(r["results"].count("created") for r in rounds),
            "conflict": sum(r["results"].count("conflict") for r in rounds),
            "violations": sum(r["active_count"] != 1 for r in rounds)}, service)
    report = {"environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                               "platform": platform.system(), "journal_mode": "delete", "busy_timeout_seconds": 5},
              "method": "单进程、两个工作线程各自建立独立数据库连接；每轮新数据库；屏障同时起跑；20轮。",
              "time_model": "测试注入整数时钟：now=1000，slot1=[2000,2600)，边界now=2000；不是现场真实时间。",
              "limitations": ["未测试真实HTTP身份认证、跨进程或多机并发", "未测吞吐量和延迟", "未进行故障注入或持续负载测试"],
              "cases": cases, "race_rounds": rounds,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory / "evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "schema.sql").write_text(SCHEMA, encoding="utf-8")
    (directory / "reference.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    return report
