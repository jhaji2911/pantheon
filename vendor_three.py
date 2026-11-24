"""Vendor Three.js locally so the 3D world is fully self-contained (no CDN).

r187 ships both renderers: `three` (WebGLRenderer + EffectComposer passes) and `three/webgpu` +
`three/tsl` (WebGPURenderer, node materials, compute). They share `three.core.js`, so one
scene graph runs on either. Addons are fetched with their relative imports resolved, and kept
at their examples/jsm paths so those imports work unchanged (importmap: three/addons/ -> jsm/).
"""
import pathlib
import re
import urllib.request

VERSION = "0.187.0"
BASE = "https://unpkg.com/three@%s/" % VERSION
VENDOR = pathlib.Path(__file__).resolve().parent / "static" / "vendor"

BUILD = ("three.module.js", "three.core.js", "three.webgpu.js", "three.webgpu.nodes.js", "three.tsl.js")
ADDONS = (
    "controls/OrbitControls.js", "objects/Sky.js", "objects/SkyMesh.js", "utils/BufferGeometryUtils.js",
    "math/SimplexNoise.js",
    # WebGL2 fallback post-processing
    "postprocessing/EffectComposer.js", "postprocessing/RenderPass.js", "postprocessing/OutputPass.js",
    "postprocessing/UnrealBloomPass.js", "postprocessing/GTAOPass.js", "postprocessing/SMAAPass.js",
    # WebGPU post-processing (TSL nodes)
    "tsl/display/GTAONode.js", "tsl/display/BloomNode.js", "tsl/display/TRAANode.js",
)
IMPORT = re.compile(r"""(?:from|import)\s*['"](\.{1,2}/[^'"]+)['"]""")


def fetch(rel: str) -> str:
    req = urllib.request.Request(BASE + rel, headers={"User-Agent": "mist-console/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode()


def main():
    queue = ["build/" + b for b in BUILD] + ["examples/jsm/" + a for a in ADDONS]
    seen = set()
    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)
        body = fetch(rel)
        target = VENDOR / (rel.replace("examples/jsm/", "jsm/", 1) if rel.startswith("examples/") else rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        base = pathlib.PurePosixPath(rel).parent
        for dep in IMPORT.findall(body):
            queue.append(_norm(base, dep))
        print("%-48s %8d" % (rel, len(body)))
    # historical import paths used by the views
    (VENDOR / "Sky.js").write_text((VENDOR / "jsm/objects/Sky.js").read_text())
    (VENDOR / "OrbitControls.js").write_text((VENDOR / "jsm/controls/OrbitControls.js").read_text())
    assert (VENDOR / "build/three.module.js").stat().st_size > 400_000, "three.module.js looks truncated"


def _norm(base: pathlib.PurePosixPath, dep: str) -> str:
    parts = []
    for p in (str(base) + "/" + dep).split("/"):
        if p == "..":
            parts.pop()
        elif p not in (".", ""):
            parts.append(p)
    return "/".join(parts)


if __name__ == "__main__":
    main()
