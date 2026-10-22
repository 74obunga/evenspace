import logging
import time

from app.db.session import get_session_factory
from app.modules.notifications.service import deliver_due

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("evenspace.notifications")


def main() -> None:
    factory = get_session_factory()
    logger.info("Notification worker started")
    while True:
        db = factory()
        try:
            count = deliver_due(db)
            if count:
                logger.info("Processed %s notification(s)", count)
        except Exception:
            logger.exception("Notification delivery batch failed")
            db.rollback()
        finally:
            db.close()
        time.sleep(5)


if __name__ == "__main__":
    main()
