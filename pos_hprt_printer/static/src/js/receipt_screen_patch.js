/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { rpc } from "@web/core/network/rpc";
import { onMounted } from "@odoo/owl";

const autoPrinted = new Set();

function referenceOf(order) {
    return order?.pos_reference || order?.name || order?.get_name?.() || "";
}

function backendIdOf(order) {
    const candidates = [order?.server_id, order?.backendId, order?.backend_id, order?.id];
    for (const value of candidates) {
        if (Number.isInteger(value) || (typeof value === "string" && /^\d+$/.test(value))) {
            return Number(value);
        }
    }
    return null;
}

function toPlainJson(value) {
    try {
        return JSON.parse(JSON.stringify(value));
    } catch (error) {
        console.warn("pos_hprt_printer: dados do recibo não serializáveis", error);
        return {};
    }
}

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(async () => {
            const order = this.currentOrder;
            const key = referenceOf(order) || String(backendIdOf(order) || "");
            if (key && !autoPrinted.has(key)) {
                autoPrinted.add(key);
                await new Promise((resolve) => setTimeout(resolve, 700));
                const ok = await this.printExternalReceipt(true);
                if (!ok) autoPrinted.delete(key);
            }
        });
    },

    _completeReceiptData(order) {
        const exporters = [
            () => order?.export_for_printing?.(),
            () => order?.exportForPrinting?.(),
            () => this.orderExportForPrinting?.(order),
            () => this.pos?.orderExportForPrinting?.(order),
        ];
        for (const exportReceipt of exporters) {
            try {
                const data = exportReceipt();
                if (data && typeof data === "object") {
                    return toPlainJson(data);
                }
            } catch (error) {
                console.warn("pos_hprt_printer: método de exportação de recibo falhou", error);
            }
        }
        return {};
    },

    async printExternalReceipt(automatic = false) {
        const order = this.currentOrder;
        if (!order) return false;
        try {
            const receiptData = this._completeReceiptData(order);
            const result = await rpc("/pos_hprt_printer/print_receipt", {
                order_id: backendIdOf(order),
                pos_reference: referenceOf(order),
                receipt: receiptData,
            });
            if (result.state === "error") {
                if (!automatic) {
                    this.notification.add(result.last_error || "Falha ao imprimir o talão.", { type: "danger" });
                }
                return false;
            }
            if (!automatic) this.notification.add("Talão enviado para a impressora.", { type: "success" });
            return true;
        } catch (error) {
            console.error("pos_hprt_printer: erro ao imprimir talão", error);
            if (!automatic) this.notification.add("Erro de comunicação ao imprimir o talão.", { type: "danger" });
            return false;
        }
    },

    async printBeverages() {
        const order = this.currentOrder;
        if (!order) return;
        try {
            const result = await rpc("/pos_hprt_printer/print_beverages", {
                order_id: backendIdOf(order),
                pos_reference: referenceOf(order),
            });
            if (result.state === "error") {
                this.notification.add(result.last_error || "Falha ao imprimir bebidas.", { type: "danger" });
            } else {
                this.notification.add("Ticket de bebidas enviado.", { type: "success" });
            }
        } catch (error) {
            console.error("pos_hprt_printer: erro ao imprimir bebidas", error);
            this.notification.add("Erro de comunicação ao imprimir bebidas.", { type: "danger" });
        }
    },
});
