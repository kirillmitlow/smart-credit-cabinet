"""Test-only writer with hand-picked controls; never imports the parser or mock generator."""

OWN = "40802810800000009876"
SECOND = "40802810800000009877"
OTHER = "40702810300000005678"
INN = "001234567887"
OTHER_INN = "0010000000"


def account(
    number: str = OWN,
    *,
    start: str = "01.01.2026",
    end: str = "31.03.2026",
    opening: str = "10000.00",
    incoming: str = "0.00",
    outgoing: str = "0.00",
    closing: str = "10000.00",
) -> str:
    return "\n".join(
        [
            "СекцияРасчСчет",
            f"ДатаНачала={start}",
            f"ДатаКонца={end}",
            f"РасчСчет={number}",
            f"НачальныйОстаток={opening}",
            f"ВсегоПоступило={incoming}",
            f"ВсегоСписано={outgoing}",
            f"КонечныйОстаток={closing}",
            "КонецРасчСчет",
        ]
    )


def payment(
    number: str,
    amount: str,
    *,
    payer: str = OTHER,
    recipient: str = OWN,
    payer_inn: str = OTHER_INN,
    recipient_inn: str = INN,
    created: str = "09.01.2026",
    credited: str = "10.01.2026",
    debited: str = "",
    purpose: str = "Оплата по договору",
) -> str:
    return "\n".join(
        [
            "СекцияДокумент=Платежное поручение",
            f"Номер={number}",
            f"Дата={created}",
            f"Сумма={amount}",
            f"ПлательщикСчет={payer}",
            f"ПлательщикИНН={payer_inn}",
            f"ПолучательСчет={recipient}",
            f"ПолучательИНН={recipient_inn}",
            f"ДатаСписано={debited}",
            f"ДатаПоступило={credited}",
            f"НазначениеПлатежа={purpose}",
            "КонецДокумента",
        ]
    )


def statement(
    accounts: list[str],
    payments: list[str],
    *,
    numbers: tuple[str, ...] = (OWN,),
    start: str = "01.01.2026",
    end: str = "31.03.2026",
    encoding: str = "cp1251",
) -> bytes:
    return "\n".join(
        [
            "1CClientBankExchange",
            "ВерсияФормата=1.03",
            "Кодировка=Windows",
            f"ДатаНачала={start}",
            f"ДатаКонца={end}",
            *(f"РасчСчет={number}" for number in numbers),
            *accounts,
            *payments,
            "КонецФайла",
            "",
        ]
    ).encode(encoding)
