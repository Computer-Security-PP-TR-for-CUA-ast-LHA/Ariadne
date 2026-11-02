"""Standalone -I worker. Verified upstream source stays outside this repository."""
import hashlib
import json
from pathlib import Path
import sys
import types

FILES = {
    'code/scoped_authorization.py': '34ab1780ff7ed83b3a034a1b5ff51dac526ac2a85072d8f6eb848bf4c74e8b22',
    'code/recovery_catalog.py': 'db1dbb9148c0152b67b82cb1bd176407d2b7e049008ccf829e88c91db285bb16',
    'LICENSE': '8a533b573465c7e1109de11bd92fbdddce2c3ecd86a89d6e6f5edf75b5460431',
}


def main():
    root = Path(sys.argv[1])
    sources = {}
    for name, expected in FILES.items():
        source = (root / name).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError('upstream checksum mismatch')
        sources[name] = source
    modules = {}
    for name in ('scoped_authorization', 'recovery_catalog'):
        module = types.ModuleType(name)
        sys.modules[name] = module
        exec(compile(sources['code/' + name + '.py'], '<verified-upstream:' + name + '>', 'exec'), module.__dict__)
        modules[name] = module
    raw = sys.stdin.buffer.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('input budget exceeded')
    data = json.loads(raw)
    data['authorities'] = {channel: modules['scoped_authorization'].Authority(
        a['domain'], bytes.fromhex(a['key_hex']), frozenset(tuple(s) for s in a['scopes']))
        for channel, a in data['authorities'].items()}
    data['policy'] = {op: frozenset(fields) for op, fields in data['policy'].items()}
    result = modules['recovery_catalog'].authorized_parameters(**data)
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('upstream adapter failed\n')
        sys.exit(1)
