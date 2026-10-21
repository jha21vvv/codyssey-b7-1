import os
import re
import subprocess
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

"""
[권태현 전담] 웹 UI 화면(GET /)과 정적 파일(/static) 서빙 검증 테스트
"""

client = TestClient(app)

def test_index_page_success():
    """GET / 에서 챗봇 화면을 HTML로 반환"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="chat-form"' in response.text

def test_index_page_assets_load_success():
    """화면이 불러오는 CSS·JS 파일이 모두 /static 경로에서 열림"""
    html = client.get("/").text
    assets = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert assets
    for path in assets:
        assert client.get(path).status_code == 200, path

def test_index_page_outside_repo_root(tmp_path):
    """저장소 루트가 아닌 폴더(예: tests/)에서 실행해도 화면 파일을 찾음"""
    repo_root = Path(__file__).resolve().parent.parent
    code = "from fastapi.testclient import TestClient; from app.main import app; print('STATUS', TestClient(app).get('/').status_code)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
    )
    assert "STATUS 200" in result.stdout, result.stderr
