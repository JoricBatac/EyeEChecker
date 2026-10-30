"""Create database tables (production bootstrap until migrations are added).

python -m scripts.init_db
"""

from app import models  # noqa: F401
from app.core.db import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Tables created.")
