import os
import runpy
from alembic.config import Config
from alembic import command

database_url = os.environ["EVENSPACE_PROD_DATABASE_URL"]

# env.py reads DATABASE_URL, so set it for this process.
os.environ["DATABASE_URL"] = database_url

config = Config("alembic.ini")

print("Checking target database...")
command.current(config, verbose=True)

print("\nApplying pending migrations to the target database...")
command.upgrade(config, "head")

print("\nVerifying final revision...")
command.current(config, verbose=True)

print("\nVerifying required meeting attendee columns...")
runpy.run_path("check_prod_schema.py", run_name="__main__")
