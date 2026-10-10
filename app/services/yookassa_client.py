"""Клиент ЮKassa API для приёма платежей."""
import logging
import httpx
import uuid
from app.config import settings
from app.models.payment import Payment

logger = logging.getLogger(__name__)

YOOKASSA_API_URL = "https://api.yookassa.ru/v3"

# IP-адреса ЮKassa для whitelist (webhooks)
YOOKASSA_WEBHOOK_IPS = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11",
    "77.75.156.35",
    "77.75.154.128/25",
    "2a02:5180::/32",
]


class YooKassaError(Exception):
    """Ошибка при работе с ЮKassa API."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


async def create_payment(
    payment: Payment,
    return_url: str,
    user_email: str,
) -> dict:
    """
    Создаёт платёж в ЮKassa с фискальным чеком (54-ФЗ).

    Args:
        payment: объект Payment из БД (с amount_kop, plan, description)
        return_url: URL для редиректа после оплаты (например, /billing/success)
        user_email: email пользователя (для отправки фискального чека)

    Returns:
        dict с confirmation_url для редиректа пользователя

    Raises:
        YooKassaError: при ошибке API
    """
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise YooKassaError(
            "ЮKassa не настроена: YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY не заданы",
        )

    # Сумма в рублях (ЮKassa принимает строку с 2 знаками после запятой)
    amount_value = f"{payment.amount_kop / 100:.2f}"

    # === Фискальный чек (54-ФЗ) ===
    # vat_code:
    #   1 — НДС не облагается (ИП на УСН) ← ваш случай
    #   2 — НДС 0%
    #   3 — НДС 10%
    #   4 — НДС 20%
    #   5 — НДС 10/110
    #   6 — НДС 20/120
    # Если вы на ОСНО — поменяйте на нужное значение.
    vat_code = 1

    receipt = {
        "customer": {
            "email": user_email,
        },
        "items": [
            {
                "description": payment.description or f"Подписка: {payment.plan}",
                "quantity": "1.00",
                "amount": {
                    "value": amount_value,
                    "currency": "RUB",
                },
                "vat_code": vat_code,
                "payment_mode": "full_payment",      # полная оплата
                "payment_subject": "service",        # услуга
            }
        ],
    }

    payload = {
        "amount": {
            "value": amount_value,
            "currency": "RUB",
        },
        "capture": True,  # сразу списываем
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "description": payment.description or f"Подписка: {payment.plan}",
        "receipt": receipt,
        "metadata": {
            "payment_id": payment.id,
            "user_id": payment.user_id,
            "plan": payment.plan,
        },
    }

    # Idempotence key для идемпотентности
    idempotence_key = str(uuid.uuid4())
    headers = {
        "Idempotence-Key": idempotence_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info(
        f"[YOOKASSA] Creating payment | user_id={payment.user_id} | "
        f"amount={amount_value} RUB | plan={payment.plan} | email={user_email}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{YOOKASSA_API_URL}/payments",
                json=payload,
                headers=headers,
                auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            )
    except httpx.HTTPError as e:
        logger.error(f"[YOOKASSA] HTTP error: {e}")
        raise YooKassaError(f"Ошибка подключения к ЮKassa: {e}")

    if resp.status_code not in (200, 201):
        error_text = resp.text[:500]
        logger.error(
            f"[YOOKASSA] API error | HTTP {resp.status_code} | {error_text}"
        )
        raise YooKassaError(
            f"ЮKassa вернула ошибку: HTTP {resp.status_code}",
            http_status=resp.status_code,
        )

    try:
        data = resp.json()
    except Exception as e:
        logger.error(f"[YOOKASSA] Invalid JSON response: {e}")
        raise YooKassaError("Невалидный JSON от ЮKassa")

    # Извлекаем confirmation_url
    confirmation = data.get("confirmation", {})
    confirmation_url = confirmation.get("confirmation_url")
    if not confirmation_url:
        logger.error(f"[YOOKASSA] No confirmation_url in response: {data}")
        raise YooKassaError("ЮKassa не вернула confirmation_url")

    # Сохраняем yookassa_payment_id
    yookassa_payment_id = data.get("id")
    logger.info(
        f"[YOOKASSA] Payment created | yookassa_id={yookassa_payment_id} | "
        f"confirmation_url={confirmation_url[:80]}..."
    )

    return {
        "yookassa_payment_id": yookassa_payment_id,
        "confirmation_url": confirmation_url,
        "status": data.get("status", "pending"),
    }


async def get_payment_info(yookassa_payment_id: str) -> dict:
    """
    Получает информацию о платеже из ЮKassa.
    Используется для проверки статуса после редиректа.
    """
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise YooKassaError("ЮKassa не настроена")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{YOOKASSA_API_URL}/payments/{yookassa_payment_id}",
                auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            )
    except httpx.HTTPError as e:
        logger.error(f"[YOOKASSA] Get payment HTTP error: {e}")
        raise YooKassaError(f"Ошибка получения платежа: {e}")

    if resp.status_code != 200:
        logger.error(
            f"[YOOKASSA] Get payment error | HTTP {resp.status_code} | {resp.text[:300]}"
        )
        raise YooKassaError(
            f"Ошибка получения платежа: HTTP {resp.status_code}",
            http_status=resp.status_code,
        )

    return resp.json()


def is_webhook_ip_allowed(ip: str) -> bool:
    """
    Проверяет, входит ли IP в whitelist ЮKassa.
    Используется для защиты webhook-эндпоинта.
    """
    import ipaddress

    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False

    for network_str in YOOKASSA_WEBHOOK_IPS:
        try:
            network = ipaddress.ip_network(network_str, strict=False)
            if ip_obj in network:
                return True
        except ValueError:
            continue

    return False