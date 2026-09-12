"""Bounded loopback fixture driving actual Codex CLI unified-exec and Hooks.

No model credentials, direct Hook calls, business action replay or proof ingestion.
The caller supplies only its isolated environment. Raw prompts/results stay in RAM.
"""
from contextlib import contextmanager
import http.server
import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path


class NativeCanaryError(RuntimeError):
    pass


class NativeCanary:
    def __init__(self, codex, workspace, environment, *, externally_isolated=False):
        self.codex, self.workspace, self.environment = codex, workspace, environment
        self.externally_isolated = externally_isolated
        self.commands, self.calls, self.notifications = [], [], []
        self.messages = queue.Queue(maxsize=4096)
        self.process = None
        self.next_id = 0
        isolated = Path(environment['SULDE_HOME']).parent.resolve()
        if isolated.name != 'isolated' or not Path(environment['CODEX_HOME']).resolve().is_relative_to(isolated):
            raise NativeCanaryError('native canary requires candidate-owned isolated roots')

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def receive(self):
        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty()
            value = self.messages.get(timeout=min(45, remaining))
        except queue.Empty as error:
            raise NativeCanaryError('native Codex notification timed out') from error
        if not isinstance(value, dict):
            raise NativeCanaryError('native Codex stopped before proof completed')
        if 'method' in value:
            self.notifications.append(value)
            if len(self.notifications) > 4096:
                raise NativeCanaryError('native notification limit exceeded')
        return value

    def rpc(self, method, params):
        self.next_id += 1
        identifier = self.next_id
        self.send(dict(id=identifier, method=method, params=params))
        while True:
            value = self.receive()
            if value.get('id') == identifier:
                if 'error' in value:
                    raise NativeCanaryError(f'{method} failed: {value["error"]}')
                return value['result']
            if 'id' in value and 'method' in value:
                raise NativeCanaryError('unexpected native approval/tool request; no automatic authority')

    @contextmanager
    def start(self):
        owner = self
        self.deadline = time.monotonic() + 90
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8 * 1024 * 1024:
                    self.send_error(413)
                    return
                request = json.loads(self.rfile.read(size))
                number = len(owner.calls)
                owner.calls.append(self.path)
                # Do not retain prompts, request bodies or raw tool results.
                if number < len(owner.commands):
                    tool_names = {t.get('name') for t in request.get('tools', [])}
                    if 'exec_command' not in tool_names:
                        self.send_error(422, 'native unified exec tool unavailable')
                        return
                    item = dict(type='function_call', name='exec_command', id=f'fc_{number}',
                                call_id=f'candidate_native_{number}', arguments=json.dumps({
                                    'cmd': owner.commands[number], 'workdir': str(owner.workspace),
                                    'yield_time_ms': 1000}))
                elif number == len(owner.commands):
                    item = dict(type='message', id='done', role='assistant', status='completed',
                                content=[dict(type='output_text', text='Canary complete.', annotations=[])])
                else:
                    self.send_error(429, 'bounded canary exhausted')
                    return
                response = dict(id=f'resp_{number}', status='completed', output=[item],
                                usage=dict(input_tokens=1, output_tokens=1, total_tokens=2))
                events = [dict(type='response.created', response={**response, 'status': 'in_progress', 'output': []}),
                          dict(type='response.output_item.added', output_index=0, item=item),
                          dict(type='response.output_item.done', output_index=0, item=item),
                          dict(type='response.completed', response=response)]
                raw = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        config = Path(self.environment['CODEX_HOME']) / 'config.toml'
        original = config.read_bytes() if config.exists() else b''
        extra = ('\n[model_providers.sulde_native_canary]\nname = "Local canary, no external model"\n'
                 f'base_url = "http://127.0.0.1:{server.server_port}/v1"\nwire_api = "responses"\n'
                 'request_max_retries = 0\nstream_max_retries = 0\n')
        try:
            config.write_bytes(original + extra.encode())
            self.process = subprocess.Popen([self.codex, '-c', 'model_provider="sulde_native_canary"',
                '-c', 'model="fixture"', '-c', 'check_for_update_on_startup=false',
                '-c', 'features.hooks=true', '-c', 'features.unified_exec=true', 'app-server'],
                cwd=self.workspace, env=self.environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
            def read():
                try:
                    for line in self.process.stdout:
                        self.messages.put(json.loads(line), timeout=1)
                finally:
                    self.messages.put(None, timeout=1)
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            self.rpc('initialize', {'clientInfo': {'name': 'sulde_native_canary', 'version': '1'},
                                    'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized', 'params': {}})
            inventory = self.rpc('hooks/list', {'cwds': [str(self.workspace)]})
            entries = inventory.get('data', [])
            hooks = [h for entry in entries for h in entry.get('hooks', [])
                     if h.get('pluginId') == 'sulde@sulde-local']
            expected = {'preToolUse', 'permissionRequest', 'postToolUse', 'sessionStart', 'userPromptSubmit', 'stop'}
            if (len(hooks) != 6 or {h.get('eventName') for h in hooks} != expected
                or any(not re.fullmatch('sha256:[0-9a-f]{64}', h.get('currentHash', '')) for h in hooks)
                or any(not Path(h.get('sourcePath', '')).resolve().is_relative_to(
                    Path(self.environment['CODEX_HOME']) / 'plugins/cache') for h in hooks)):
                raise NativeCanaryError('candidate native Hook discovery incomplete: ' + json.dumps(inventory)[-4000:])
            # Trust only this isolated candidate's exact discovered hashes through
            # the native config API. Never edit a production trust/approval file.
            edits = [{'keyPath': 'hooks.state.' + json.dumps(h['key']) + '.trusted_hash',
                      'value': h['currentHash'], 'mergeStrategy': 'replace'} for h in hooks]
            edits.append({'keyPath': 'projects.' + json.dumps(str(self.workspace)) + '.trust_level',
                          'value': 'trusted', 'mergeStrategy': 'replace'})
            self.rpc('config/batchWrite', {'edits': edits, 'filePath': str(config)})
            trusted = self.rpc('hooks/list', {'cwds': [str(self.workspace)]})
            actual = [h for entry in trusted.get('data', []) for h in entry.get('hooks', [])
                      if h.get('pluginId') == 'sulde@sulde-local']
            if len(actual) != 6 or any(h.get('trustStatus') != 'trusted' or h.get('enabled') is not True for h in actual):
                raise NativeCanaryError('candidate native Hook trust did not settle')
            result = self.rpc('thread/start', {'cwd': str(self.workspace), 'approvalPolicy': 'never',
                              'sandbox': 'danger-full-access' if self.externally_isolated else 'workspace-write'})
            self.session = result['thread']['id']
            yield self
        finally:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
                self.process.stdin.close()
                self.process.stdout.close()
            config.write_bytes(original)
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def execute(self, commands):
        self.commands = list(commands)
        self.rpc('turn/start', {'threadId': self.session,
                 'input': [{'type': 'text', 'text': 'Execute only the bounded local canaries.'}]})
        while True:
            value = self.receive()
            if value.get('method') == 'turn/completed':
                turn = value.get('params', {}).get('turn', {})
                if turn.get('status') != 'completed':
                    raise NativeCanaryError(f'native canary turn failed: {turn.get("error")}')
                break
            if 'id' in value and 'method' in value:
                raise NativeCanaryError('canary unexpectedly requested human authority')
        if len(self.calls) != len(commands) + 1:
            raise NativeCanaryError('native host did not consume the exact canary sequence')
        return [r['params']['item'] for r in self.notifications if r.get('method') == 'item/completed'
                and r.get('params', {}).get('item', {}).get('type') == 'commandExecution']
