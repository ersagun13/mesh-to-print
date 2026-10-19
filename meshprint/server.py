"""Loopback-only local API with bounded isolated processing workers.

Security boundary: only upload bytes and validated options enter a worker. Client
filenames never become paths. Only registered output basenames are downloadable.
"""
import base64
import binascii
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import mimetypes
from pathlib import Path
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
from urllib.parse import unquote, urlsplit
import webbrowser

from . import __version__
from .fixtures import demo_meshes
from .formats import MAX_BYTES, MeshError, write_stl
from .pipeline import APP, json_bytes, validate_options

MAX_REQUEST = 4 * ((MAX_BYTES + 2) // 3) + 16384
MAX_JOBS = 16
MAX_QUEUE = 4
MAX_WORKSPACE_BYTES = 2 * 1024 ** 3
JOB_PATTERN = re.compile(r'^[a-f0-9]{32}$')
ROOT = Path(__file__).resolve().parent.parent
MARKER = '.meshprint-workspace'


class Policy:
    """Reject DNS rebinding, cross-origin reads and unauthorized writes."""
    def __init__(self, port, token):
        self.host = f'127.0.0.1:{port}'
        self.origin = f'http://{self.host}'
        self.token = token

    def check(self, method, headers):
        if headers.get('Host') != self.host:
            raise MeshError('Host must match the printed 127.0.0.1 URL.')
        origin = headers.get('Origin')
        if origin is not None and origin != self.origin:
            raise MeshError('Cross-origin requests are forbidden.')
        if method == 'POST':
            if origin != self.origin:
                raise MeshError('A matching Origin is required for uploads.')
            token = headers.get('X-Local-Token', '')
            if not hmac.compare_digest(token, self.token):
                raise MeshError('The local session token is missing or invalid.')


def validate_submission(payload):
    if not isinstance(payload, dict) or set(payload) != {'filename', 'content_base64', 'options'}:
        raise MeshError('Upload requires exactly filename, content_base64 and options.')
    name = payload['filename']
    if (not isinstance(name, str) or not 1 <= len(name) <= 255 or
            any(c in name for c in ('/', '\\', '\0')) or
            any(ord(c) < 32 for c in name)):
        raise MeshError('Filename must be a display basename without path separators.')
    if name.rsplit('.', 1)[-1].lower() not in ('stl', 'obj', 'glb'):
        raise MeshError('Supported upload extensions are STL, OBJ and GLB.')
    encoded = payload['content_base64']
    if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
        raise MeshError('Upload exceeds 64 MiB or is empty.')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MeshError('Upload is not valid base64.') from exc
    if not data or len(data) > MAX_BYTES:
        raise MeshError('Upload exceeds 64 MiB or is empty.')
    return name, data, validate_options(payload['options'])


def cleanup_workspace(path):
    """Remove only generated job directories inside an explicitly marked workspace."""
    path = Path(path)
    marker = path / MARKER
    if path.is_symlink() or not marker.is_file() or marker.read_text() != APP:
        raise MeshError('Cleanup requires a workspace created by Mesh to Print.')
    lock = path / '.running'
    if lock.exists():
        raise MeshError('Stop the server before cleaning its workspace.')
    count = 0
    for child in path.iterdir():
        if JOB_PATTERN.fullmatch(child.name) and child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
            count += 1
    return count


class JobManager:
    """One worker at a time, finite queue/history/disk quota and hard timeout."""
    def __init__(self, workspace, start_worker=True):
        self.workspace = Path(workspace).absolute()
        if self.workspace.is_symlink():
            raise MeshError('Workspace must not be a symbolic link.')
        self.workspace.mkdir(parents=True, exist_ok=True)
        marker = self.workspace / MARKER
        if marker.exists():
            if marker.read_text() != APP:
                raise MeshError('Invalid workspace marker.')
        elif any(self.workspace.iterdir()):
            raise MeshError('Choose a new empty directory for the local workspace.')
        else:
            marker.write_text(APP)
        self.lock_path = self.workspace / '.running'
        try:
            with self.lock_path.open('x') as lock:
                lock.write(str(__import__('os').getpid()))
        except FileExistsError as exc:
            raise MeshError('Workspace is already in use; remove stale.running only after verifying its server stopped.') from exc
        self.jobs = {}
        self.queue = queue.Queue(maxsize=MAX_QUEUE)
        self.lock = threading.Lock()
        self.closed = False
        self.active_process = None
        self.worker = None
        if start_worker:
            self.worker = threading.Thread(target=self._loop, daemon=True)
            self.worker.start()

    def submit(self, filename, data, options):
        # Validate here as well as at HTTP ingress: CLI callers share this boundary.
        filename, data, options = validate_submission({
            'filename': filename,
            'content_base64': base64.b64encode(data).decode('ascii'),
            'options': options,
        })
        with self.lock:
            if len(self.jobs) >= MAX_JOBS or self.queue.full():
                raise MeshError('Job limit reached. Wait for queued work or clean a stopped workspace.')
            total = sum(p.stat().st_size for p in self.workspace.rglob('*') if p.is_file())
            pending = sum(job['status'] in ('queued', 'running') for job in self.jobs.values())
            reserved = (pending + 1) * 512 * 1024 ** 2
            if total + len(data) + reserved > MAX_WORKSPACE_BYTES:
                raise MeshError('The 2 GiB workspace quota is reached. Stop the server and run cleanup.')
            job_id = secrets.token_hex(16)
            directory = self.workspace / job_id
            directory.mkdir()
            source = directory / ('input.' + filename.rsplit('.', 1)[-1].lower())
            source.write_bytes(data)
            (directory / 'request.json').write_bytes(json_bytes({'filename': filename, 'options': options}))
            job = {'job_id': job_id, 'status': 'queued', 'progress': 0,
                   'message': 'Waiting for the local geometry worker.', 'error': None,
                   'report': None, 'artifacts': [], 'previews': {}}
            self.jobs[job_id] = job
            self.queue.put_nowait((job_id, source))
            return dict(job)

    def _loop(self):
        while not self.closed:
            try:
                item = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue
            self._run(item)

    def run_next(self):
        self._run(self.queue.get_nowait())

    def _run(self, item):
        job_id, source = item
        with self.lock:
            self.jobs[job_id].update(status='running', progress=0.1,
                                     message='Checking physical geometry in an isolated local worker.')
        directory = source.parent
        command = [sys.executable, str(ROOT / 'run.py'), '_worker', str(source), str(directory / 'output'), str(directory / 'request.json')]
        try:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.lock:
                self.active_process = child
                if self.closed:
                    child.kill()
            try:
                returncode = child.wait(timeout=300)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                raise
            error_path = directory / 'worker-error.json'
            if returncode != 0:
                if error_path.is_file():
                    message = json.loads(error_path.read_text())['error']
                else:
                    message = 'Worker stopped at its memory/CPU limit or exited unexpectedly. Try fewer triangles.'
                raise MeshError(message)
            report = json.loads((directory / 'output' / 'report.json').read_text())
            artifacts = []
            previews = {}
            for path in sorted((directory / 'output').iterdir()):
                url = f'/api/jobs/{job_id}/files/{path.name}'
                if path.suffix == '.msh':
                    previews[path.stem] = url
                else:
                    artifacts.append({'name': path.name, 'url': url, 'label': path.name})
            with self.lock:
                self.jobs[job_id].update(status='completed', progress=1,
                                         message='Diagnostics and measured exports are ready.',
                                         report=report, artifacts=artifacts, previews=previews)
        except subprocess.TimeoutExpired:
            with self.lock:
                self.jobs[job_id].update(status='failed', message='Worker time limit reached.',
                                         error='Processing exceeded 300 seconds. Try fewer triangles or disable sampling.')
        except (MeshError, OSError, ValueError, KeyError) as exc:
            with self.lock:
                self.jobs[job_id].update(status='failed', message='Processing could not complete.', error=str(exc))
        finally:
            with self.lock:
                self.active_process = None
            self.queue.task_done()

    def get(self, job_id):
        if not JOB_PATTERN.fullmatch(job_id):
            raise MeshError('Invalid job identifier.')
        with self.lock:
            if job_id not in self.jobs:
                raise MeshError('Job not found in this session.')
            return dict(self.jobs[job_id])

    def artifact_path(self, job_id, basename):
        job = self.get(job_id)
        allowed = {entry['name'] for entry in job['artifacts']}
        allowed.update(url.rsplit('/', 1)[-1] for url in job['previews'].values())
        if basename not in allowed or '/' in basename or '\\' in basename:
            raise MeshError('Artifact not found or path is invalid.')
        directory = self.workspace / job_id / 'output'
        path = directory / basename
        if path.is_symlink() or path.resolve().parent != directory.resolve() or not path.is_file():
            raise MeshError('Artifact path is invalid.')
        return path

    def close(self):
        with self.lock:
            self.closed = True
            if self.active_process is not None:
                self.active_process.kill()
        if self.worker:
            self.worker.join(timeout=5)
        self.lock_path.unlink(missing_ok=True)


def make_handler(manager, policy):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'MeshPrintLocal/0.1'
        protocol_version = 'HTTP/1.0'

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def send_bytes(self, status, data, content_type='application/json', attachment=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if attachment:
                self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')
            self.end_headers()
            self.wfile.write(data)

        def respond_json(self, status, value):
            self.send_bytes(status, json_bytes(value))

        def safe_path(self):
            split = urlsplit(self.path)
            if split.scheme or split.netloc or split.query or split.fragment:
                raise MeshError('Only exact local paths without query strings are supported.')
            path = unquote(split.path)
            if any(segment in ('.', '..') for segment in path.split('/')) or '\\' in path or '\0' in path:
                raise MeshError('Path traversal is forbidden.')
            return path

        def check(self, method):
            # Duplicate Host/Origin/token headers must not be interpreted differently downstream.
            for name in ('Host', 'Origin', 'X-Local-Token', 'Content-Length'):
                if len(self.headers.get_all(name, [])) > 1:
                    raise MeshError('Duplicate request security headers are forbidden.')
            policy.check(method, self.headers)
            return self.safe_path()

        def do_GET(self):
            try:
                path = self.check('GET')
                if path == '/api/config':
                    self.respond_json(200, {'app': APP, 'version': __version__, 'token': policy.token,
                                           'max_upload_bytes': MAX_BYTES, 'profiles': [],
                                           'native': {'required': False, 'available': True, 'backend': 'Python standard library'}})
                elif path == '/api/demo':
                    mesh = demo_meshes()['repairable-vessel.stl']
                    self.respond_json(200, {'filename': 'repairable-vessel.stl',
                                           'content_base64': base64.b64encode(write_stl(mesh)).decode('ascii'),
                                           'options': {'mode': 'analyze', 'units': 'mm', 'samples': 128,
                                                       'fill_holes_mm': None}})
                elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}', path):
                    self.respond_json(200, manager.get(path.rsplit('/', 1)[-1]))
                elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}/files/[^/]+', path):
                    parts = path.split('/')
                    file = manager.artifact_path(parts[3], parts[5])
                    mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                    attachment = None if file.suffix in ('.msh', '.html', '.json') else file.name
                    self.send_bytes(200, file.read_bytes(), mime, attachment)
                elif path in ('/', '/index.html', '/app.js', '/styles.css', '/viewer.js', '/lib.js'):
                    file = ROOT / 'web' / ('index.html' if path == '/' else path[1:])
                    if not file.is_file():
                        raise MeshError('Browser assets are unavailable; use the CLI.')
                    self.send_bytes(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'text/plain')
                else:
                    self.respond_json(404, {'error': 'Path not found.'})
            except MeshError as exc:
                self.respond_json(400, {'error': str(exc)})
            except (BrokenPipeError, ConnectionError, TimeoutError):
                pass

        def do_POST(self):
            try:
                path = self.check('POST')
                if path != '/api/jobs':
                    self.respond_json(404, {'error': 'Path not found.'})
                    return
                if self.headers.get('Transfer-Encoding'):
                    raise MeshError('Transfer-Encoding is unsupported; send Content-Length.')
                if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                    raise MeshError('Upload Content-Type must be application/json.')
                length = self.headers.get('Content-Length', '')
                if not length.isdecimal() or not 1 <= int(length) <= MAX_REQUEST:
                    raise MeshError('Request length is missing or exceeds the upload limit.')
                body = self.rfile.read(int(length))
                if len(body) != int(length):
                    raise MeshError('Truncated request body.')
                def reject_constant(value):
                    raise MeshError('JSON numbers must be finite.')
                payload = json.loads(body, parse_constant=reject_constant)
                name, data, options = validate_submission(payload)
                job = manager.submit(name, data, options)
                self.respond_json(202, {'job_id': job['job_id'], 'status': job['status']})
            except (MeshError, ValueError, UnicodeDecodeError, RecursionError) as exc:
                self.respond_json(400, {'error': str(exc)})
            except (BrokenPipeError, ConnectionError, TimeoutError):
                pass

        def do_OPTIONS(self):
            self.respond_json(405, {'error': 'CORS is not enabled.'})

    return Handler


def serve(port=0, no_browser=False, workspace='meshprint-workspace'):
    """Bind only loopback. A bind failure is actionable and never called success."""
    manager = JobManager(workspace)
    server = None
    try:
        server = HTTPServer(('127.0.0.1', port), BaseHTTPRequestHandler)
        policy = Policy(server.server_port, secrets.token_urlsafe(32))
        server.RequestHandlerClass = make_handler(manager, policy)
        print(policy.origin, flush=True)
        if not no_browser:
            webbrowser.open(policy.origin)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        raise MeshError(f'Cannot bind the local browser server: {exc}. Use analyze/repair CLI commands in restricted environments.') from exc
    finally:
        if server:
            server.server_close()
        manager.close()
