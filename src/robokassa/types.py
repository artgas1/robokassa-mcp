"""Shared dataclasses, enums, and exceptions for the Robokassa client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import IntEnum


class OperationStateCode(IntEnum):
    """Lifecycle state of a payment operation returned by OpStateExt.

    Values come from Robokassa's documented state machine. See:
    https://docs.robokassa.ru/ru/xml-interfaces
    """

    INITIALIZED = 5
    """Операция инициализирована, оплата ещё не подтверждена."""

    CANCELED = 10
    """Операция отменена покупателем или по таймауту."""

    HOLD = 20
    """Средства зарезервированы на карте (предавторизация / StepByStep)."""

    RECEIVED = 50
    """Средства получены от покупателя, идёт зачисление магазину."""

    REFUNDED_BEFORE_CREDIT = 60
    """Отказ в зачислении магазину, деньги возвращены покупателю.

    NOTE: это НЕ пользовательский возврат через ЛК после успешной оплаты.
    Для статуса post-payment возврата используйте Refund/GetState.
    """

    SUSPENDED = 80
    """Операция приостановлена (security check / внештатная ситуация)."""

    COMPLETED = 100
    """Платёж прошёл успешно, средства зачислены магазину."""


class OpStateResultCode(IntEnum):
    """Top-level `Result.Code` for XML interface responses."""

    SUCCESS = 0
    BAD_SIGNATURE = 1
    MERCHANT_NOT_FOUND = 2
    OPERATION_NOT_FOUND = 3
    DUPLICATE_INVOICE = 4
    INTERNAL_ERROR = 1000


@dataclass(frozen=True, slots=True)
class OperationInfo:
    """Details about how the payment was made.

    All fields are optional — Robokassa omits them until the operation
    reaches at least RECEIVED (50).
    """

    inc_curr_label: str | None = None
    """Валюта, которой платил клиент."""

    inc_sum: Decimal | None = None
    """Сумма в валюте `inc_curr_label`."""

    inc_account: str | None = None
    """Счёт покупателя (кошелёк / маскированный номер карты)."""

    payment_method_code: str | None = None
    """Код способа оплаты (`BankCard`, `SberPay`, `SBP`, etc.)."""

    out_curr_label: str | None = None
    """Валюта зачисления магазину."""

    out_sum: Decimal | None = None
    """Сумма к зачислению магазину."""

    op_key: str | None = None
    """Уникальный идентификатор операции. ОБЯЗАТЕЛЕН для Refund/Create."""

    bank_card_rrn: str | None = None
    """RRN банковской транзакции (для карточных платежей)."""


@dataclass(frozen=True, slots=True)
class OperationState:
    """Result of OpStateExt — current state of a payment operation."""

    result_code: OpStateResultCode
    """Статус обработки самого запроса. 0 = успех."""

    state_code: OperationStateCode | None = None
    """Состояние операции. None если result_code != SUCCESS."""

    request_date: datetime | None = None
    """Дата и время ответа на запрос."""

    state_date: datetime | None = None
    """Дата и время последнего изменения state_code."""

    info: OperationInfo = field(default_factory=OperationInfo)
    """Детали операции (могут быть пустыми до state >= RECEIVED)."""

    user_fields: dict[str, str] = field(default_factory=lambda: {})
    """Пользовательские `Shp_*` параметры, переданные при старте платежа."""

    @property
    def is_paid(self) -> bool:
        """True если операция успешно завершена (state = 100)."""
        return self.state_code is OperationStateCode.COMPLETED

    @property
    def is_terminal(self) -> bool:
        """True если state больше не будет меняться (100 / 10 / 60)."""
        return self.state_code in {
            OperationStateCode.COMPLETED,
            OperationStateCode.CANCELED,
            OperationStateCode.REFUNDED_BEFORE_CREDIT,
        }


class RobokassaError(Exception):
    """Base exception for all Robokassa API failures."""


class RobokassaApiError(RobokassaError):
    """Business-logic error returned by Robokassa (non-zero Result.Code)."""

    def __init__(self, code: OpStateResultCode | int, description: str | None = None) -> None:
        self.code = code
        self.description = description
        suffix = f": {description}" if description else ""
        super().__init__(f"Robokassa API error {int(code)}{suffix}")


class RobokassaResponseError(RobokassaError):
    """Malformed or unexpected response from Robokassa (parse failure)."""
