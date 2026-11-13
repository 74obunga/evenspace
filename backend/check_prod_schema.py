import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["EVENSPACE_PROD_DATABASE_URL"])
required_columns = {
    "signature_png",
    "gps_latitude",
    "gps_longitude",
    "gps_accuracy_m",
    "gps_captured_at",
    "registration_source",
    "registered_by_id",
}

try:
    with engine.connect() as conn:
        print("PRODUCTION REVISION:")
        print(conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).all())

        actual_columns = set(conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'meeting_guest_registrations'
              AND column_name IN (
                  'signature_png',
                  'gps_latitude',
                  'gps_longitude',
                  'gps_accuracy_m',
                  'gps_captured_at',
                  'registration_source',
                  'registered_by_id'
              )
        """)).scalars().all())
        missing_columns = required_columns - actual_columns
        print("\nREQUIRED COLUMNS:")
        print(sorted(actual_columns))
        if missing_columns:
            raise RuntimeError(
                "Production schema is missing required meeting attendee columns: "
                + ", ".join(sorted(missing_columns))
                + ". Apply backend migrations with `python apply_prod_migrations.py`."
            )
        print("\nProduction meeting attendee schema is ready, including signature storage.")
finally:
    engine.dispose()
