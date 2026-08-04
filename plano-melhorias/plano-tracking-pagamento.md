---
criado: 2026-06-10T15:17:24-03:00
atualizado: 2026-06-11T19:10:00-03:00
---

# Tracking de Links de Pagamento

## Objetivo

Rastrear quando um link de pagamento é enviado ao lead e quando o pagamento é efetivamente confirmado via webhook da Kiwify/Cakto. Após confirmação, enviar mensagem de parabéns + link de suporte. Links são gerados dinamicamente com UTMs e `src` do lead.

---

## Links Base (sem tracking)

| Tier | Valor | Link Base | Produto ID |
|------|-------|-----------|------------|
| 1 - Padrão | R$399 | `https://pay.kiwify.com.br/x1rMBUT` | `x1rMBUT` |
| 2 - Desconto | R$299 | `https://pay.kiwify.com.br/q1qKleb` | `q1qKleb` |
| 3 | R$249 | `https://pay.kiwify.com.br/COCyYNU` | `COCyYNU` |
| 4 | R$199 | `https://pay.kiwify.com.br/lj7aq9a` | `lj7aq9a` |
| 5 | R$179 | `https://pay.kiwify.com.br/7fPOC7X` | `7fPOC7X` |
| Desafio | R$47 | `https://pay.cakto.com.br/m42xe54` | - (Cakto) |

---

## Parâmetros de Tracking (UTM + src)

| Parâmetro | Descrição | Exemplo |
|-----------|-----------|---------|
| `utm_source` | Origem do tráfego | `whatsappIA` |
| `utm_campaign` | Tier/Oferta enviada | `full`, `tier_2`, `tier_3`, `tier_4`, `tier_5`, `desafio` |
| `src` | ID único do cliente (UUID do DataCrazy) | `2efce2f6-1481-4d42-b38d-b02a521ced4c` |

### Campanhas (utm_campaign)

| utm_campaign | Tier | Valor | Descrição |
|--------------|------|-------|-----------|
| `full` | 1 | R$399 | Preço cheio |
| `tier_2` | 2 | R$299 | Primeiro desconto |
| `tier_3` | 3 | R$249 | Segundo desconto |
| `tier_4` | 4 | R$199 | Terceiro desconto |
| `tier_5` | 5 | R$179 | Menor preço |
| `desafio` | - | R$47 | Desafio de 7 dias |

### Formato do Link com Tracking

```
https://pay.kiwify.com.br/{produto_id}?utm_source=whatsappIA&utm_campaign={tier}&src={lead_id}
```

Exemplos:
- Tier 1: `https://pay.kiwify.com.br/x1rMBUT?utm_source=whatsappIA&utm_campaign=full&src=2efce2f6-...`
- Tier 3: `https://pay.kiwify.com.br/COCyYNU?utm_source=whatsappIA&utm_campaign=tier_3&src=2efce2f6-...`
- Desafio: `https://pay.cakto.com.br/m42xe54?utm_source=whatsappIA&utm_campaign=desafio&src=2efce2f6-...`

> **Nota:** O `src` é o `ctx.external_id` (UUID do lead no DataCrazy). Sempre disponível no contexto do agente.

---

## Dados do Webhook Kiwify (Payload)

| Campo | Descrição |
|-------|-----------|
| `order_id` | ID único do pedido na Kiwify |
| `order_status` | Status do pedido (`paid`, `pending`, `refunded`) |
| `payment_method` | Método de pagamento (`pix`, `credit_card`, etc.) |
| `store_id` | ID da loja/produtor |
| `payment_merchant_id` | ID da operação de pagamento |
| `installments` | Número de parcelas (1 = à vista) |
| `product_name` | Nome do produto |
| `full_name` | Nome completo do cliente |
| `mobile` | WhatsApp/celular com DDD e código do país |
| `cpf` / `cnpj` | CPF ou CNPJ do cliente |
| `src` | ID único do cliente (UUID) — usado pra vincular ao lead |
| `utm_source` | UTM de origem |
| `utm_campaign` | UTM de campanha |

---

## Tabela no Banco de Dados

Criar tabela `payment_links` para rastreamento (no mesmo banco SQLite da VFO):

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER | PK auto-incremento |
| `lead_id` | TEXT | external_id do DataCrazy (UUID) |
| `phone` | TEXT | Telefone do lead |
| `session_id` | TEXT | vanessa-wa-{phone} |
| `link_url` | TEXT | Link completo gerado dinamicamente |
| `utm_source` | TEXT | whatsappIA |
| `utm_campaign` | TEXT | full, tier_2, tier_3, tier_4, tier_5, desafio |
| `link_sent` | INTEGER | 1 = link enviado |
| `link_sent_at` | TEXT | ISO timestamp do envio |
| `paid` | INTEGER | 1 = pagamento confirmado |
| `paid_at` | TEXT | ISO timestamp do pagamento |
| `order_id` | TEXT | ID do pedido na Kiwify/Cakto |
| `order_status` | TEXT | paid, refunded, pending |
| `payment_method` | TEXT | pix, credit_card |
| `product_name` | TEXT | Nome do produto |
| `amount` | REAL | Valor pago |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

---

## Endpoint de Webhook

**Rota:** `POST /vfo/webhooks/payment` e `POST /vfo-2/webhooks/payment`

Endpoint único que aceita webhooks de AMBAS as plataformas (Kiwify e Cakto). Detecta a origem pelo formato do payload.

**Configuração manual (Bruno faz):**
- Painel Kiwify → Configurações → Webhooks:
  - URL 1: `https://<seu-dominio>/vfo/webhooks/payment` (vanessa-1)
  - URL 2: `https://<seu-dominio>/vfo-2/webhooks/payment` (vanessa-2)
  - Eventos: `order.paid`, `order.refunded`
- Painel Cakto → Integrações → Webhooks:
  - URL 1: `https://<seu-dominio>/vfo/webhooks/payment` (vanessa-1)
  - URL 2: `https://<seu-dominio>/vfo-2/webhooks/payment` (vanessa-2)
  - Eventos: `purchase.complete`

---

## Fluxo Completo

```
1. Lead aceita preço
    ↓
2. send_payment_link(tier) ou send_challenge_link()
   → Gera link dinamicamente com UTMs + src={external_id}
   → Envia link ao lead
   → Registra em payment_links (link_sent=1, paid=0)
    ↓
3. Lead clica e paga na Kiwify/Cakto
    ↓
4. Kiwify/Cakto manda webhook → POST /vfo/webhooks/payment
    ↓
5. Handler:
   → Detecta origem (Kiwify ou Cakto)
   → Busca lead pelo src (external_id) ou mobile (telefone)
   → Atualiza payment_links (paid=1, order_id, order_status, etc)
   → Envia mensagem de parabéns + link de suporte
    ↓
6. Se order_status == "refunded":
   → Envia mensagem direcionando pro suporte
```

---

## Mensagens Pós-Compra

### Parabéns (pagamento confirmado — order.paid)

```
{nome}, parabéns! 🎉

Você acabou de dar o primeiro passo para transformar a sua vida!

Para os próximos passos e para você ter acesso ao treinamento, fala com meu time de suporte aqui:

https://wa.me/558599549121?text=oiii%20Van%2C%20j%C3%A1%20sou%20aluna%2C%20gostaria%20de%20ajuda

Bora pra cima! ✨
```

### Reembolso (order.refunded)

```
{nome}, tudo bem? Vi que você solicitou o reembolso.

Se precisar de qualquer ajuda ou tiver alguma dúvida, fala com meu time de suporte:

https://wa.me/558599549121?text=oiii%20Van%2C%20tenho%20uma%20d%C3%BAvida%20sobre%20meu%20pedido
```

---

## Observações Importantes

1. **`send_payment_link()` não muda a flag `is_purchased`** — essa flag continua sendo setada quando o link é enviado (como está hoje, serve pra controle interno de que o link foi mandado). A tabela `payment_links` é que rastreia se realmente pagou.

2. **Endpoint único** — um handler pra Kiwify e Cakto. Detecta a origem pelo payload.

3. **Webhook config** — Bruno configura manualmente nos painéis da Kiwify e Cakto.

4. **Links dinâmicos** — gerados em runtime no `send_payment_link()` e `send_challenge_link()`. Os links base ficam como constantes, os parâmetros UTM + src são adicionados na hora do envio.

5. **`external_id` como src** — `ctx.external_id` sempre vem do DataCrazy (UUID do lead). Usar direto no `send_payment_link()`.

6. **Desafio de 7 dias (Cakto)** — também dispara mensagem de parabéns após pagamento confirmado.

---

## Arquivos que Vão Mudar

| Arquivo | Mudança |
|---|---|
| `app/follow_up_state.py` | Criar tabela `payment_links` + init + funções CRUD |
| `tools/vanessa.py` | Gerar links dinâmicos + registrar envio na tabela |
| `app/whatsapp_api.py` | Novo endpoint `POST /vfo/webhooks/payment` |
| `prompts/vanessa.py` | Instrução: se lead confirmar pagamento, responder com parabéns + suporte |

---

## Pendências

- [x] Criar tabela `payment_links` no banco de dados
- [x] Implementar funções CRUD para `payment_links`
- [x] Gerar links dinâmicos com UTMs em `send_payment_link()`
- [x] Gerar links dinâmicos com UTMs em `send_challenge_link()`
- [x] Registrar envio na tabela `payment_links`
- [x] Criar endpoint `POST /vfo/webhooks/payment` em `whatsapp_api.py`
- [x] Implementar handler que detecta Kiwify vs Cakto
- [x] Implementar lógica de parabéns + link de suporte
- [x] Implementar lógica de refund → suporte
- [x] Atualizar prompt do agente para resposta pós-compra
- [x] Configurar webhook na Kiwify (manual — Bruno)
- [x] Configurar webhook na Cakto (manual — Bruno)
