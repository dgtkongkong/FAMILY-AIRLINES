"""Check Pages project-prefix assets and prevent private-data publication."""
from pathlib import Path
import re, json
root=Path(__file__).resolve().parent/'docs'
assert (root/'index.html').is_file()
for p in root.rglob('*'):
    if not p.is_file(): continue
    assert p.suffix not in {'.sqlite3','.jks','.keystore','.py'}, p
    if p.suffix=='.html':
        text=p.read_text('utf-8')
        for value in re.findall(r'(?:href|src)="([^"]+)"',text):
            if value.startswith(('https:', '#')):continue
            assert not value.startswith('/'), (p,value)
            target=p.parent/value
            assert target.exists(), (p,value)
for name in ['child','parent']:
    d=json.loads((root/'preview'/f'sample-{name}.json').read_text('utf-8'))
    assert not d['ledger'] and not d['requests'] and not d['audit']
    assert d['balance']==0
script=(root/'preview/app.js').read_text('utf-8')
assert "fetch('/api/'+path" not in script
assert "register('/sw.js')" not in script
print('Pages checks passed: relative assets, synthetic empty records, no private files.')

