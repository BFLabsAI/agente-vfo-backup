# Webhook WhatsApp Cloud API para múltiplos números — guia técnico

Baseado em: `developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview` e `.../webhooks/override/`

Cenário: 1 Meta App, 2+ `phone_number_id`, mesma WABA ou WABAs diferentes sob o mesmo portfolio do cliente.

---

## Opção A — Um único webhook para todos os números (sem override)

**Isso é o padrão da plataforma.** O App Dashboard só expõe um campo de Callback URL. Sem nenhuma configuração adicional, todo número e toda WABA inscritos nesse App mandam eventos para essa única URL. Você diferencia a origem dentro do próprio payload.

### Como configurar

1. **App Dashboard → seu App → WhatsApp → Configuration** (ou **Use cases → Customize → Configuration**, se o App foi criado via use case "Connect with customers through WhatsApp").
2. Preencha **Callback URL** (seu endpoint HTTPS) e **Verify Token** (string arbitrária que você define).
3. Clique em **Verify and Save** — a Meta faz uma requisição `GET` ao seu endpoint com `hub.mode`, `hub.verify_token` e `hub.challenge`; seu endpoint deve responder o `hub.challenge` em texto puro se `hub.verify_token` bater com o que você configurou.
4. Na mesma tela, marque os **campos (fields)** que você quer receber: no mínimo `messages`. Adicione `message_template_status_update`, `account_update` etc. conforme necessidade.
5. Garanta que o App está inscrito na WABA — isso acontece automaticamente ao adicionar o número via API Setup/Embedded Signup, ou manualmente via `POST /<WABA_ID>/subscribed_apps` sem body (inscrição simples, sem override).
6. Repita a inscrição para cada WABA adicional que o App for atender (se os números estiverem em WABAs diferentes do mesmo portfolio do cliente).
7. Coloque o App em **modo Live** — alguns webhooks não são enviados em modo Dev.

Isso é tudo. Nenhuma chamada extra por número é necessária — o roteamento acontece no seu lado, não no lado da Meta.

### Como rotear internamente

Todo payload traz a origem explícita:

```
entry[].id                                              → WABA ID
entry[].changes[].value.metadata.phone_number_id        → qual número recebeu o evento
entry[].changes[].value.metadata.display_phone_number   → número em formato de exibição
```

Exemplo real de payload (mensagem recebida), conforme a doc:

```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "102290129340398",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15550783881",
              "phone_number_id": "106540352242922"
            },
            "contacts": [ { "profile": { "name": "Sheena Nelson" }, "wa_id": "16505551234" } ],
            "messages": [ { "from": "16505551234", "id": "wamid...", "timestamp": "1749416383" } ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
```

Lógica de dispatch mínima (pseudocódigo):

```python
def handle_webhook(payload):
    for entry in payload["entry"]:
        waba_id = entry["id"]
        for change in entry["changes"]:
            value = change["value"]
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            # roteie para o handler correto usando phone_number_id (ou waba_id se for por WABA)
            handler = ROUTING_MAP.get(phone_number_id)
            if handler is None:
                log_warning(f"phone_number_id desconhecido: {phone_number_id}")
                continue
            handler(change)
```

Pontos de atenção:

- **Chave a usar:** `phone_number_id`, não `display_phone_number`. O `display_phone_number` vem formatado (com ou sem `+`, espaços variam) e gera bugs de matching sutis. `phone_number_id` é um ID numérico estável.
- **Mapa de roteamento sempre com fallback explícito.** Se você adicionar um número novo e esquecer de atualizar o mapa, os eventos chegam mas são silenciosamente descartados — trate isso como erro logado, não como `else` mudo.
- **Retentativas duplicadas:** se seu endpoint não responder `200`, a Meta reenvia com frequência decrescente por até 7 dias, e reenvia para todos os Apps inscritos na WABA. Isso pode gerar notificações duplicadas — sua lógica de processamento deve ser idempotente (dedupe por `messages[].id` / `wamid`).

**Quando essa opção é suficiente:** praticamente sempre, para o seu caso (App próprio, 1 cliente, N números). É a opção mais simples de manter e a que eu recomendo como padrão.

---

## Opção B — Override de callback URL (endpoints fisicamente separados)

Use isso só se houver razão operacional real: números atendidos por serviços/times diferentes, isolamento de falha, filas separadas na sua infra, etc. Não é necessário para simplesmente "ter mais de um número".

### Como funciona a resolução

Ordem de prioridade documentada:

1. Existe override no **número** (`phone_number`)? → usa essa URL.
2. Não existe no número, mas existe no **WABA**? → usa essa URL.
3. Nenhum dos dois? → cai na callback padrão do **App**.

### Campos que aceitam override

`messages`, `message_echoes`, `calls`, `consumer_profile`, `messaging_handovers`, `group_lifecycle_update`, `group_participants_update`, `group_settings_update`, `group_status_update`, `smb_message_echoes`, `smb_app_state_sync`, `history`, `account_settings_update`.

**Não aceitam override — sempre vão para a callback padrão do App, sem exceção:** `message_template_status_update`, `message_template_quality_update`, `message_template_components_update`, `template_category_update`, `account_update`, `account_review_update`, `account_alerts`.

### Pré-requisito

O App precisa já estar inscrito em webhooks na WABA (Opção A, passo 5) e você precisa de um token com `whatsapp_business_management` sobre essa WABA/número. Confirme que o endpoint alternativo consegue receber e processar o request de verificação antes de configurar.

### B1 — Override no nível de WABA

Aplica-se a todos os números daquela WABA que não tenham um override próprio (nível número tem prioridade sobre nível WABA).

**Configurar:**

```
POST /<WABA_ID>/subscribed_apps
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "override_callback_uri": "https://minha-url-alternativa.com/webhook",
  "verify_token": "meu_token_secreto"
}
```

Resposta esperada: `{ "success": true }`

**Consultar o que está configurado:**

```
GET /<WABA_ID>/subscribed_apps
Authorization: Bearer <ACCESS_TOKEN>
```

Retorna, entre outros campos, `override_callback_uri` se houver um configurado.

**Remover o override** (volta a usar a callback padrão do App): repita o `POST /<WABA_ID>/subscribed_apps` **sem** os parâmetros `override_callback_uri` e `verify_token` no body — isso reinscreve o App normalmente e apaga o override.

### B2 — Override no nível de número (mais granular)

Sobrepõe qualquer override de WABA para aquele número específico.

**Configurar:**

```
POST /<BUSINESS_PHONE_NUMBER_ID>
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "webhook_configuration": {
    "override_callback_uri": "https://minha-url-do-numero-x.com/webhook",
    "verify_token": "meu_token_secreto"
  }
}
```

Resposta esperada: `{ "success": true }`

**Consultar o que está configurado (mostra os 3 níveis de uma vez):**

```
GET /<BUSINESS_PHONE_NUMBER_ID>?fields=webhook_configuration
Authorization: Bearer <ACCESS_TOKEN>
```

Resposta:

```json
{
  "webhook_configuration": {
    "phone_number": "https://minha-url-do-numero-x.com/webhook",
    "whatsapp_business_account": "https://minha-url-alternativa.com/webhook",
    "application": "https://minha-callback-padrao.com/webhook"
  },
  "id": "106540352242922"
}
```

`whatsapp_business_account` só aparece se a WABA associada também tiver override configurado.

**Remover o override do número:**

```json
{
  "webhook_configuration": {
    "override_callback_uri": ""
  }
}
```
(mesmo endpoint `POST /<BUSINESS_PHONE_NUMBER_ID>`, string vazia)

### Regras práticas B1 x B2

| Situação | Onde configurar override |
|---|---|
| Isolar todos os números de uma WABA inteira | B1, no `WABA_ID` |
| Isolar só um número específico dentro de uma WABA compartilhada | B2, no `BUSINESS_PHONE_NUMBER_ID` |
| Um número precisa de exceção dentro de uma WABA já com override | B2 nesse número — vence sobre o override da WABA |
| Eventos de template/conta (`account_update` etc.) | Não dá pra isolar — sempre vai para a callback do App, use a Opção A para esses campos |

### Checklist antes de ativar override em produção

- [ ] Endpoint alternativo já responde `200` e processa o payload de teste (`App Dashboard > WhatsApp > Configurations` tem botão de teste, ou use o test webhook endpoint)
- [ ] `verify_token` do override é diferente do padrão do App, se você quiser rastrear qual canal está sendo usado
- [ ] Lógica de dedupe por `wamid` também está no endpoint alternativo (retentativas de 7 dias valem aqui também)
- [ ] Se depois quiser reverter, sabe o comando de remoção (B1 ou B2 acima) — não existe botão no App Dashboard pra isso, é só via API

---

## Recomendação para o seu caso

Comece pela **Opção A**. Ela cobre 2+ números sem nenhuma chamada extra de configuração, e o roteamento por `phone_number_id` é trivial de implementar e testar. Migre partes específicas para **Opção B** só quando surgir uma necessidade concreta de isolamento físico — não antecipe a complexidade.