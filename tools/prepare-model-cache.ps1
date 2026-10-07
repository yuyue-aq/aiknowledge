param([string]$DockerExecutable = 'docker')
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path $PSScriptRoot -Parent
$modelSource = Join-Path $repositoryRoot 'models/embedding/bge-large-zh-v1.5'
if (-not (Test-Path -LiteralPath (Join-Path $modelSource 'config.json'))) {
    throw '本地 BGE 模型尚未准备好。'
}
# Use the existing application image; this helper does not receive credentials.
& $DockerExecutable image inspect aiknowledge-api --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw '请先构建 V2 API 镜像。' }
& $DockerExecutable volume create aiknowledge_bge_models_v1
if ($LASTEXITCODE -ne 0) { throw '模型缓存卷创建失败。' }
$copyCode = @'
from pathlib import Path
import hashlib, shutil
source, target = Path('/source'), Path('/target')
files = [path for path in source.rglob('*') if path.is_file()]
if any(target.iterdir()):
    for path in files:
        cached = target / path.relative_to(source)
        if not cached.is_file():
            raise RuntimeError('已有缓存不完整，不能覆盖正在使用的模型。')
        with path.open('rb') as original, cached.open('rb') as saved:
            if hashlib.file_digest(original, 'sha256').digest() != hashlib.file_digest(saved, 'sha256').digest():
                raise RuntimeError('缓存与原模型不同，请先停止服务并准备新缓存卷。')
    print('已有模型缓存验证通过，直接复用。')
else:
    shutil.copytree(source, target, dirs_exist_ok=True)
    print('模型缓存已准备好。')
'@
& $DockerExecutable run --rm --network none --user 0 `
    --mount "type=bind,source=$modelSource,target=/source,readonly" `
    --mount 'type=volume,source=aiknowledge_bge_models_v1,target=/target' `
    aiknowledge-api python -c $copyCode
if ($LASTEXITCODE -ne 0) { throw '模型缓存复制失败。' }
