"""Build the authenticated live contract generation screen."""
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'public-demo-dist'

def build():
    OUT.mkdir(exist_ok=True)
    files={
      'index.html':ROOT/'web/live.html',
      'auth.js':ROOT/'web/auth.js',
      'app.js':ROOT/'web/live-app.js',
    }
    for name,source in files.items():OUT.joinpath(name).write_bytes(source.read_bytes())
    css='\n'.join((ROOT/'web/styles'/f'{name}.css').read_text(encoding='utf8') for name in ('theme','base','layout','components'))
    css+='\n'+(ROOT/'web/demo-experience.css').read_text(encoding='utf8')
    OUT.joinpath('style.css').write_text(css,encoding='utf8')
    for obsolete in ('demo-contract.xlsx','demo.json','public-demo.js'):
        OUT.joinpath(obsolete).unlink(missing_ok=True)
    print('Authenticated live generation build: PASS')

if __name__=='__main__':build()
