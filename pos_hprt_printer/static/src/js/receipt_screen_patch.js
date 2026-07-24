/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { rpc } from "@web/core/network/rpc";

// Este patch intercepta o método "printReceipt", que é exatamente o
// método chamado pelo botão "Imprimir" já existente no ecrã de recibo
// do POS (confirmado no código-fonte do point_of_sale 18.0). Ou seja,
// não criamos um botão novo: o botão "Imprimir" passa a também enviar
// o recibo para a impressora HPRT via Raspberry Pi.
patch(ReceiptScreen.prototype, {
    async printReceipt() {
        // 1) Envia para a impressora térmica HPRT (via Raspberry/Tailscale)
        await this._printOnHprt();

        // 2) Mantém o comportamento normal do Odoo (impressão web/estado
        //    interno da encomenda), para não quebrar outras partes do POS.
        return super.printReceipt(...arguments);
    },

    async _printOnHprt() {
        const order = this.currentOrder;
        if (!order || !order.id) {
            this.notification.add(
                "Encomenda ainda não sincronizada com o servidor — não é possível imprimir na HPRT.",
                { type: "warning" }
            );
            return;
        }

        try {
            const result = await rpc("/pos_hprt_printer/print_receipt", {
                order_id: order.id,
            });

            if (result.state === "error") {
                this.notification.add(
                    "Falha ao enviar para a impressora HPRT: " + (result.last_error || "erro desconhecido"),
                    { type: "danger" }
                );
            } else {
                this.notification.add("Talão enviado para a impressora HPRT.", {
                    type: "success",
                });
            }
        } catch (error) {
            this.notification.add(
                "Erro de comunicação com o servidor ao enviar para a HPRT.",
                { type: "danger" }
            );
            console.error("pos_hprt_printer: erro RPC print_receipt", error);
        }
    },
});
