import base64
from io import BytesIO
import json
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from compfinder.api import create_app
from compfinder.config import MODEL_FILES, Settings
from compfinder.engine import REGISTER_TOKENS, OnnxEncoder
from compfinder.imaging import INPUT_SIZE, decode_image, preprocess
from compfinder.model_setup import install
from compfinder.sources import check_public, parse_page
from compfinder.taxonomy import check_visual
from compfinder.imports import parse_info


class ColorEncoder:
    """Known orthogonal features make ranking expectations independent of implementation."""
    version = "test-color-v1"

    def embed(self, images):
        vectors = np.array([np.asarray(image).mean(axis=(0, 1)) for image in images], dtype=np.float32)
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)


def photo(color, size=(96, 96)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


@pytest.fixture
def env(tmp_path):
    settings = Settings(tmp_path, tmp_path / "missing.onnx", tmp_path / "dist")
    app = create_app(settings, ColorEncoder(), start_worker=False)
    with TestClient(app) as client:
        yield client, app, settings


def create(client, name):
    response = client.post("/api/admin/styles", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, style_id, role, data, filename="photo.png"):
    return client.post(f"/api/admin/styles/{style_id}/images", data={"role": role}, files={"file": (filename, data, "image/png")})


def add(client, style_id, role, color):
    response = upload(client, style_id, role, photo(color))
    assert response.status_code == 201, response.text
    return response.json()["image"]


def drain(app):
    while app.state.engine.process_one():
        pass


def search(client, *colors, crops=None):
    files = [("files", (f"{i}.png", photo(color), "image/png")) for i, color in enumerate(colors)]
    return client.post("/api/search", files=files, data={"crops": json.dumps(crops)} if crops else {})


def test_empty_library_and_draft_visibility(env):
    client, app, _ = env
    assert client.get("/api/styles").json() == {"items": []}
    assert search(client, "red").json()["items"] == []
    style_id = create(client, "只有展示")
    add(client, style_id, "display", "red")
    assert client.get(f"/api/styles/{style_id}").status_code == 404
    assert client.get(f"/api/admin/styles/{style_id}").json()["missing"] == ["缺少识别图"]
    assert app.state.engine.process_one() is False


def test_recognition_images_never_leak_to_public_api(env):
    client, app, _ = env
    style_id = create(client, "红色款式")
    display = add(client, style_id, "display", "green")
    recognition = upload(client, style_id, "recognition", photo("red"), "private-reference.png").json()["image"]
    drain(app)
    for path in ("/api/styles", f"/api/styles/{style_id}"):
        response = client.get(path)
        assert response.status_code == 200
        assert recognition["id"] not in response.text
        assert "private-reference" not in response.text
        assert "recognitionImages" not in response.text
    result = search(client, "red")
    assert result.status_code == 200
    assert result.json()["items"][0]["cover"]["id"] == display["id"]
    assert recognition["id"] not in result.text
    assert "/admin/" not in result.text
    assert client.get(f"/api/images/{recognition['id']}").status_code == 404
    assert client.get(f"/api/images/{recognition['id']}?thumbnail=true").status_code == 404
    assert client.get(recognition["url"]).status_code == 200
    assert client.get(display["url"].replace("/admin", "")).status_code == 200
    with app.state.database.connect() as db:
        rows = db.execute("SELECT role,vector FROM images").fetchall()
    assert all(row["vector"] is None for row in rows if row["role"] == "display")


def test_multiview_average_of_best_reference_and_query_dedup(env):
    client, app, _ = env
    one = create(client, "单角度")
    both = create(client, "多角度")
    for style_id in (one, both):
        add(client, style_id, "display", "green")
        add(client, style_id, "recognition", "red")
    add(client, both, "recognition", "blue")
    drain(app)
    result = search(client, "red", "blue").json()
    assert [r["id"] for r in result["items"]] == [both, one]
    assert result["items"][0]["similarity"] == pytest.approx(1)
    assert result["items"][1]["similarity"] == pytest.approx(.5)
    assert result["items"][0]["scores"] == pytest.approx([1, 1])
    assert result["items"][1]["scores"] == pytest.approx([1, 0])
    assert result["queryIndex"] == [0, 1]
    assert result["elapsedMs"] >= 0
    repeated = search(client, "red", "blue", "blue").json()
    assert repeated["queryCount"] == 2
    assert repeated["queryIndex"] == [0, 1, 1]
    assert repeated["items"] == result["items"]
    assert len(result["items"]) == len({r["id"] for r in result["items"]})


def test_crop_and_queries_do_not_enter_library(env):
    client, app, settings = env
    red = create(client, "红")
    blue = create(client, "蓝")
    for style_id, color in ((red, "red"), (blue, "blue")):
        add(client, style_id, "display", "white")
        add(client, style_id, "recognition", color)
    drain(app)
    image = Image.new("RGB", (200, 100), "red")
    image.paste(Image.new("RGB", (100, 100), "blue"), (100, 0))
    buffer = BytesIO(); image.save(buffer, "PNG")
    before = set((settings.data_dir / "images").iterdir())
    result = client.post("/api/search", files={"files": ("split.png", buffer.getvalue())},
                         data={"crops": json.dumps([{"x": .5, "y": 0, "width": .5, "height": 1}])})
    assert result.json()["items"][0]["id"] == blue
    assert set((settings.data_dir / "images").iterdir()) == before
    assert client.get("/api/admin/index").json()["recognitionImages"] == 2


def test_cover_order_and_mutation_rules(env):
    client, app, _ = env
    style_id = create(client, "款式")
    first = add(client, style_id, "display", "green")
    second = add(client, style_id, "display", "blue")
    ref = add(client, style_id, "recognition", "red")
    drain(app)
    route = f"/api/admin/styles/{style_id}"
    assert client.patch(route, json={"coverId": ref["id"]}).status_code == 422
    assert client.patch(route, json={"displayOrder": [second["id"], second["id"]]}).status_code == 422
    assert client.patch(route, json={"coverId": second["id"], "displayOrder": [second["id"], first["id"]]}).status_code == 200
    assert app.state.engine.process_one() is False
    info = client.get(f"/api/styles/{style_id}").json()
    assert info["cover"]["id"] == second["id"]
    assert [p["id"] for p in info["displayImages"]] == [second["id"], first["id"]]
    client.delete(f"/api/admin/images/{second['id']}")
    assert client.get(f"/api/styles/{style_id}").json()["cover"]["id"] == first["id"]
    client.delete(f"/api/admin/images/{ref['id']}")
    assert search(client, "red").json()["items"] == []
    assert client.get(ref["url"]).status_code == 404
    assert client.delete(route).status_code == 200
    assert client.get(route).status_code == 404


def test_style_info_is_optional_editable_and_searchable(env):
    client, app, _ = env
    style_id = create(client, "信息款式")
    add(client, style_id, "display", "white")
    add(client, style_id, "recognition", "red")
    drain(app)
    route = f"/api/admin/styles/{style_id}"
    empty = {"params": [], "visual": [], "notes": ""}
    assert client.get(route).json()["info"] == empty
    assert client.get(f"/api/styles/{style_id}").json()["info"] == empty
    info = {"params": [{"name": " 封装 ", "value": "DIP-4"}, {"name": "", "value": " "}],
            "visual": [{"name": "颜色", "value": "红色"}], "notes": " 第一行\n第二行 "}
    saved = {"params": [{"name": "封装", "value": "DIP-4"}], "visual": [{"name": "颜色", "value": "红色"}], "notes": "第一行\n第二行"}
    assert client.patch(route, json={"info": info}).json()["info"] == saved
    assert client.get(f"/api/styles/{style_id}").json()["info"] == saved
    assert search(client, "red").json()["items"][0]["info"] == saved
    assert [s["id"] for s in client.get("/api/styles", params={"q": "dip-4"}).json()["items"]] == [style_id]
    assert [s["id"] for s in client.get("/api/admin/styles", params={"q": "红色"}).json()["items"]] == [style_id]
    assert client.get("/api/styles", params={"q": "不存在"}).json()["items"] == []
    for bad in ({"params": [{"name": "", "value": "没有名称"}]}, {"params": [{"name": "a", "value": "b", "unit": "V"}]},
                {"visual": [{"name": "颜色\x00", "value": "红"}]}, {"notes": "x" * 5001}, {"extra": []}):
        assert client.patch(route, json={"info": bad}).status_code == 422
    assert client.patch(route, json={"info": None}).status_code == 422
    assert client.get(route).json()["info"] == saved
    assert client.patch(route, json={"info": {}}).json()["info"] == empty


def test_existing_database_gains_style_info(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "compfinder.db")
    db.execute("CREATE TABLE styles (id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, cover_id TEXT, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
    db.execute("INSERT INTO styles(id,name) VALUES ('old','旧款式')")
    db.commit()
    db.close()
    settings = Settings(tmp_path, tmp_path / "missing.onnx", tmp_path / "dist")
    with TestClient(create_app(settings, ColorEncoder(), start_worker=False)) as client:
        assert client.get("/api/admin/styles/old").json()["info"] == {"params": [], "visual": [], "notes": ""}


def test_content_dedup_is_scoped_to_style_and_role(env):
    client, _, _ = env
    style_id = create(client, "重复测试")
    a = upload(client, style_id, "display", photo("red"))
    b = upload(client, style_id, "display", photo("red"), "renamed.png")
    c = upload(client, style_id, "recognition", photo("red"))
    assert b.json()["duplicate"] is True
    assert a.json()["image"]["id"] == b.json()["image"]["id"]
    assert c.json()["duplicate"] is False
    assert c.json()["image"]["id"] != a.json()["image"]["id"]


@pytest.mark.parametrize("box", [[], {"x": -1, "y": 0, "width": 1, "height": 1},
                                      {"x": 0, "y": 0, "width": .01, "height": 1},
                                      {"x": True, "y": 0, "width": 1, "height": 1}])
def test_invalid_crops_are_rejected(env, box):
    client, _, _ = env
    assert search(client, "red", crops=[box]).status_code == 422


def test_bad_uploads_and_query_limits(env):
    client, _, _ = env
    style_id = create(client, "验证")
    assert upload(client, style_id, "display", b"%PDF-1.7").status_code == 422
    assert upload(client, style_id, "display", b"x" * (20 * 1024 * 1024 + 1)).status_code == 422
    assert upload(client, style_id, "display", photo("red", (10, 10))).status_code == 422
    assert upload(client, style_id, "wrong", photo("red")).status_code == 422
    assert search(client, *(["red"] * 7)).status_code == 422
    assert client.post("/api/admin/styles", json={"name": "  "}).status_code == 422
    assert client.post("/api/admin/styles", json={"name": "验证"}).status_code == 422


def test_import_preview_partial_success_duplicates_and_path_safety(env):
    client, app, _ = env
    create(client, "已有")
    paths = ["图库/新款/展示图/1.png", "图库/新款/识别图/1.png", "图库/新款/识别图/duplicate.png",
             "图库/新款/识别图/broken.png", "图库/草稿/展示图/1.png", "图库/已有/展示图/1.png",
             "../bad/展示图/1.png", "图库/错目录/图纸/1.pdf"]
    preview = client.post("/api/admin/imports/preview", json={"paths": paths}).json()
    assert len(preview["groups"]) == 3
    assert len(preview["rejected"]) == 2
    assert next(g for g in preview["groups"] if g["name"] == "已有")["skip"] is True
    job = client.post("/api/admin/imports", json={"paths": paths}).json()
    job_id = job["id"]
    for path in paths[:5]:
        data = b"bad" if "broken" in path else photo("red")
        response = client.post(f"/api/admin/imports/{job_id}/files", data={"path": path}, files={"file": ("image.png", data)})
        assert response.status_code == 200
    assert client.post(f"/api/admin/imports/{job_id}/files", data={"path": "fake.png"}, files={"file": ("x", photo("red"))}).status_code == 404
    result = client.post(f"/api/admin/imports/{job_id}/finish").json()
    assert result["counts"] == {"pending": 0, "uploaded": 3, "duplicate": 1, "failed": 1, "skipped": 3, "info": 0}
    drain(app)
    assert [s["name"] for s in client.get("/api/styles").json()["items"]] == ["新款"]
    existing = next(s for s in client.get("/api/admin/styles").json()["items"] if s["name"] == "已有")
    assert existing["displayCount"] == 0


def test_import_style_info_files(env):
    client, _, _ = env
    old = create(client, "已有")
    example = Path(__file__).resolve().parents[2] / "examples" / "导入示例"
    custom = {"参数": [{"name": "型号", "value": "X1"}, {"name": "批次", "value": None}],
              "视觉信息": {"颜色": ["蓝色", None, "银色"], "直径": 8, "有极性": True, "未识别": None}, "备注": "AI 识别"}
    infos = {"图库/新款/款式信息.json": (example / "款式A" / "款式信息.json").read_text(encoding="utf-8"),
             "图库/只有信息/款式信息.json": (example / "款式B" / "款式信息.json").read_text(encoding="utf-8"),
             "图库/已有/款式信息.json": "﻿" + json.dumps(custom, ensure_ascii=False),
             "图库/坏格式/款式信息.json": '{"视觉信息": {"颜色": "红"',
             "图库/空/款式信息.json": '{"参数": {}, "备注": "  "}',
             "图库/未知/款式信息.json": '{"分类": "开关"}',
             "图库/新款/展示图/款式信息.json": "{}"}
    paths = ["图库/新款/展示图/1.png", "图库/新款/识别图/1.png", "图库/已有/展示图/1.png", "图库/新款/款式信息.json.txt"]
    preview = client.post("/api/admin/imports/preview", json={"paths": paths, "infos": infos}).json()
    groups = {g["name"]: g for g in preview["groups"]}
    assert set(groups) == {"新款", "只有信息", "已有"}
    assert groups["已有"]["skip"] is True
    assert groups["已有"]["info"] == {"params": [{"name": "型号", "value": "X1"}],
                                     "visual": [{"name": "颜色", "value": "蓝色、银色"}, {"name": "直径", "value": "8"},
                                                {"name": "有极性", "value": "是"}], "notes": "AI 识别"}
    messages = {r["path"]: r["message"] for r in preview["rejected"]}
    assert len(messages) == 5
    assert "JSON" in messages["图库/坏格式/款式信息.json"] and "没有填写" in messages["图库/空/款式信息.json"]
    assert "分类" in messages["图库/未知/款式信息.json"] and "并列" in messages["图库/新款/展示图/款式信息.json"]
    assert "须命名为" in messages["图库/新款/款式信息.json.txt"]
    job = client.post("/api/admin/imports", json={"paths": paths, "infos": infos}).json()
    assert job["counts"] == {"pending": 2, "uploaded": 0, "duplicate": 0, "failed": 0, "skipped": 6, "info": 3}
    styles = {s["name"]: s for s in client.get("/api/admin/styles").json()["items"]}
    assert styles["新款"]["info"]["params"][0] == {"name": "原厂料号", "value": "TS-6606"}
    assert len(styles["新款"]["info"]["visual"]) == 7 and styles["新款"]["info"]["notes"]
    assert styles["只有信息"]["info"]["visual"][3:] == [{"name": "带支架", "value": "是"},
                                                    {"name": "可见特殊结构", "value": "疑似硅胶按头、双动作结构"}]
    assert styles["只有信息"]["state"] == "draft"
    assert styles["已有"]["id"] == old and styles["已有"]["displayCount"] == 0
    assert styles["已有"]["info"] == groups["已有"]["info"]
    single = client.post("/api/admin/imports/preview", json={"infos": {"款式C/款式信息.json": '{"备注": "单款"}'}}).json()
    assert [g["name"] for g in single["groups"]] == ["款式C"]
    assert client.post("/api/admin/imports/preview", json={"paths": []}).status_code == 422


def test_restart_recovers_pending_and_invalidates_old_vectors(env):
    client, app, settings = env
    style_id = create(client, "持久化")
    add(client, style_id, "display", "white")
    ref = add(client, style_id, "recognition", "red")
    drain(app)
    with app.state.database.connect() as db:
        db.execute("UPDATE images SET state='processing' WHERE id=?", (ref["id"],))
    encoder = ColorEncoder(); encoder.version = "test-color-v2"
    next_app = create_app(settings, encoder, start_worker=False)
    with TestClient(next_app) as restarted:
        assert restarted.get("/api/admin/index").json()["pending"] == 1
        assert restarted.get("/api/styles").json()["items"] == []
        drain(next_app)
        assert search(restarted, "red").json()["items"][0]["id"] == style_id
    encoder.version = "test-color-v3"
    third_app = create_app(settings, encoder, start_worker=False)
    with TestClient(third_app) as restarted:
        assert restarted.get("/api/admin/index").json()["pending"] == 1
        assert restarted.get("/api/styles").json()["items"] == []


def test_missing_model_and_failed_index_retry(tmp_path):
    settings = Settings(tmp_path, tmp_path / "missing.onnx", tmp_path / "dist")
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        style_id = create(client, "缺模型")
        add(client, style_id, "display", "white")
        add(client, style_id, "recognition", "red")
        assert client.get("/api/admin/index").json()["modelReady"] is False
        assert client.post("/api/admin/index/retry").status_code == 503
        assert app.state.engine.process_one() is False


def test_index_failure_can_be_retried(env):
    client, app, _ = env
    style_id = create(client, "索引失败")
    add(client, style_id, "display", "white")
    ref = add(client, style_id, "recognition", "red")
    encoder = app.state.engine.encoder
    class Broken:
        def embed(self, images):
            raise RuntimeError("测试用推理失败")
    app.state.engine.encoder = Broken()
    drain(app)
    assert client.get("/api/admin/index").json()["failed"] == 1
    assert search(client, "red").json()["items"] == []
    app.state.engine.encoder = encoder
    assert client.post("/api/admin/index/retry").status_code == 200
    drain(app)
    assert client.get(f"/api/admin/styles/{style_id}").json()["recognitionImages"][0]["state"] == "ready"
    assert client.get(ref["url"]).status_code == 200


def test_model_preprocessing_preserves_extents_and_transparency():
    image = Image.new("RGBA", (240, 80), (0, 0, 0, 0))
    image.paste((240, 0, 0, 255), (0, 30, 240, 50))
    stream = BytesIO(); image.save(stream, "PNG")
    rgb = decode_image(stream.getvalue())
    assert rgb.getpixel((0, 0)) == (255, 255, 255)
    tensor = preprocess(rgb)
    assert tensor.shape == (3, INPUT_SIZE, INPUT_SIZE) == (3, 448, 448)
    assert np.isfinite(tensor).all()


def test_model_needs_both_verified_files(tmp_path):
    graph = tmp_path / "model.onnx"
    graph.write_bytes(b"graph")
    with pytest.raises(RuntimeError, match="缺少图片模型"):
        OnnxEncoder(graph)
    graph.with_name("model.onnx_data").write_bytes(b"weights")
    with pytest.raises(RuntimeError, match="校验失败"):
        OnnxEncoder(graph)


def test_model_setup_rejects_unverified_source(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPFINDER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("COMPFINDER_MODEL_PATH", raising=False)
    source = tmp_path / "download"
    source.mkdir()
    for name in MODEL_FILES:
        (source / name).write_bytes(b"not the model")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        install(source)
    assert not list((tmp_path / "data").rglob("model.onnx*"))


def test_embedding_skips_register_tokens():
    class Session:
        def run(self, names, feeds):
            hidden = np.zeros((1, 1 + REGISTER_TOKENS + 4, 384), dtype=np.float32)
            hidden[:, 0, 0] = 1  # CLS
            hidden[:, 1:1 + REGISTER_TOKENS, 2] = 100  # registers must not leak into the patch mean
            hidden[:, 1 + REGISTER_TOKENS:, 1] = 1  # patches
            return [hidden[:, 0], hidden]
    encoder = OnnxEncoder.__new__(OnnxEncoder)
    encoder.session, encoder.input = Session(), "pixel_values"
    vector = encoder.embed([Image.new("RGB", (64, 64), "red")])[0]
    assert vector.shape == (768,)
    assert np.isclose(vector[0], 2 ** -.5) and np.isclose(vector[384 + 1], 2 ** -.5)
    assert np.isclose(np.abs(vector).sum(), 2 * 2 ** -.5)


# Remote access: access token, MCP tools for AI clients, and the ytst taxonomy.
TOKEN = "t" * 32


def rpc(method, params=None, message_id=1):
    return {"jsonrpc": "2.0", "id": message_id, "method": method, **({"params": params} if params is not None else {})}


def call(client, tool_name, **arguments):
    return client.post("/mcp", json=rpc("tools/call", {"name": tool_name, "arguments": arguments})).json()["result"]


def data_url(color):
    return "data:image/png;base64," + base64.b64encode(photo(color)).decode()


def test_token_is_generated_once_and_must_be_strong(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPFINDER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COMPFINDER_TOKEN", raising=False)
    first = Settings.from_env().token
    assert len(first) >= 32 and Settings.from_env().token == first
    monkeypatch.setenv("COMPFINDER_TOKEN", "short")
    with pytest.raises(RuntimeError):
        Settings.from_env()


def test_access_token_guards_everything_but_the_page_shell(tmp_path):
    settings = Settings(tmp_path, tmp_path / "missing.onnx", tmp_path / "dist", token=TOKEN)
    with TestClient(create_app(settings, ColorEncoder(), start_worker=False)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/api/auth/status").json() == {"required": True, "authenticated": False}
        for method, path in (("get", "/api/styles"), ("get", "/api/admin/index"), ("get", "/docs"),
                             ("get", "/openapi.json"), ("post", "/api/uploads"), ("post", "/mcp")):
            assert client.request(method, path).status_code == 401, path
        assert client.post("/api/auth/login", json={"token": "wrong-token-123456789"}).status_code == 401
        bearer = {"Authorization": f"Bearer {TOKEN}"}
        assert client.get("/api/styles", headers=bearer).status_code == 200
        assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
        assert client.get("/api/styles").status_code == 200
        assert client.get("/api/auth/status").json()["authenticated"] is True
        assert client.post("/mcp", json=rpc("ping")).status_code == 401  # MCP needs its own token, not the login cookie
        assert client.post("/mcp", json=rpc("ping"), headers=bearer).status_code == 401  # nor the login token
        client.post("/api/auth/logout")
        assert client.get("/api/styles").status_code == 401


def test_mcp_tokens_are_stored_scoped_and_editable(tmp_path):
    settings = Settings(tmp_path, tmp_path / "missing.onnx", tmp_path / "dist", token=TOKEN)
    with TestClient(create_app(settings, ColorEncoder(), start_worker=False)) as client:
        admin = {"Authorization": f"Bearer {TOKEN}"}
        listing = client.get("/api/admin/tokens", headers=admin).json()
        assert listing["items"] == [] and len({tool["name"] for tool in listing["tools"]}) == 10
        assert all(tool["group"] and tool["title"] for tool in listing["tools"])
        for bad in ({"name": "x", "tools": []}, {"name": "x", "tools": ["delete_style"]},
                    {"name": "x", "tools": ["list_styles"], "secret": "short"}, {"name": " ", "tools": ["list_styles"]}):
            assert client.post("/api/admin/tokens", headers=admin, json=bad).status_code == 422, bad
        token = client.post("/api/admin/tokens", headers=admin, json={"name": "只搜索", "tools": ["list_styles", "search_by_image"]}).json()
        assert len(token["secret"]) >= 32 and token["enabled"] and token["lastUsedAt"] is None
        assert token["tools"] == ["search_by_image", "list_styles"]
        mcp = {"Authorization": f"Bearer {token['secret']}"}

        names = [tool["name"] for tool in client.post("/mcp", json=rpc("tools/list"), headers=mcp).json()["result"]["tools"]]
        assert names == ["search_by_image", "list_styles"]
        listed = client.post("/mcp", json=rpc("tools/call", {"name": "list_styles", "arguments": {}}), headers=mcp).json()
        assert json.loads(listed["result"]["content"][0]["text"])["total"] == 0
        denied = client.post("/mcp", json=rpc("tools/call", {"name": "create_style", "arguments": {"name": "x"}}), headers=mcp).json()
        assert denied["error"]["code"] == -32602 and "无权" in denied["error"]["message"]
        assert client.post("/api/uploads", headers=mcp, files={"file": ("a.png", photo("red"), "image/png")}).status_code == 201
        for path in ("/api/styles", "/api/admin/tokens"):
            assert client.get(path, headers=mcp).status_code == 401, path
        assert client.get("/api/admin/tokens", headers=admin).json()["items"][0]["lastUsedAt"]

        route = f"/api/admin/tokens/{token['id']}"
        updated = client.patch(route, headers=admin, json={"name": "建档", "tools": ["create_style"], "secret": "n" * 32}).json()
        assert (updated["name"], updated["tools"], updated["secret"]) == ("建档", ["create_style"], "n" * 32)
        assert client.post("/mcp", json=rpc("ping"), headers=mcp).status_code == 401  # the old secret stops working
        renewed = {"Authorization": f"Bearer {'n' * 32}"}
        assert client.post("/mcp", json=rpc("ping"), headers=renewed).status_code == 200
        assert client.patch(route, headers=admin, json={"secret": TOKEN}).status_code == 422
        assert client.patch(route, headers=admin, json={"enabled": None}).status_code == 422
        assert client.patch(route, headers=admin, json={"enabled": False}).json()["enabled"] is False
        assert client.post("/mcp", json=rpc("ping"), headers=renewed).status_code == 401
        assert client.delete(route, headers=admin).status_code == 200
        assert client.delete(route, headers=admin).status_code == 404
        assert client.get("/api/admin/tokens", headers=admin).json()["items"] == []


def test_mcp_builds_and_searches_the_library(env):
    client, app, _ = env
    init = client.post("/mcp", json=rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                        "clientInfo": {"name": "test", "version": "1"}})).json()["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    tools = {tool["name"] for tool in client.post("/mcp", json=rpc("tools/list")).json()["result"]["tools"]}
    assert {"search_by_image", "create_style", "add_images", "update_style_info", "read_page", "preview_image"} <= tools
    assert "安装方式" in call(client, "visual_taxonomy")["content"][0]["text"]

    rejected = call(client, "create_style", name="TS-6606", visual={"颜色": "红"})
    assert rejected["isError"] and "不是规范中的视觉字段" in rejected["content"][0]["text"]
    assert client.get("/api/admin/styles").json()["items"] == []
    created = call(client, "create_style", name="TS-6606", visual={"安装方式": "插件", "脚数": 4, "带支架": False},
                   params={"原厂料号": "TS-6606"}, notes="来源 https://example.com/item")
    style = json.loads(created["content"][0]["text"])
    assert style["info"]["visual"] == [{"name": "安装方式", "value": "插件"}, {"name": "脚数", "value": "4"},
                                       {"name": "带支架", "value": "否"}]

    uploaded = client.post("/api/uploads", files={"file": ("a.png", photo("blue"), "image/png")}).json()
    shown = json.loads(call(client, "add_images", style_id=style["id"], role="display",
                            images=[{"image": data_url("white")}])["content"][0]["text"])
    assert shown["added"] == 1
    refs = json.loads(call(client, "add_images", style_id=style["id"], role="recognition", images=[
        {"image": data_url("red")}, {"image": uploaded["id"]}, {"image": data_url("red")}, {"image": "ftp://example.com/a.png"},
        {"image": data_url("green"), "crop": {"x": 0, "y": 0, "width": .5, "height": .5}}])["content"][0]["text"])
    assert (refs["added"], refs["duplicates"], refs["failed"]) == (3, 1, 1)
    drain(app)

    found = call(client, "search_by_image", images=[{"image": data_url("red")}], limit=3)
    assert json.loads(found["content"][0]["text"])["candidates"][0]["id"] == style["id"]
    assert any(block["type"] == "image" and block["mimeType"] == "image/jpeg" for block in found["content"])

    updated = json.loads(call(client, "update_style_info", style_id=style["id"], visual={"按压方向": "顶按"})["content"][0]["text"])
    assert updated["info"]["visual"] == [{"name": "按压方向", "value": "顶按"}]
    assert updated["info"]["params"] == [{"name": "原厂料号", "value": "TS-6606"}] and updated["info"]["notes"]
    detail = call(client, "get_style", style_id=style["id"], thumbnails="recognition")["content"]
    assert sum(block["type"] == "image" for block in detail) == 3
    preview = call(client, "preview_image", image=data_url("red"), crop={"x": .25, "y": .25, "width": .5, "height": .5})
    meta = json.loads(preview["content"][0]["text"])
    assert (meta["width"], meta["shownWidth"], meta["cropped"]) == (96, 48, True)

    assert call(client, "get_style", style_id="missing")["isError"]
    assert client.post("/mcp", json=rpc("tools/call", {"name": "delete_style", "arguments": {}})).json()["error"]["code"] == -32602
    assert client.post("/mcp", content=b"{oops", headers={"content-type": "application/json"}).status_code == 400
    assert client.get("/mcp").status_code == 405
    assert client.post("/mcp", json=rpc("ping"), headers={"Origin": "https://evil.example"}).status_code == 403


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.png", "http://10.0.0.8/a.png", "http://169.254.169.254/latest",
                                 "http://[::1]/a.png", "file:///etc/passwd"])
def test_links_to_private_hosts_are_refused(url):
    with pytest.raises(ValueError):
        check_public(url)


def test_page_reading_collects_gallery_images():
    html = """<html><head><title> TS-6606 轻触开关 </title><meta property="og:image" content="//img.example/main.jpg">
    <script>var gallery = {"side": "https:\\/\\/img.example\\/side.png"}</script></head>
    <body><p>6×6 插件 4 脚</p><img data-src="/a.webp" src="data:image/gif;base64,R0lG"></body></html>"""
    page = parse_page(html, "https://shop.example/item/1")
    assert page["title"] == "TS-6606 轻触开关" and "6×6 插件 4 脚" in page["text"]
    assert [image["url"] for image in page["images"]] == ["https://img.example/main.jpg", "https://shop.example/a.webp",
                                                          "https://img.example/side.png"]


def test_examples_follow_the_taxonomy():
    example = Path(__file__).resolve().parents[2] / "examples" / "导入示例"
    for name in ("款式A", "款式B"):
        check_visual(parse_info((example / name / "款式信息.json").read_text(encoding="utf-8"))["visual"])
    with pytest.raises(ValueError, match="只能是"):
        check_visual([{"name": "安装方式", "value": "焊接"}])
