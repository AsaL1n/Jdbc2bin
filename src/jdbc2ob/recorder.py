import time
from pathlib import Path
from typing import List, Optional

from .event import FlowEvent


class SessionRecorder:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events: List[FlowEvent] = []
        self.started_at = time.time()
        self.ended_at: Optional[float] = None
        self._event_index = 0

        # 只保留 events.log 作为运行过程日志。
        self.events_log = open(self.session_dir / "events.log", "a", encoding="utf-8")

    def log(self, message: str):
        line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
        print(line)
        self.events_log.write(line + "\n")
        self.events_log.flush()

    def record(self, direction: str, data: bytes):
        if not data:
            return

        self._event_index += 1
        ev = FlowEvent(index=self._event_index, direction=direction, data=data, time=time.time())
        self.events.append(ev)

        if direction == "s2c":
            label = "S2C FakeMySQL -> JDBC"
        else:
            label = "C2S JDBC -> FakeMySQL"

        # 仅保留内存事件，用于最终构造 namedpipe_payload.bin。
        self.log("%s #%d: %d bytes, first=%s" % (label, ev.index, len(data), data[:16].hex(" ")))

    def close_files(self):
        try:
            self.events_log.close()
        except Exception:
            pass

    def finish_summary(self, carrier_path: Optional[Path], validation_ok: bool, validation_error: Optional[str]):
        self.ended_at = time.time()
        duration = round(self.ended_at - self.started_at, 3)
        s2c_bytes = sum(e.length for e in self.events if e.direction == "s2c")
        c2s_bytes = sum(e.length for e in self.events if e.direction == "c2s")

        self.log("session duration: %.3fs" % duration)
        self.log("events: %d, s2c_bytes: %d, c2s_bytes: %d" % (len(self.events), s2c_bytes, c2s_bytes))

        if carrier_path and carrier_path.exists():
            self.log("namedpipe_payload.bin generated: %s (%d bytes)" % (carrier_path, carrier_path.stat().st_size))

        if validation_ok:
            self.log("carrier validation: OK")
        else:
            self.log("carrier validation: FAILED%s" % ((": " + validation_error) if validation_error else ""))
