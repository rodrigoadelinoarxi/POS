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


def money(value):
    try:
        return f"{float(value):.2f} EUR"
    except (TypeError, ValueError):
        return "0.00 EUR"


def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(values):
    SEEN_FILE.write_text(json.dumps(sorted(values)))


def require_token():
    return bool(TOKEN) and request.headers.get("X-Print-Token", "") == TOKEN


def print_logo(p, encoded):
    if not encoded:
        return
    try:
        raw = base64.b64decode(encoded.split(",")[-1])
        image = Image.open(io.BytesIO(raw)).convert("L")
        image.thumbnail((384, 240))
        p.set(align="center")
        p.image(image)
        p.text("\n")
    except Exception:
        pass


def print_receipt(p, data):
    company = data.get("company") or {}
    print_logo(p, company.get("logo_base64"))
    p.set(align="center", bold=True, width=3, height=3)
    p.text((company.get("name") or "").strip() + "\n")
    p.set(align="center", bold=False, width=1, height=1)
    if company.get("vat"): p.text(f"NIF: {company['vat']}\n")
    address = " ".join(filter(None, [company.get("street"), company.get("street2")]))
    locality = " ".join(filter(None, [company.get("zip"), company.get("city")]))
    if address: p.text(address + "\n")
    if locality: p.text(locality + "\n")
    if company.get("phone"): p.text(f"Tel: {company['phone']}\n")
    p.text("-" * WIDTH + "\n")
    p.set(align="left")
    if data.get("cashier"): p.text(f"Atendido por: {data['cashier']}\n")
    if data.get("order_number"):
        p.set(align="center", bold=True, width=6, height=6)
        p.text(str(data["order_number"]) + "\n")
        p.set(align="left", bold=False, width=1, height=1)
    p.text(f"Documento: {data.get('order_ref') or ''}\n")
    p.text(f"Data: {data.get('date') or datetime.now().isoformat(timespec='seconds')}\n")
    partner = data.get("partner") or {}
    if partner.get("name"): p.text(f"Cliente: {partner['name']}\n")
    if partner.get("vat"): p.text(f"NIF Cliente: {partner['vat']}\n")
    p.text("-" * WIDTH + "\n")
    for line in data.get("lines") or []:
        name = str(line.get("product") or "")
        qty = line.get("qty", 0)
        unit = line.get("price_unit", 0)
        total = line.get("price_subtotal_incl", line.get("price_subtotal", 0))
        p.text(name + "\n")
        p.text(f"  {qty:g} x {money(unit)} = {money(total)}\n")
        if float(line.get("discount") or 0): p.text(f"  Desconto: {line['discount']}%\n")
    p.text("-" * WIDTH + "\n")
    p.text(f"Valor sem impostos: {money(data.get('amount_untaxed'))}\n")
    p.text(f"IVA: {money(data.get('amount_tax'))}\n")
    p.set(bold=True, width=2, height=2)
    p.text(f"TOTAL: {money(data.get('amount_total'))}\n")
    p.set(bold=False, width=1, height=1)
    for payment in data.get("payments") or []:
        p.text(f"{payment.get('method') or 'Pagamento'}: {money(payment.get('amount'))}\n")
    if float(data.get("change") or 0) > 0: p.text(f"Troco: {money(data.get('change'))}\n")
    p.text("-" * WIDTH + "\n")
    if data.get("atcud"): p.text(f"ATCUD: {data['atcud']}\n")
    if data.get("qr_code"):
        try:
            p.set(align="center")
            p.qr(str(data["qr_code"]), size=5)
        except Exception:
            p.text(str(data["qr_code"]) + "\n")
    p.set(align="left")
    if data.get("hash_code"): p.text(f"{data['hash_code']} - Processado pelo software\n")
    p.set(align="center")
    p.text("\nObrigado!\n\n")
    p.cut()


def print_beverages(p, data):
    numero_original = str(data.get("order_number") or "").strip()

    # O Odoo envia 037, mas mostra 137.
    if numero_original.isdigit():
        numero_pedido = str(int(numero_original) + 100)
    else:
        numero_pedido = numero_original

    print(
        "NUMERO_BEBIDAS_CORRIGIDO:",
        {
            "recebido": numero_original,
            "impresso": numero_pedido,
        },
        flush=True,
    )

    # Numero do pedido em grande, sem o titulo BEBIDAS.
    if numero_pedido:
        p.set(align="center", bold=True)
        p._raw(b"\x1d\x21\x77")
        p.text(numero_pedido + "\n")
        p._raw(b"\x1d\x21\x00")

    # Mesa logo abaixo do numero.
    p.set(align="center", bold=True, width=3, height=3)

    mesa = data.get("table")

    # Mesa grande (forçada).
    p.set(align="center", bold=True)
    p._raw(b"\x1d\x21\x33")

    if mesa:
        p.text(f"MESA: {mesa}\n")
    else:
        p.text("MESA: ---\n")

    p._raw(b"\x1d\x21\x00")
    p.set(align="center", bold=False, width=1, height=1)

    p.set(width=1, height=1, bold=False, align="center")

    if data.get("cashier"):
        p.text(f"Atendido por: {data['cashier']}\n")

    p.text("-" * WIDTH + "\n")

    # Produtos por baixo.
    p.set(align="left", bold=True, width=2, height=2)

    for line in data.get("lines") or []:
        qty = line.get("qty", 0)

        try:
            qty_text = f"{float(qty):g}"
        except (TypeError, ValueError):
            qty_text = str(qty)

        produto = str(line.get("product") or "")
        p.text(f"{qty_text} x {produto}\n")

        if line.get("note"):
            p.set(width=1, height=1, bold=False)
            p.text(f"  Nota: {line['note']}\n")
            p.set(width=2, height=2, bold=True)

    p.set(width=1, height=1, bold=False, align="center")
    p.text("\n" + str(data.get("date") or "") + "\n\n")
    p.cut()


@app.get("/health")
def health():
    error = None
    ok = True
    try:
        p = printer(); p.close()
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
