"""Stream a server launcher's output to dated files and record its lifetime.

No third-party packages: both application virtual environments can run this.
Log files are unique per supervisor, so concurrent restarts never share handles.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


class RunLog:
    def __init__(self, root, app):
        self.directory = Path(root) / app
        self.directory.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 30 * 86400
        for old in self.directory.glob('*.log'):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass  # Another process may still have an old log open.
        self.run_id = f"{datetime.now():%H%M%S}-{os.getpid()}"
        self.day = None
        self.file = None

    def write(self, stream, message):
        now = datetime.now().astimezone()
        day = now.strftime("%Y-%m-%d")
        if day != self.day:
            if self.file:
                self.file.close()
            self.file = (self.directory / f"{day}-{self.run_id}.log").open(
                "a", encoding="utf-8", buffering=1
            )
            self.day = day
        line = f"{now.isoformat(timespec='milliseconds')} [{stream}] {message.rstrip()}\n"
        self.file.write(line)
        self.file.flush()
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except (OSError, UnicodeError):
            pass  # A closed console must not discard the persistent log.

    def event(self, name, **fields):
        self.write("lifecycle", json.dumps({"event": name, **fields}, ensure_ascii=False))

    def close(self):
        if self.file:
            self.file.close()


def pump(pipe, stream, messages):
    try:
        for line in iter(pipe.readline, b""):
            messages.put((stream, line.decode("utf-8", errors="replace")))
    finally:
        pipe.close()
        messages.put((stream, None))


def check_health(url, timeout=5):
    started = time.monotonic()
    try:
        request = urllib.request.Request(url)
        if url.endswith('/graphql'):
            request = urllib.request.Request(url, data=b'{"query":"{__typename}"}',
                                             headers={'Content-Type': 'application/json'})
        # Local service checks must not inherit a machine HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            response.read(1024)
            result = {'healthy': response.status == 200, 'http_status': response.status}
    except urllib.error.HTTPError as exc:
        result = {'healthy': False, 'http_status': exc.code}
        exc.close()
    except Exception as exc:
        # Do not log the URL: its prefix may contain REPORT_PATH_TOKEN.
        result = {'healthy': False, 'error_type': type(exc).__name__}
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    return result


def supervise(command, log, heartbeat=30, health_url=None):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log.event("launcher_start", supervisor_pid=os.getpid(), parent_pid=os.getppid())
    proc = None
    started = time.monotonic()
    try:
        # Inherit the console group: Ctrl+C reaches the launcher and its children.
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        log.event("process_start", child_pid=proc.pid)
        messages = queue.Queue()
        for stream in ("stdout", "stderr"):
            threading.Thread(target=pump, args=(getattr(proc, stream), stream, messages), daemon=True).start()
        closed = 0
        next_heartbeat = time.monotonic() + heartbeat
        while closed < 2 or proc.poll() is None:
            try:
                stream, line = messages.get(timeout=0.2)
                if line is None:
                    closed += 1
                else:
                    log.write(stream, line)
            except queue.Empty:
                pass
            if time.monotonic() >= next_heartbeat:
                log.event("heartbeat", child_pid=proc.pid, child_alive=proc.poll() is None,
                          uptime_seconds=round(time.monotonic() - started))
                if health_url and proc.poll() is None:
                    log.event('health_check', **check_health(health_url))
                next_heartbeat = time.monotonic() + heartbeat
        code = proc.wait()
        log.event("process_exit", child_pid=proc.pid, exit_code=code,
                  exit_code_hex=hex(code & 0xFFFFFFFF),
                  outcome="normal" if code == 0 else "abnormal",
                  uptime_seconds=round(time.monotonic() - started, 2))
        return code
    except KeyboardInterrupt:
        log.event("interrupt_received", reason="console interrupt (Ctrl+C)")
        if proc:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.event("stop_requested", child_pid=proc.pid, reason="interrupt grace period expired")
                proc.terminate()
                proc.wait(timeout=10)
            log.event("process_exit", child_pid=proc.pid, exit_code=proc.returncode, outcome="interrupted")
        return 130
    except Exception as exc:
        log.event("supervisor_error", error_type=type(exc).__name__, message=str(exc))
        return 1
    finally:
        log.event("launcher_exit")
        log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, choices=("report-site", "dagster_project"))
    parser.add_argument("--log-root", default=str(Path(__file__).resolve().parent / ".logs"))
    parser.add_argument('--health-port', type=int)
    parser.add_argument('--health-path')
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required")
    health_url = None
    if args.health_port and args.health_path:
        token = os.environ.get('REPORT_PATH_TOKEN', '').strip()
        env_file = Path(__file__).resolve().parent / 'report-site' / '.env'
        if not token and env_file.exists():
            for line in env_file.read_text(encoding='utf-8-sig').splitlines():
                key, sep, value = line.partition('=')
                if sep and key.strip() == 'REPORT_PATH_TOKEN':
                    token = value.strip().strip('\"').strip("'")
        prefix = '/' + token.strip('/') if token else ''
        health_url = f'http://127.0.0.1:{args.health_port}{prefix}{args.health_path}'
    return supervise(command, RunLog(args.log_root, args.app), health_url=health_url)


if __name__ == "__main__":
    sys.exit(main())
