/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { rpc } from "@web/core/network/rpc";

// Este patch NÃO mexe no botão "Imprimir" já existente (nem no standard
// do Odoo, nem no do módulo de certificação fiscal l10n_pt_ao_pos).
// Em vez disso, o template receipt_screen_patch.xml acrescenta um botão
// NOVO, independente, chamado "Imprimir Talão (HPRT)", que chama
// diretamente o método abaixo.
patch(ReceiptScreen.prototype, {
    async printOnHprt() {
        const order = this.currentOrder;
        if (!order || !order.id) {
            this.notification.add(
                "Encomenda ainda não sincronizada com o servidor — não é possível imprimir na HPRT.",
                { type: "warning" }
            );
            return;
        }

        // Reaproveita a mesma função que os botões "Duplicado"/"Triplicado"
        // já usam, para obter exatamente os mesmos dados fiscais (QR,
        // ATCUD, hash) que aparecem no ecrã — sem duplicar essa lógica.
        let fiscalData = {};
        try {
            const exportFn = this.orderExportForPrinting
                ? this.orderExportForPrinting.bind(this)
                : this.pos.orderExportForPrinting.bind(this.pos);
            const data = exportFn(order);
            let hashCode = null;
            if (data.inalterable_hash && data.inalterable_hash.length > 30) {
                hashCode =
                    data.inalterable_hash[0] +
                    data.inalterable_hash[10] +
                    data.inalterable_hash[20] +
                    data.inalterable_hash[30];
            }
            fiscalData = {
                qr_code: data.qr_code || null,
                atcud: data.atcud || null,
                hash_code: hashCode,
            };
        } catch (error) {
            console.warn("pos_hprt_printer: não foi possível obter dados fiscais (QR/ATCUD)", error);
        }

        try {
            const result = await rpc("/pos_hprt_printer/print_receipt", {
                order_id: order.id,
                receipt: fiscalData,
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
