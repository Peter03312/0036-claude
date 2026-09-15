"""交付编排校验：verify 服务必须存在于主编排文件且不依赖 curl。

这些是"按约定运行 Compose verify"的硬性要求，用测试锁定，防止回归。
"""
from __future__ import annotations

import os

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _compose():
    path = os.path.join(ROOT, "docker-compose.yml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_verify_service_in_main_compose():
    doc = _compose()
    services = doc["services"]
    assert "verify" in services, "主编排文件必须包含 verify 服务"
    verify = services["verify"]
    # 仅在 verify profile 下启动，普通 up 不受影响。
    assert verify.get("profiles") == ["verify"]


def test_verify_does_not_require_curl():
    verify = _compose()["services"]["verify"]
    command = " ".join(verify["command"])
    assert "curl" not in command, "verify 必须用 Python 等待健康，精简镜像无 curl"
    assert "urllib" in command


def test_verify_waits_for_frontend_and_backend_checks():
    verify = _compose()["services"]["verify"]
    deps = verify["depends_on"]
    conditions = {k: v["condition"] for k, v in deps.items()}
    assert conditions.get("web-verify") == "service_completed_successfully"
    assert conditions.get("api-verify-base") == "service_completed_successfully"


def test_verify_images_have_dockerfiles():
    doc = _compose()
    for svc in ("api-verify-base", "web-verify"):
        build = doc["services"][svc].get("build", {})
        df = build.get("dockerfile", "Dockerfile")
        context = os.path.join(ROOT, build["context"])
        assert os.path.isfile(os.path.join(context, df)), (svc, df)


def test_backend_dockerignore_keeps_tests_for_verify_image():
    """Dockerfile.verify 要 COPY tests，.dockerignore 不得把 tests/ 排除。"""
    ignore_path = os.path.join(ROOT, "backend", ".dockerignore")
    with open(ignore_path, encoding="utf-8") as f:
        rules = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]
    # 任何会忽略 tests 目录的规则都不允许出现。
    blocks_tests = [
        r for r in rules
        if r.rstrip("/") == "tests"
        or r in ("tests", "tests/")
        or r.startswith("tests/")
        or r in ("*", "**")
    ]
    assert not blocks_tests, f".dockerignore 排除了 tests：{blocks_tests}"
    # tests 源文件确实存在，COPY 才不会失败。
    assert os.path.isfile(
        os.path.join(ROOT, "backend", "tests", "test_api.py")
    )


def test_backend_verify_dockerfile_copies_tests():
    path = os.path.join(ROOT, "backend", "Dockerfile.verify")
    content = open(path, encoding="utf-8").read()
    assert "COPY tests" in content
    assert "pytest" in content


def test_verify_mounts_repo_root():
    """后端测试/端到端脚本需要仓库根文件（docker-compose.yml、verify/）。

    verify 服务必须把仓库根挂到容器内（只读），并在 backend 目录跑测试，
    而不是只依赖以 ./backend 为上下文的镜像内容。
    """
    verify = _compose()["services"]["verify"]
    # 卷可能是短格式字符串 "./:/workspace:ro" 或长格式映射。
    raw = verify.get("volumes", [])
    mounts = {}
    for item in raw:
        if isinstance(item, str):
            src, rest = item.split(":", 1)
            parts = rest.split(":")
            mounts[src.rstrip("/") or "."] = {
                "target": parts[0],
                "ro": len(parts) > 1 and "ro" in parts[1].split(","),
            }
        else:
            mounts[item["source"].rstrip("/") or "."] = {
                "target": item.get("target"),
                "ro": item.get("read_only", False),
            }
    assert "." in mounts, f"必须挂载仓库根，实际挂载：{list(mounts)}"
    assert mounts["."]["target"] == "/workspace"
    assert mounts["."]["ro"] is True

    command = " ".join(verify["command"])
    assert "cd /workspace/backend" in command
    assert "/workspace/verify/verify_e2e.py" in command
    # 只读挂载下不写缓存。
    assert "no:cacheprovider" in command
    env = verify.get("environment", [])
    assert any("PYTHONDONTWRITEBYTECODE=1" in str(e) for e in env)


def test_verify_repo_root_files_exist():
    """挂载后容器内 /workspace 下应能找到的根文件（防止路径漂移）。"""
    assert os.path.isfile(os.path.join(ROOT, "docker-compose.yml"))
    assert os.path.isfile(os.path.join(ROOT, "verify", "verify_e2e.py"))
    assert os.path.isfile(os.path.join(ROOT, "backend", "tests", "test_api.py"))
