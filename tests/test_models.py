from sqlalchemy import create_engine, inspect

from backend.app.models import Base


def test_schema_can_be_created_in_empty_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "albums",
        "approvals",
        "edits",
        "members",
        "photo_members",
        "photos",
    }
    photo_columns = {column["name"] for column in inspector.get_columns("photos")}
    assert {"processing_started_at", "analysis_attempts"} <= photo_columns
