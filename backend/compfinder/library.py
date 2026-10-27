import json
from pathlib import Path
import sqlite3
import threading
import uuid

from PIL import ImageOps

from .imaging import content_hash, decode_image

INFO_GROUPS = ("params", "visual")


def new_id():
    return uuid.uuid4().hex


def clean_name(name):
    name = name.strip()
    if not name or len(name) > 120 or any(ord(char) < 32 for char in name):
        raise ValueError("款式名称须为 1～120 个字符，不能包含控制字符")
    return name


def clean_info(info):
    """Trim entries and drop blank rows; every remaining row needs a name."""
    result = {}
    for group in INFO_GROUPS:
        rows = []
        for entry in info.get(group, []):
            name, value = entry["name"].strip(), entry["value"].strip()
            if not name and not value:
                continue
            if not name:
                raise ValueError("款式信息的每一行都需要填写名称")
            if any(ord(char) < 32 for char in name + value):
                raise ValueError("款式信息不能包含控制字符")
            if len(name) > 60 or len(value) > 500:
                raise ValueError(f"“{name[:20]}”过长：名称最多 60 字，内容最多 500 字")
            rows.append({"name": name, "value": value})
        if len(rows) > 100:
            raise ValueError("参数和视觉信息每组最多 100 行")
        result[group] = rows
    notes = info.get("notes", "").strip()
    if any(ord(char) < 32 and char not in "\n\r\t" for char in notes):
        raise ValueError("备注不能包含控制字符")
    if len(notes) > 5000:
        raise ValueError("备注最多 5000 字")
    result["notes"] = notes
    return result


def load_info(raw):
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    return {"params": data.get("params", []), "visual": data.get("visual", []), "notes": data.get("notes", "")}


def matches(row, query):
    if not query:
        return True
    info = load_info(row["info"])
    text = [row["name"], info["notes"], *(part for group in INFO_GROUPS for entry in info[group] for part in entry.values())]
    return any(query in part.casefold() for part in text)


class Library:
    def __init__(self, settings, database, engine):
        self.settings = settings
        self.database = database
        self.engine = engine
        self.image_dir = settings.data_dir / "images"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def create(self, name):
        style_id = new_id()
        try:
            with self.database.connect() as db:
                db.execute("INSERT INTO styles(id,name) VALUES (?,?)", (style_id, clean_name(name)))
        except sqlite3.IntegrityError as exc:
            raise ValueError("已有同名款式，请打开原款式补充图片") from exc
        return style_id

    def images(self, db, style_id, role=None):
        sql = "SELECT * FROM images WHERE style_id=?"
        args = [style_id]
        if role:
            sql += " AND role=?"
            args.append(role)
        return db.execute(sql + " ORDER BY position,id", args).fetchall()

    def image_info(self, row, admin=False):
        base = "/api/admin/images" if admin else "/api/images"
        info = {"id": row["id"], "url": f"{base}/{row['id']}",
                "thumbnailUrl": f"{base}/{row['id']}?thumbnail=true", "width": row["width"], "height": row["height"]}
        if admin:
            info.update(filename=row["filename"], role=row["role"], state=row["state"], error=row["error"])
        return info

    def serialize(self, db, row, admin=False, detail=False):
        photos = self.images(db, row["id"])
        display = [p for p in photos if p["role"] == "display"]
        recognition = [p for p in photos if p["role"] == "recognition"]
        ready = sum(p["state"] == "ready" and p["vector_version"] == self.engine.version for p in recognition)
        searchable = bool(display and ready)
        if not admin and not searchable:
            return None
        cover = next((p for p in display if p["id"] == row["cover_id"]), display[0] if display else None)
        item = {"id": row["id"], "name": row["name"], "displayCount": len(display),
                "cover": self.image_info(cover, admin) if cover else None, "info": load_info(row["info"])}
        if detail:
            item["displayImages"] = [self.image_info(p, admin) for p in display]
        if admin:
            missing = []
            if not display:
                missing.append("缺少展示图")
            if not recognition:
                missing.append("缺少识别图")
            pending = sum(p["state"] in {"pending", "processing"} for p in recognition)
            failed = sum(p["state"] == "failed" for p in recognition)
            state = "draft" if missing else "ready" if searchable else "failed" if failed and not pending else "processing"
            item.update(recognitionCount=len(recognition), indexedCount=ready, pendingCount=pending,
                        failedCount=failed, state=state, missing=missing, searchable=searchable, createdAt=row["created_at"])
            if detail:
                item["recognitionImages"] = [self.image_info(p, True) for p in recognition]
        return item

    def get(self, style_id, admin=False):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM styles WHERE id=?", (style_id,)).fetchone()
            if row is None:
                return None
            return self.serialize(db, row, admin, True)

    def list(self, admin=False, query=""):
        with self.database.connect() as db:
            rows = db.execute("SELECT * FROM styles ORDER BY created_at DESC,id").fetchall()
            return [item for row in rows if matches(row, query.strip().casefold())
                    if (item := self.serialize(db, row, admin)) is not None]

    def add_image(self, style_id, role, filename, data):
        if role not in {"display", "recognition"}:
            raise ValueError("图片用途必须是 display 或 recognition")
        image = decode_image(data)
        digest = content_hash(image)
        with self.lock, self.database.connect() as db:
            if not db.execute("SELECT 1 FROM styles WHERE id=?", (style_id,)).fetchone():
                raise LookupError("款式不存在")
            existing = db.execute("SELECT * FROM images WHERE style_id=? AND role=? AND sha256=?",
                                  (style_id, role, digest)).fetchone()
            if existing:
                return {"image": self.image_info(existing, True), "duplicate": True}
            image_id = new_id()
            storage_name = f"{image_id}.png"
            target = self.image_dir / storage_name
            thumb = self.image_dir / f"{image_id}.thumb.webp"
            try:
                image.save(target, format="PNG")
                ImageOps.contain(image, (480, 480)).save(thumb, format="WEBP", quality=85)
                position = db.execute("SELECT coalesce(max(position),-1)+1 FROM images WHERE style_id=? AND role=?",
                                      (style_id, role)).fetchone()[0]
                filename = Path(filename.replace("\\", "/")).name[:220]
                db.execute("INSERT INTO images(id,style_id,role,filename,storage_name,sha256,width,height,position,state) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)", (image_id, style_id, role, filename, storage_name, digest,
                           image.width, image.height, position, "display" if role == "display" else "pending"))
                if role == "display":
                    db.execute("UPDATE styles SET cover_id=? WHERE id=? AND cover_id IS NULL", (image_id, style_id))
                db.commit()
            except BaseException:
                target.unlink(missing_ok=True)
                thumb.unlink(missing_ok=True)
                raise
            row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        self.engine.wake.set()
        return {"image": self.image_info(row, True), "duplicate": False}

    def update(self, style_id, changes):
        with self.lock, self.database.connect() as db:
            if not db.execute("SELECT 1 FROM styles WHERE id=?", (style_id,)).fetchone():
                raise LookupError("款式不存在")
            if "name" in changes:
                try:
                    db.execute("UPDATE styles SET name=? WHERE id=?", (clean_name(changes["name"]), style_id))
                except sqlite3.IntegrityError as exc:
                    raise ValueError("已有同名款式") from exc
            if "info" in changes:
                db.execute("UPDATE styles SET info=? WHERE id=?",
                           (json.dumps(clean_info(changes["info"]), ensure_ascii=False), style_id))
            if "coverId" in changes:
                cover_id = changes["coverId"]
                if not db.execute("SELECT 1 FROM images WHERE id=? AND style_id=? AND role='display'", (cover_id, style_id)).fetchone():
                    raise ValueError("封面必须是本款式的展示图")
                db.execute("UPDATE styles SET cover_id=? WHERE id=?", (cover_id, style_id))
            if "displayOrder" in changes:
                order = changes["displayOrder"]
                ids = [r["id"] for r in self.images(db, style_id, "display")]
                if len(order) != len(ids) or set(order) != set(ids):
                    raise ValueError("排序必须包含当前所有展示图片，且不能重复")
                db.executemany("UPDATE images SET position=? WHERE id=?", enumerate(order))
        return self.get(style_id, True)

    def _remove_files(self, rows):
        for row in rows:
            # File names originate exclusively from our generated UUIDs.
            for filename in (row["storage_name"], f"{row['id']}.thumb.webp"):
                try:
                    (self.image_dir / filename).unlink(missing_ok=True)
                except OSError:
                    pass  # Deleted DB records cannot be served or searched; cleanup on next startup.

    def delete_image(self, image_id):
        with self.lock, self.database.connect() as db:
            row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
            if row is None:
                raise LookupError("图片不存在")
            db.execute("DELETE FROM images WHERE id=?", (image_id,))
            replacement = db.execute("SELECT id FROM images WHERE style_id=? AND role='display' ORDER BY position,id LIMIT 1",
                                     (row["style_id"],)).fetchone()
            db.execute("UPDATE styles SET cover_id=? WHERE id=? AND cover_id=?",
                       (replacement[0] if replacement else None, row["style_id"], image_id))
        self._remove_files([row])

    def delete_style(self, style_id):
        with self.lock, self.database.connect() as db:
            rows = self.images(db, style_id)
            if not db.execute("DELETE FROM styles WHERE id=?", (style_id,)).rowcount:
                raise LookupError("款式不存在")
        self._remove_files(rows)

    def cleanup_orphans(self):
        with self.database.connect() as db:
            names = {name for row in db.execute("SELECT id,storage_name FROM images")
                     for name in (row["storage_name"], f"{row['id']}.thumb.webp")}
        for path in self.image_dir.iterdir():
            if path.is_file() and path.name not in names:
                try:
                    path.unlink()
                except OSError:
                    pass
