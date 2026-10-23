"""Readable, self-contained synthetic agreements from the already accepted payment snapshot."""

import hashlib
import json
from html import escape
from pathlib import Path
from typing import Any

FONTS = Path(__file__).with_name("fonts")
TEMPLATE_VERSION = "credit-agreement-pdf-v1"
NOTICE = "ДЕМО. Синтетический документ, юридической силы не имеет"


def _money(value: Any) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


def render_credit(body: str, *, schedule_only: bool = False) -> bytes:
    # Imported lazily so schema export does not require native Pango libraries.
    from weasyprint import HTML  # type: ignore[import-untyped]
    from weasyprint.text.fonts import FontConfiguration  # type: ignore[import-untyped]
    from weasyprint.urls import URLFetcher, URLFetcherResponse  # type: ignore[import-untyped]

    data = json.loads(body)
    assets = {
        (FONTS / name).as_uri(): FONTS / name for name in ("PTSans-Regular.ttf", "PTSans-Bold.ttf")
    }

    # WeasyPrint's extension base has no typing markers.
    class LocalFonts(URLFetcher):  # type: ignore[misc]
        def fetch(self, url: str, headers: Any = None) -> Any:
            if url not in assets:
                raise ValueError("Only bundled PDF font assets may be loaded")
            return URLFetcherResponse(url, assets[url].read_bytes())

    title = "График платежей" if schedule_only else "Кредитный договор"
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(value))}</td>"
            for value in (
                row["number"],
                _money(row["paymentRub"]),
                _money(row["principalRub"]),
                _money(row["interestRub"]),
                _money(row["balanceRub"]),
            )
        )
        + "</tr>"
        for row in data["schedule"]
    )
    facts = (
        ("Заёмщик", data["borrower"]["name"]),
        ("ИНН", data["borrower"]["inn"]),
        ("Банк", data["bank"]),
        ("Продукт", data["product"]["title"]),
        ("Сумма / лимит", _money(data["amountRub"])),
        ("Срок", f"{data['termMonths']} мес."),
        ("Ставка", f"{data['ratePercent']}% годовых"),
        ("Ежемесячный платёж", _money(data["paymentRub"])),
        ("Последний платёж", _money(data["lastPaymentRub"])),
        ("Переплата", _money(data["overpaymentRub"])),
    )
    facts_html = "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in facts)
    markup = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>{title}</title>
    <style>
    @font-face {{font-family:PT;src:url('{(FONTS / "PTSans-Regular.ttf").as_uri()}')}}
    @font-face {{font-family:PT;src:url('{(FONTS / "PTSans-Bold.ttf").as_uri()}');font-weight:700}}
    @page {{size:A4;margin:18mm 16mm 22mm;
      @bottom-center {{content:'{NOTICE} · ' counter(page);font:8pt PT;color:#555}}}}
    body {{font:10.5pt PT;color:#222;line-height:1.35}} h1 {{font-size:21pt;margin:0 0 3mm}}
    h2 {{font-size:13pt;margin-top:7mm}} .notice {{color:#a02222;font-weight:700}}
    dl {{display:grid;grid-template-columns:42% 58%;gap:2mm;margin-top:6mm}}
    dt {{color:#555}} dd {{margin:0;font-weight:700;overflow-wrap:anywhere}}
    table {{width:100%;border-collapse:collapse;font-size:9pt}} thead {{display:table-header-group}}
    th,td {{border-bottom:1px solid #ddd;padding:2mm;text-align:right}}
    th {{background:#f3f3f3}} th:first-child,td:first-child {{text-align:left}}
    tr {{break-inside:avoid}} p {{overflow-wrap:anywhere}}
    </style><h1>{title}</h1><p>№ {escape(data["number"])} · Заявка {escape(data["applicationNumber"])}</p>
    <p class="notice">{NOTICE}</p><dl>{facts_html}</dl>
    <h2>Условия демонстрации</h2>
    <p>Условия зафиксированы при принятии предложения. Реальные обязательства и движение денег
    не возникают. Подпись подтверждает именно сохранённый файл. После изменения условий требуется
    новый договор и новая подпись.</p>
    <h2>График платежей</h2><p>Периоды отсчитываются от выдачи. Для лимитных продуктов график
    показывает расчётный сценарий использования; фактические условия отражены в кабинете.</p>
    <table><thead><tr><th>Период</th><th>Платёж</th><th>Основной долг</th><th>Проценты</th>
    <th>Остаток</th></tr></thead><tbody>{rows}</tbody></table>
    <p>Версия шаблона: {TEMPLATE_VERSION}. УИд: {escape(data["contractUid"])}.</p></html>"""
    return bytes(
        HTML(string=markup, url_fetcher=LocalFonts()).write_pdf(
            font_config=FontConfiguration(),
            pdf_identifier=hashlib.sha256((body + str(schedule_only)).encode()).hexdigest(),
        )
    )
