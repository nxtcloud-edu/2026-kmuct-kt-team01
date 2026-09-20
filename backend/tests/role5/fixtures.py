"""Contract fixtures ONLY: SQLite *_test.sqlite3, synthetic photos and local storage.

No AWS calls, no production models, no signed-session emulation.
"""
from contextlib import closing, contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from backend.app.edits import EditRecord, EditSettings, PhotoSnapshot
from backend.tests.role5.test_render import image_file


class FixtureRepository:
    mode = "fixture"

    def __init__(self, path):
        self.path = Path(path)
        assert self.path.name.endswith("_test.sqlite3")
        self.fail_commit = False
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS edits(id TEXT PRIMARY KEY, photo_id TEXT NOT NULL,
                    number INTEGER NOT NULL, record TEXT NOT NULL, UNIQUE(photo_id, number));
                CREATE TABLE IF NOT EXISTS approvals(edit_id TEXT, member_id TEXT,
                    PRIMARY KEY(edit_id, member_id));
            ''')

    def seed(self, photo):
        data = asdict(photo)
        for key in ("active_member_ids", "confirmed_member_ids"):
            data[key] = sorted(data[key])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR REPLACE INTO photos VALUES (?, ?)", (photo.id, json.dumps(data)))

    def photo_id_for_edit(self, edit_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT photo_id FROM edits WHERE id=?", (edit_id,)).fetchone()
            return row[0] if row else None

    @contextmanager
    def transaction(self, photo_id):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("BEGIN IMMEDIATE")
            tx = FixtureTransaction(db, photo_id)
            yield tx
            if self.fail_commit:
                raise RuntimeError("fixture commit failure")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


class FixtureTransaction:
    def __init__(self, db, photo_id):
        self.db, self.photo_id = db, photo_id
        row = db.execute("SELECT snapshot FROM photos WHERE id=?", (photo_id,)).fetchone()
        if row:
            data = json.loads(row[0])
            for key in ("active_member_ids", "confirmed_member_ids"):
                data[key] = frozenset(data[key])
            self.photo = PhotoSnapshot(**data)
        else:
            self.photo = None

    def replace_photo(self, photo):
        data = asdict(photo)
        for key in ("active_member_ids", "confirmed_member_ids"):
            data[key] = sorted(data[key])
        self.db.execute("UPDATE photos SET snapshot=? WHERE id=?", (json.dumps(data), photo.id))
        self.photo = photo

    def edits(self):
        records = []
        for row in self.db.execute("SELECT record FROM edits WHERE photo_id=? ORDER BY number", (self.photo_id,)):
            data = json.loads(row[0])
            data["settings"] = EditSettings(**data["settings"])
            records.append(EditRecord(**data))
        return records

    def approvals(self):
        result = {}
        for edit_id, member_id in self.db.execute("SELECT a.edit_id, a.member_id FROM approvals a JOIN edits e ON e.id=a.edit_id WHERE e.photo_id=?", (self.photo_id,)):
            result.setdefault(edit_id, set()).add(member_id)
        return result

    def add_edit(self, edit):
        self.db.execute("INSERT INTO edits VALUES (?, ?, ?, ?)", (edit.id, edit.photo_id, edit.number, json.dumps(asdict(edit))))

    def add_approval(self, edit_id, member_id):
        self.db.execute("INSERT OR IGNORE INTO approvals VALUES (?, ?)", (edit_id, member_id))

    def remove_approval(self, edit_id, member_id):
        self.db.execute("DELETE FROM approvals WHERE edit_id=? AND member_id=?", (edit_id, member_id))

    def clear_approvals(self):
        self.db.execute("DELETE FROM approvals WHERE edit_id IN (SELECT id FROM edits WHERE photo_id=?)", (self.photo_id,))


class FixtureStorage:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(exist_ok=True)
        self.fail_write = False

    @contextmanager
    def open_original(self, photo):
        with (self.root / photo.s3_key).open("rb") as stream:
            yield stream

    def write_edit(self, key, stream):
        if self.fail_write:
            raise OSError("fixture disk failure")
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # Contract: either atomically publish the complete object or clean partial writes.
        with path.open("xb") as target:
            try:
                shutil.copyfileobj(stream, target)
            except BaseException:
                target.close()
                path.unlink(missing_ok=True)
                raise

    def delete_edit(self, key):
        (self.root / key).unlink(missing_ok=True)


def seed_photo(repo, storage, *, members=None, **overrides):
    member_ids = members or [str(uuid4()), str(uuid4())]
    photo_id, album_id = str(uuid4()), str(uuid4())
    data = dict(id=photo_id, album_id=album_id, uploader_member_id=member_ids[0],
                s3_key=f"original-{photo_id}.png", analysis_status="done", face_count=2,
                shot_type="group", active_member_ids=frozenset(member_ids),
                confirmed_member_ids=frozenset(member_ids), has_unresolved_faces=False,
                provider="fixture", mode="fixture")
    data.update(overrides)
    photo = PhotoSnapshot(**data)
    repo.seed(photo)
    (storage.root / photo.s3_key).write_bytes(image_file().getvalue())
    return photo, member_ids
