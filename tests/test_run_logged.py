import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'run-logged.py'


class RuntimeLoggingTests(unittest.TestCase):
    def test_health_check_records_http_error_and_timeout(self):
        spec = importlib.util.spec_from_file_location('run_logged', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/slow':
                    time.sleep(.4)
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            self.assertEqual(module.check_health(base)['http_status'], 500)
            result = module.check_health(base + '/slow', timeout=.05)
            self.assertFalse(result['healthy'])
            self.assertIn('error_type', result)
        finally:
            server.shutdown()
            server.server_close()

    def test_streams_are_persisted_before_exit_and_failure_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            child = "import sys,time; print('stdout-ready',flush=True); print('stderr-ready',file=sys.stderr,flush=True); time.sleep(3); sys.exit(7)"
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT), '--app', 'report-site', '--log-root', folder,
                 '--', sys.executable, '-c', child], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 2.5
                text = ''
                while time.monotonic() < deadline:
                    text = ''.join(p.read_text(encoding='utf-8') for p in Path(folder).rglob('*.log'))
                    if 'stderr-ready' in text and 'stdout-ready' in text:
                        break
                    time.sleep(0.05)
                self.assertIn('[stdout] stdout-ready', text)
                self.assertIn('[stderr] stderr-ready', text)
                self.assertIsNone(proc.poll(), 'output must reach disk before child exit')
                self.assertEqual(proc.wait(timeout=10), 7)
                text = ''.join(p.read_text(encoding='utf-8') for p in Path(folder).rglob('*.log'))
                self.assertIn('"exit_code": 7', text)
                self.assertIn('"outcome": "abnormal"', text)
                self.assertIn('"event": "launcher_exit"', text)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_failed_spawn_is_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), '--app', 'report-site', '--log-root', folder,
                 '--', str(Path(folder) / 'does-not-exist.exe')], capture_output=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 1)
            text = ''.join(p.read_text(encoding='utf-8') for p in Path(folder).rglob('*.log'))
            self.assertIn('supervisor_error', text)
            self.assertIn('launcher_exit', text)

    def test_normal_exit_and_heartbeat(self):
        spec = importlib.util.spec_from_file_location('run_logged', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            code = module.supervise([sys.executable, '-c', 'import time; time.sleep(.5)'],
                                    module.RunLog(folder, 'report-site'), heartbeat=.1)
            self.assertEqual(code, 0)
            text = ''.join(p.read_text(encoding='utf-8') for p in Path(folder).rglob('*.log'))
            self.assertIn('"event": "heartbeat"', text)
            self.assertIn('"outcome": "normal"', text)


if __name__ == '__main__':
    unittest.main()
