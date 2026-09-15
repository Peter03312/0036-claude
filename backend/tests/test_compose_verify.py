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
