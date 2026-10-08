"""Prepare an isolated local P1 preview, using existing official infrastructure.

Secrets are read into memory from the running API and written only under ignored
tmp/. No environment values are printed or copied into the image build context.
"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
DOCKER=os.environ.get('AIKNOWLEDGE_EVAL_DOCKER','docker')
context=ROOT/'tmp/p1-preview-context'
runtime=ROOT/'tmp/p1-preview-runtime'
for directory in [context,runtime]:
    assert directory.resolve().is_relative_to(ROOT.resolve())
    directory.mkdir(parents=True,exist_ok=True)

def captured(*args):
    return subprocess.check_output([DOCKER,*args],text=True,encoding='utf-8')

def run(*args):
    subprocess.run([DOCKER,*args],check=True,cwd=ROOT)

official=json.loads(captured('inspect','aiknowledge-api-1'))[0]
if not official['State']['Running']:raise RuntimeError('Start the official local infrastructure first')
env=dict(value.split('=',1) for value in official['Config']['Env'] if '=' in value)
env['AIKNOWLEDGE_DATABASE_URL']=env['AIKNOWLEDGE_DATABASE_URL'].rsplit('/',1)[0]+'/aiknowledge_p1'
env.update(AIKNOWLEDGE_REDIS_URL='redis://redis:6379/1',
    AIKNOWLEDGE_MINIO_BUCKET='aiknowledge-p1-private',
    AIKNOWLEDGE_AUTH_ACCESS_TOKEN_SECRET='aiknowledge-p1-local-access-secret',
    AIKNOWLEDGE_AUTH_REFRESH_TOKEN_PEPPER='aiknowledge-p1-local-refresh-pepper',
    AIKNOWLEDGE_PUBLIC_SESSION_SECRET='aiknowledge-p1-local-public-session',
    AIKNOWLEDGE_SHARE_TOKEN_PEPPER='aiknowledge-p1-local-share-pepper',
    AIKNOWLEDGE_AUTH_REQUIRED='true',
    AIKNOWLEDGE_CORS_ALLOWED_ORIGINS='http://127.0.0.1:10087,http://localhost:10087',
    OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false')
selected={k:v for k,v in env.items() if k.startswith('AIKNOWLEDGE_') or k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','TOKENIZERS_PARALLELISM')}
if any('\n' in v or '\r' in v for v in selected.values()):raise ValueError('Environment values must be single-line')
(runtime/'runtime.env').write_text('\n'.join(f'{k}={v}' for k,v in selected.items())+'\n',encoding='utf-8')
pg=json.loads(captured('inspect','aiknowledge-postgres-1'))[0]
pg_env=dict(x.split('=',1) for x in pg['Config']['Env'] if '=' in x)
user=pg_env.get('POSTGRES_USER','aiknowledge')
exists=captured('exec','aiknowledge-postgres-1','psql','-U',user,'-d','postgres','-t','-A','-c',"SELECT 1 FROM pg_database WHERE datname='aiknowledge_p1'").strip()
if not exists:run('exec','aiknowledge-postgres-1','psql','-U',user,'-d','postgres','-c','CREATE DATABASE aiknowledge_p1')
for folder in ['app','migrations']:
    for source in (ROOT/'aiknowledge'/folder).rglob('*.py'):
        target=context/source.relative_to(ROOT/'aiknowledge')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
for name in ['alembic.ini','pyproject.toml','uv.lock']:shutil.copyfile(ROOT/'aiknowledge'/name,context/name)
(context/'Dockerfile.api').write_text('FROM aiknowledge-api\nCOPY --chown=app:app app/ /app/app/\nCOPY --chown=app:app migrations/ /app/migrations/\nCOPY --chown=app:app alembic.ini pyproject.toml uv.lock /app/\n',encoding='utf-8')
run('build','--network=none','-f',str(context/'Dockerfile.api'),'-t','aiknowledge-p1-api',str(context))
dist=ROOT/'aiknowledge_frontend/dist'
if not (dist/'index.html').is_file():raise RuntimeError('Build the H5 frontend before preparing preview')
# P1 must use its own reverse proxy; absolute official API URLs mix deployments.
scripts='\n'.join(p.read_text(encoding='utf-8') for p in (dist/'js').glob('*.js'))
if 'http://localhost:8000/api/v1' in scripts or 'http://127.0.0.1:8000/api/v1' in scripts or re.search('[A-Za-z]:[\\\\/]+[^"\\n]{0,100}api[\\\\/]+v1',scripts):
    raise RuntimeError('Build P1 H5 with TARO_APP_API_BASE=/api/v1 before preparing preview')
shutil.copytree(dist,context/'dist',dirs_exist_ok=True)
nginx=(ROOT/'aiknowledge_frontend/nginx.conf').read_text(encoding='utf-8').replace('http://api:8000','http://p1-api:8000')
(context/'nginx.conf').write_text(nginx,encoding='utf-8')
(context/'Dockerfile.frontend').write_text('FROM aiknowledge-frontend\nCOPY dist/ /usr/share/nginx/html/\nCOPY nginx.conf /etc/nginx/conf.d/default.conf\n',encoding='utf-8')
run('build','--network=none','-f',str(context/'Dockerfile.frontend'),'-t','aiknowledge-p1-frontend',str(context))
run('compose','-p','aiknowledge-p1','-f','compose.p1.yaml','up','-d')
print('P1 preview: http://127.0.0.1:10087 ; official 10086 data unchanged')
