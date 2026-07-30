#!/usr/bin/env python3
import base64
import hashlib
import io
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from PIL import Image
from escpos.printer import Usb

app = Flask(__name__)
TOKEN = os.environ.get("PRINT_TOKEN", "")
VENDOR_ID = int(os.environ.get("PRINTER_VENDOR_ID", "0x0000"), 16)
PRODUCT_ID = int(os.environ.get("PRINTER_PRODUCT_ID", "0x0000"), 16)
OUT_EP = int(os.environ.get("PRINTER_OUT_EP", "0x01"), 16)
IN_EP = int(os.environ.get("PRINTER_IN_EP", "0x81"), 16)
DATA_DIR = Path(os.environ.get("PRINT_DATA_DIR", "/var/lib/pos-print-api"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "printed_jobs.json"
LOCK = threading.Lock()
WIDTH = 48


def printer():
    return Usb(VENDOR_ID, PRODUCT_ID, 0, out_ep=OUT_EP, in_ep=IN_EP, timeout=8000)


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value, symbol="EUR"):
    if isinstance(value, str) and any(ch.isdigit() for ch in value):
        return value
    return f"{number(value):.2f} {symbol}"


def first(mapping, *keys, default=None):
    for key in keys:
        if isinstance(mapping, dict) and mapping.get(key) not in (None, ""):
            return mapping[key]
    return default


def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(values):
    SEEN_FILE.write_text(json.dumps(sorted(values)))


def require_token():
    return bool(TOKEN) and request.headers.get("X-Print-Token", "") == TOKEN


def decode_image(value):
    if not value:
        return None
    if isinstance(value, dict):
        value = first(value, "src", "data", "base64")
    if not isinstance(value, str):
        return None
    try:
        raw = base64.b64decode(value.split(",")[-1])
        return Image.open(io.BytesIO(raw)).convert("L")
    except Exception:
        return None


def print_image(p, value, max_size=(384, 260)):
    image = decode_image(value)
    if image is None:
        return
    image.thumbnail(max_size)
    p.set(align="center")
    p.image(image)
    p.text("\n")


def normalize_line(line):
    product = first(line, "productName", "product_name", "product", "name", "full_product_name", default="")
    qty = first(line, "quantity", "qty", default=0)
    unit_name = first(line, "unit_name", "uom_name", "unit", default="")
    unit_price = first(line, "price_without_discount", "price_unit", "unit_price", "price", default=0)
    total = first(line, "price_with_tax", "price_subtotal_incl", "price_subtotal", "total", default=0)
    discount = first(line, "discount", "discountPercent", default=0)
    note = first(line, "customer_note", "note", default="")
    return {
        "product": product,
        "qty": qty,
        "unit": unit_name,
        "unit_price": unit_price,
        "total": total,
        "discount": discount,
        "note": note,
    }


def normalize_payment(payment):
    return {
        "name": first(payment, "name", "payment_method_name", "method", default="Pagamento"),
        "amount": first(payment, "amount", "amount_formatted", default=0),
    }


def receipt_view(data):
    raw = data.get("odoo_receipt") or {}
    header = raw.get("headerData") or raw.get("header_data") or {}
    company = raw.get("company") or header.get("company") or data.get("company") or {}
    partner = raw.get("partner") or raw.get("customer") or data.get("partner") or {}
    lines_raw = first(raw, "orderlines", "order_lines", "lines", default=None) or data.get("lines") or []
    payments_raw = first(raw, "paymentlines", "payment_lines", "payments", default=None) or data.get("payments") or []
    currency = first(raw, "currency_symbol", "currencySymbol", default="EUR")
    full_hash = first(raw, "inalterable_hash", "hash", "hash_code", default=data.get("hash_code"))
    hash_code = full_hash
    if isinstance(full_hash, str) and len(full_hash) > 30:
        hash_code = full_hash[0] + full_hash[10] + full_hash[20] + full_hash[30]
    return {
        "company": company,
        "partner": partner,
        "logo": first(company, "logo", "logo_base64", default=first(header, "logo")),
        "cashier": first(raw, "cashier", "cashier_name", "served_by", default=data.get("cashier")),
        "order_number": first(raw, "order_number", "ticket_number", "sequence_number", default=data.get("order_number")),
        "order_ref": first(raw, "name", "order_name", "pos_reference", default=data.get("order_ref")),
        "date": first(raw, "date", "date_order", "order_date", default=data.get("date")),
        "lines": [normalize_line(line) for line in lines_raw if isinstance(line, dict)],
        "payments": [normalize_payment(payment) for payment in payments_raw if isinstance(payment, dict)],
        "untaxed": first(raw, "total_without_tax", "amount_untaxed", "subtotal", default=data.get("amount_untaxed")),
        "tax": first(raw, "total_tax", "amount_tax", "tax", default=data.get("amount_tax")),
        "total": first(raw, "total_with_tax", "amount_total", "total", "total_paid", default=data.get("amount_total")),
        "change": first(raw, "change", "change_amount", default=data.get("change")),
        "qr": first(raw, "qr_code", "qrCode", default=data.get("qr_code")),
        "atcud": first(raw, "atcud", "ATCUD", default=data.get("atcud")),
        "hash": hash_code,
        "footer": first(raw, "footer", "footer_text", default=""),
        "currency": currency,
    }


def _plain_text(value):
    return "" if value is None else str(value).replace("\n", " ").strip()


def _money_pt(value, symbol="EUR"):
    """Formata valores como o recibo português do Odoo: 1,00 €."""
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    amount = number(value)
    rendered = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    currency = "€" if str(symbol).upper() in ("EUR", "€") else str(symbol)
    return f"{rendered} {currency}".strip()


def _qty_pt(value):
    amount = number(value)
    return f"{amount:.2f}".replace(".", ",")


def _row(left, right, width=WIDTH):
    left = _plain_text(left)
    right = _plain_text(right)
    if not right:
        return left[:width]
    available = max(width - len(right) - 1, 1)
    return f"{left[:available]:<{available}} {right}"[:width]


def _short_separator():
    return "-" * 24


def print_receipt(p, data):
    """Imprime o recibo na mesma ordem visual do ecrã de recibo do Odoo.

    O conteúdo vem de ``odoo_receipt`` (export_for_printing do POS). A API
    apenas o adapta à largura térmica de 80 mm; não recalcula a venda.
    """
    view = receipt_view(data)
    company = view["company"] or {}

    # Cabeçalho igual ao recibo mostrado no POS.
    print_image(p, view["logo"], max_size=(300, 230))
    p.set(align="center", bold=False, width=1, height=1)
    company_name = _plain_text(first(company, "name", default=""))
    if company_name:
        p.text(company_name + "\n")
    p.text(_short_separator() + "\n")
    if view["cashier"]:
        p.text(f"Servido por {_plain_text(view['cashier'])}\n")

    # O número é propositadamente 4x e a negrito, conforme pedido.
    if view["order_number"]:
        p.set(align="center", bold=True, width=4, height=4)
        p.text(_plain_text(view["order_number"]) + "\n")
        p.set(align="center", bold=False, width=1, height=1)
    p.text("\n")

    # Linhas: nome e total na mesma linha; quantidade/preço/unidade por baixo.
    for line in view["lines"]:
        product = _plain_text(line["product"])
        total = _money_pt(line["total"], view["currency"])
        p.set(align="left", bold=False, width=1, height=1)
        p.text(_row(product, total) + "\n")
        unit = _plain_text(line["unit"]) or "Unidades"
        detail = f"{_qty_pt(line['qty'])} x {_money_pt(line['unit_price'], view['currency'])} / {unit}"
        p.text(detail[:WIDTH] + "\n")
        if number(line["discount"]):
            p.text(f"Desconto: {number(line['discount']):g}%\n")
        if line["note"]:
            p.text(f"Nota: {_plain_text(line['note'])}\n")
        p.text("\n")

    p.set(align="center", bold=False, width=1, height=1)
    p.text(_short_separator() + "\n")
    p.set(align="left")

    # Totais exatamente na ordem do recibo Odoo: TOTAL, pagamentos, TROCO.
    p.text(_row("TOTAL", _money_pt(view["total"], view["currency"])) + "\n")
    for payment in view["payments"]:
        p.text(_row(payment["name"], _money_pt(payment["amount"], view["currency"])) + "\n")
    if view["change"] not in (None, ""):
        p.text(_row("TROCO", _money_pt(view["change"], view["currency"])) + "\n")

    # Dados fiscais, quando o módulo fiscal do Odoo os fornece.
    if view["atcud"] or view["qr"] or view["hash"]:
        p.text("\n" + "-" * WIDTH + "\n")
        if view["atcud"]:
            p.text(f"ATCUD: {_plain_text(view['atcud'])}\n")
        if view["qr"]:
            try:
                qr_image = decode_image(view["qr"])
                p.set(align="center")
                if qr_image is not None:
                    qr_image.thumbnail((290, 290))
                    p.image(qr_image)
                else:
                    p.qr(str(view["qr"]), size=5)
                p.text("\n")
            except Exception:
                p.set(align="left")
                p.text(_plain_text(view["qr"]) + "\n")
        if view["hash"]:
            p.set(align="left")
            p.text(f"{_plain_text(view['hash'])} - Processado pelo software\n")

    # Rodapé original do ecrã Odoo.
    p.set(align="center", bold=False, width=1, height=1)
    if view["footer"]:
        p.text("\n" + _plain_text(view["footer"]) + "\n")
    p.text("\nPowered by Odoo\n\n")
    if view["order_ref"]:
        reference = _plain_text(view["order_ref"])
        if not reference.lower().startswith(("pedido", "order")):
            reference = "Pedido " + reference
        p.text(reference + "\n")
    if view["date"]:
        p.text(_plain_text(view["date"]) + "\n")
    p.text("\n\n")
    p.cut()


def print_beverages(p, data):
    p.set(align="center", bold=True, width=2, height=2)
    p.text("BEBIDAS\n")
    if data.get("order_number"):
        p.set(align="center", bold=True, width=4, height=4)
        p.text(str(data["order_number"]) + "\n")
    p.set(width=1, height=1, bold=False)
    if data.get("table"):
        p.text(f"Mesa: {data['table']}\n")
    if data.get("cashier"):
        p.text(f"Atendido por: {data['cashier']}\n")
    p.text("-" * WIDTH + "\n")
    p.set(align="left", bold=True, width=2, height=2)
    for line in data.get("lines") or []:
        qty = number(line.get("qty"))
        p.text(f"{qty:g} x {line.get('product') or ''}\n")
        if line.get("note"):
            p.set(width=1, height=1, bold=False)
            p.text(f"  Nota: {line['note']}\n")
            p.set(width=2, height=2, bold=True)
    p.set(width=1, height=1, bold=False, align="center")
    p.text("\n" + (data.get("date") or "") + "\n\n")
    p.cut()


@app.get("/health")
def health():
    error = None
    ok = True
    try:
        p = printer()
        p.close()
    except Exception as exc:
        ok, error = False, str(exc)
    return jsonify(status="ok", printer_reachable=ok, printer_error=error,
                   vendor_id=hex(VENDOR_ID), product_id=hex(PRODUCT_ID))


@app.post("/print")
def do_print():
    if not require_token():
        return jsonify(status="error", error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or hashlib.sha256(request.data).hexdigest())
    with LOCK:
        seen = load_seen()
        if job_id in seen:
            return jsonify(status="duplicate", job_id=job_id)
        try:
            p = printer()
            if data.get("document_type") == "beverages":
                print_beverages(p, data)
            else:
                print_receipt(p, data)
            p.close()
            seen.add(job_id)
            save_seen(seen)
            return jsonify(status="printed", job_id=job_id)
        except Exception as exc:
            app.logger.exception("Printing failed")
            return jsonify(status="error", error=str(exc)), 500
