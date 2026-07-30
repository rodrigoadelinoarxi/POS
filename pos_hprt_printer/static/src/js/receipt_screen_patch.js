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

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(async () => {
            const order = this.currentOrder;
            const key = referenceOf(order) || String(backendIdOf(order) || "");
            if (key && !autoPrinted.has(key)) {
                autoPrinted.add(key);
                // Dá tempo ao Odoo para concluir a sincronização da venda.
                await new Promise((resolve) => setTimeout(resolve, 700));
                const ok = await this.printExternalReceipt(true);
                if (!ok) autoPrinted.delete(key);
            }
        });
    },

    _fiscalData(order) {
        try {
            const exportFn = this.orderExportForPrinting
                ? this.orderExportForPrinting.bind(this)
                : this.pos?.orderExportForPrinting?.bind(this.pos);
            const data = exportFn ? exportFn(order) : {};
            const fullHash = data?.inalterable_hash || data?.hash || "";
            const hashCode = fullHash.length > 30
                ? fullHash[0] + fullHash[10] + fullHash[20] + fullHash[30]
                : (fullHash || null);
            return {
                qr_code: data?.qr_code || data?.qrCode || null,
                atcud: data?.atcud || data?.ATCUD || null,
                hash_code: hashCode,
            };
        } catch (error) {
            console.warn("Não foi possível recolher QR/ATCUD/hash", error);
            return {};
        }
    },

    async printExternalReceipt(automatic = false) {
        const order = this.currentOrder;
        if (!order) return false;
        try {
            const result = await rpc("/pos_hprt_printer/print_receipt", {
                order_id: backendIdOf(order),
                pos_reference: referenceOf(order),
                receipt: this._fiscalData(order),
            });
            if (result.state === "error") {
                if (!automatic) this.notification.add(result.last_error || "Falha ao imprimir o talão.", { type: "danger" });
                return false;
            }
            if (!automatic) this.notification.add("Talão enviado para a impressora.", { type: "success" });
            return true;
        } catch (error) {
            console.error("Erro ao imprimir talão", error);
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
            console.error("Erro ao imprimir bebidas", error);
            this.notification.add("Erro de comunicação ao imprimir bebidas.", { type: "danger" });
        }
    },
});
