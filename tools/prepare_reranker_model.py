"""Download the approved, pinned CPU reranker into the ignored preview cache.

Run with the backend Python environment. Existing verified files are reused;
weights never enter Git or the Docker build context.
"""
import hashlib
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def valid(path, item):
    if not path.is_file() or path.stat().st_size != item["size"]:
        return False
    expected = item.get("lfs", {}).get("sha256")
    digest = hashlib.sha256() if expected else hashlib.sha1()
    if not expected:
        digest.update(f"blob {item['size']}\0".encode())
        expected = item["blobId"]
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest() == expected


def main():
    manifest = json.loads((ROOT / "eval/p1/reranker/evidence/model-manifest.json").read_text(encoding="utf-8"))
    assert manifest["repo_id"] == "BAAI/bge-reranker-v2-m3" and manifest["revision"] == REVISION
    folder = ROOT / "tmp/models/bge-reranker-v2-m3"
    folder.mkdir(parents=True, exist_ok=True)
    assert folder.resolve().is_relative_to(ROOT.resolve())
    for item in manifest["files"]:
        name = item["rfilename"]
        assert Path(name).name == name and name not in (".", "..")
        target = folder / name
        if valid(target, item):
            print("VERIFIED CACHE", name, flush=True)
            continue
        partial = target.with_suffix(target.suffix + ".part")
        for attempt in range(6):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                url = f"https://huggingface.co/{manifest['repo_id']}/resolve/{REVISION}/{name}"
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                                  timeout=httpx.Timeout(90, connect=30)) as response:
                    response.raise_for_status()
                    append = offset and response.status_code == 206
                    if append and not response.headers.get("content-range", "").startswith(f"bytes {offset}-"):
                        raise RuntimeError("Unexpected resume range")
                    with partial.open("ab" if append else "wb") as stream:
                        for block in response.iter_bytes(1024 * 1024):
                            stream.write(block)
                if not valid(partial, item):
                    # This is a single cache file, never a recursive deletion.
                    partial.unlink()
                    raise RuntimeError("Model file checksum mismatch")
                partial.replace(target)
                print("VERIFIED DOWNLOAD", name, flush=True)
                break
            except (httpx.HTTPError, RuntimeError) as exc:
                print("RETRY", name, attempt + 1, type(exc).__name__, flush=True)
                if attempt == 5:
                    raise
                time.sleep(min(5 * (attempt + 1), 30))
    (folder / "pinned-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MODEL VERIFIED", REVISION, flush=True)


if __name__ == "__main__":
    main()
