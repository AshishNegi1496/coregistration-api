from api.db import Base, engine
from api import models  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Database schema created or already present.")


if __name__ == "__main__":
    main()
