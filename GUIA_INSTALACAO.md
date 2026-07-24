# Guia de Instalação e Atualização — POS HPRT + Cozinha

Este sistema tem **3 peças separadas**, cada uma numa máquina diferente.
Este guia explica o que fazer em cada uma, e quando é preciso mexer em
qual, para nunca ficares na dúvida.

---

## Visão geral da arquitetura

```
Odoo POS (browser, qualquer tablet)
        │
        ▼
Servidor Odoo (CloudPepper) ── módulo pos_hprt_printer
        │                              │
        │ Tailscale                    │ Tailscale
        ▼                              ▼
Raspberry Pi (HPRT)          PC Linux Cozinha (Aqprox)
        │                              │
        ▼                              ▼
Impressora HPRT TP80K        Impressora Aqprox POS80AM-USB
(recibo completo)             (talão simplificado p/ cozinha)
```

- **Servidor Odoo**: onde vive o módulo `pos_hprt_printer` (botões, fila,
  lógica de negócio).
- **Raspberry Pi**: só a impressora do recibo completo (HPRT).
- **PC Linux da Cozinha**: só a impressora do talão de cozinha (Aqprox).

---

## Regra geral: o que atualizar, consoante o que mudou

| O que mudou | Onde aplicar | Precisa de "Gerar ativos novamente"? |
|---|---|---|
| Só ficheiro `.py` do módulo Odoo (ex: `pos_print_job.py`, `main.py`) | Servidor Odoo | Não — só "Atualizar" o módulo em Apps |
| Ficheiro `.js` ou `.xml` do módulo Odoo (botões, template) | Servidor Odoo | **Sim** — obrigatório |
| `app.py` do Raspberry | Só o Raspberry | Não aplicável (não é Odoo) |
| `app.py` do PC da Cozinha | Só o PC da Cozinha | Não aplicável (não é Odoo) |
| Campo novo num modelo Python (ex: `job_type`) | Servidor Odoo | Não, mas **atenção**: se a instalação falhar com erro tipo `column "X" does not exist`, o "Atualizar" não chegou a correr a migração — repete o "Atualizar" no módulo |

---

## 1. Servidor Odoo — instalar/atualizar o módulo `pos_hprt_printer`

```bash
# no teu PC pessoal, depois de descarregares o zip mais recente:
scp pos_hprt_printer_module.zip root@100.118.242.23:/tmp/
```

```bash
# no servidor (SSH):
ssh root@100.118.242.23
cd /tmp && unzip -o pos_hprt_printer_module.zip

rm -rf /var/odoo/18.flybyodoo.online/extra-addons/pos.git-6a63439eeded8/pos_hprt_printer
cp -r pos_hprt_printer /var/odoo/18.flybyodoo.online/extra-addons/pos.git-6a63439eeded8/

sudo systemctl restart <nome-do-serviço-odoo>
```

Depois, na interface do Odoo:
1. **Apps** → tira o filtro "Apps" → procura **"POS HPRT"**
2. Clica no módulo → botão **"Atualizar"**
3. Se mudaste JS/XML (botões, templates): ícone do bug 🐞 (modo debug) →
   **"Gerar ativos novamente"**
4. No POS: **Ctrl+Shift+R** (hard refresh) antes de testar

**Como confirmar o nome do serviço**, se não souberes:
```bash
ps aux | grep odoo | grep -o '\-c [^ ]*'
systemctl list-units | grep -i odoo
```

**Como ver erros**, se a instalação falhar:
```bash
sudo journalctl -u <nome-do-serviço-odoo> -n 100 --no-pager | tail -60
```

---

## 2. Raspberry Pi — atualizar a API da HPRT

```bash
# no teu PC:
scp raspberry_api.zip aministrator@100.109.78.81:/tmp/
```

```bash
# no Raspberry (SSH):
ssh aministrator@100.109.78.81
cd /tmp && unzip -o raspberry_api.zip

sudo cp raspberry_api/app.py /opt/hprt-print-api/app.py
sudo systemctl restart hprt-print-api
```

**Confirmar que ficou bem:**
```bash
sudo systemctl status hprt-print-api
curl http://127.0.0.1:5000/health
```

**Ver erros:**
```bash
sudo journalctl -u hprt-print-api -n 50 --no-pager
```

**Primeira instalação de raiz (só se for um Raspberry novo):**
```bash
cd raspberry_api
sudo bash install.sh          # instala tudo, gera o token
sudo bash firewall_setup.sh   # restringe à rede Tailscale
```

---

## 3. PC Linux da Cozinha — atualizar a API da Aqprox

Exatamente o mesmo padrão do Raspberry, só muda o nome do serviço:

```bash
# no teu PC:
scp kitchen_api.zip administrator@100.70.69.26:/tmp/
```

```bash
# no PC da cozinha (SSH):
ssh administrator@100.70.69.26
cd /tmp && unzip -o kitchen_api.zip

sudo cp kitchen_api/app.py /opt/kitchen-print-api/app.py
sudo systemctl restart kitchen-print-api
```

**Confirmar:**
```bash
sudo systemctl status kitchen-print-api
curl http://127.0.0.1:5000/health
```

**Ver erros:**
```bash
sudo journalctl -u kitchen-print-api -n 50 --no-pager
```

**Primeira instalação de raiz:**
```bash
cd kitchen_api
sudo bash install.sh
sudo bash firewall_setup.sh
```

---

## Checklist rápida quando algo não funciona

1. **O botão não aparece no POS** → faltou "Gerar ativos novamente" no
   servidor Odoo, ou faltou hard refresh (Ctrl+Shift+R) no browser.
2. **Erro `column "X" does not exist`** → o "Atualizar" do módulo não
   chegou a correr a migração — repete o "Atualizar" em Apps.
3. **"Erro de comunicação com o servidor"** no POS → olha para o log
   do Odoo (`journalctl -u <serviço-odoo>`), o erro real está lá.
4. **Job fica "pendente" ou "erro" na Fila/Histórico** → a máquina de
   destino (Raspberry ou PC cozinha) está desligada, sem Tailscale, ou
   a firewall está a bloquear — testa com `curl` a partir do servidor
   Odoo: `curl http://<IP_TAILSCALE>:5000/health`
5. **Impressora não imprime, mas a API responde 200** → confirma
   `lsusb` e os valores `PRINTER_VENDOR_ID`/`PRINTER_PRODUCT_ID`/
   `PRINTER_OUT_EP`/`PRINTER_IN_EP` no ficheiro `env` de cada máquina.

---

## Parâmetros de Sistema no Odoo (Definições Técnicas → Parâmetros)

| Chave | Valor |
|---|---|
| `pos_hprt_printer.url` | `http://100.109.78.81:5000/print` |
| `pos_hprt_printer.token` | `7fda588798ec937eb60e20dda7cff8067a23239b05d00ee223f42fe2483f254c` |
| `pos_hprt_printer.kitchen_url` | `http://100.70.69.26:5000/print` |
| `pos_hprt_printer.kitchen_token` | `4e5347e34bc6e23c19b4f14979e47cfb8e13e68b8412469a34bce0ddcd932b0a` |

---

## IPs e tokens já confirmados (para referência rápida)

| Máquina | IP Tailscale | Serviço | Token (parâmetro Odoo) |
|---|---|---|---|
| Servidor Odoo | 100.118.242.23 | — | — |
| Raspberry (HPRT) | 100.109.78.81 | `hprt-print-api` | `pos_hprt_printer.token` |
| PC Cozinha (Aqprox) | 100.70.69.26 | `kitchen-print-api` | `pos_hprt_printer.kitchen_token` |
