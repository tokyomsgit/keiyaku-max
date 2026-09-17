"""One-time: copy locally analyzed JSON caches to the private bucket so the cloud reuses them.
Rule-only local results are skipped because they would block a later AI reading."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from web_data import load_env
load_env()
from cloud_storage import Storage
from cloud_worker import CACHE_DIRS, pack_cache


def usable(folder):
    for path in folder.rglob('*.json'):
        try:data = json.loads(path.read_text(encoding='utf8'))
        except (OSError, ValueError):return False
        if not isinstance(data, dict):continue
        if data.get('local_candidates') or data.get('metadata', {}).get('local_processing') or data.get('source', {}).get('local_processing'):
            return False
    return any(folder.glob('extracted*.json'))


def main(output):
    storage = Storage();storage.ensure_bucket();sent = 0
    digests = {p.name for d in CACHE_DIRS for p in (output / d).glob('*') if len(p.name) == 64}
    for digest in sorted(digests):
        folders = [output / d / digest for d in CACHE_DIRS if (output / d / digest).is_dir()]
        if not all(usable(f) for f in folders) or storage.get('cache/' + digest + '.zip'):continue
        packed = pack_cache(output, digest)
        if packed:storage.put('cache/' + digest + '.zip', packed, 'application/zip');sent += 1
    print('seeded', sent, 'of', len(digests))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'output/web')
