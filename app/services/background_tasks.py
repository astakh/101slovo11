"""Фоновые задачи: истечение подписок, очистка логов."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.subscription import expire_subscriptions

logger = logging.getLogger(__name__)


async def run_periodic_tasks(db: AsyncSession) -> None:
    """
    Запускает все периодические задачи.
    Вызывается из lifespan или cron.
    """
    try:
        expired_count = await expire_subscriptions(db)
        if expired_count > 0:
            logger.info(f"[BG] Expired {expired_count} subscriptions")
    except Exception as e:
        logger.error(f"[BG] Error in periodic tasks: {e}")