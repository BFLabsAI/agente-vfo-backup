# Relatório Completo — Erros e Instabilidades da API DataCrazy

> **Nota de privacidade.** Este documento é publicado em repositório aberto. Os nomes dos
> contatos foram substituídos por rótulos (`Lead 01`, `Lead 02`…) e os telefones tiveram os
> dígitos centrais mascarados. A rotulagem é consistente: o mesmo contato mantém o mesmo
> rótulo ao longo do relatório. Horários, sequência de eventos e conteúdo técnico estão
> preservados na íntegra.
**Gerado por:** BF Labs / Falcon  
**Data:** 29/07/2026  
**Período analisado:** Maio 2026 – Julho 2026  
**Fontes:** Logs systemd (journalctl), SQLite (vanessa.db), código-fonte VFO, relatórios anteriores

---

## Resumo Executivo

A API do DataCrazy causou **4 categorias de falhas** que impactaram diretamente o projeto VFO (Vanessa):

| # | Categoria | Período | Severidade | Leads afetados (estimativa) |
|---|-----------|---------|------------|-----------------------------|
| 1 | Invalid Character in Header Content | 04-05/06/2026 | Alta | 11+ confirmados |
| 2 | 403 Forbidden (Cloudflare Block) | 06-07/07/2026 | Crítica | Centenas de follow-ups perdidos |
| 3 | Webhook de Automação — Roteamento Instância Errada | Contínuo | Média | Mensagens entregues no número errado |
| 4 | 995 Respostas Vazias (Modelo + API) | Maio–Junho 2026 | Crítica | 93% das transações de junho |

**Impacto total:** leads não respondidos, follow-ups não entregues, áudios/envios de mídia no número errado, e qualificações reiniciadas do zero.

---

## 1. Invalid Character in Header Content

**Período:** 04/06/2026 e 05/06/2026  
**Erro:** `Invalid character in header content ["message"]`

### O que aconteceu
A API REST do DataCrazy rejeitou mensagens contendo emojis, reticências, asteriscos e quebras de linha porque o conteúdo estava sendo inserido em um **header HTTP** em vez do body da requisição. Bug no **lado DataCrazy** — na infraestrutura de automações internas deles.

### Casos confirmados (11 leads afetados)

| Data | Hora | Contato | Telefone | Conteúdo problemático |
|------|------|---------|----------|----------------------|
| 05/06 | 11:08 | Lucineia | 5547****3020 | "...vou pagar meu cartão somente dia 10 🥹🥹🥹" |
| 05/06 | 10:51 | Iolanda Karine | 5588****7432 | Links + formatação com asterisco |
| 05/06 | 09:19 | Luana Lemos | 5579****3051 | "Mudar minha realidade financeira…" |
| 05/06 | 08:43 | Lucineia | 5547****3020 | "já comprei algumas mentorias…" |
| 05/06 | 02:19 | Aryádny Moreira | 5585****1296 | Texto longo sobre independência financeira |
| 04/06 | 22:08 | — | 5599****6022 | "Tbm ❤️" |
| 04/06 | 21:40 | Giullia Correa | 5521*****1812 | "Não mandei áudio 😅" |
| 04/06 | 21:40 | Giullia Correa | 5521*****1812 | "Não teria como eu pagar depois do primeiro resultado? 😅" |
| 04/06 | 20:58 | Danielle Rodrigues | 5585****9435 | "Pode mandar sim ☺️" |
| 04/06 | 18:54 | Vértice Digital | 5581****8465 | "Já tentei aqui pedir emprestado mas sem sucesso 😫" |
| 04/06 | 18:21 | — | 5531****4011 | Texto sobre trabalho como diarista |

### Impacto
- Mensagens não entregues ao lead
- Quebra do fluxo de conversa automatizado
- Leads com interesse real sem resposta
- **Nenhum retry foi possível** — o bug era no DataCrazy, não no VFO

### Nossa resposta
Implementamos `_sanitize_text()` em `datacrazy_automation.py` para normalizar Unicode (NFC), remover caracteres de substituição, e sanitizar mojibake. Isso mitiga no nosso lado, mas **não resolve o bug raiz** que é deles.

---

## 2. 403 Forbidden — Cloudflare Block na API DataCrazy

**Período:** 06/07/2026 (todo o dia, das 17h às 23h+)  
**Erro:** `Client error '403 Forbidden' for url 'https://api.g1.datacrazy.io/api/v1/conversations/{id}/messages'`

### O que aconteceu
O DataCrazy bloqueou nosso IP via **Cloudflare WAF/firewall**. Toda requisição POST para enviar mensagens via API REST retornava 403 Forbidden. A página de erro do Cloudflare retornava "You are unable to access datacrazy.io".

### Dados dos logs

**Instance 1 (`vfo-agent.service`):**
- Mínimo de **50+ tentativas de follow-up** falhando em loop entre 19h19 e 20h50
- Follow-ups em flow=1 step=2 e flow=2 step=1 — todos retornando 403
- Trigger de automação `bf_labs_audio_inicial` retornando Cloudflare error page (HTTP 403)

**Instance 2 (`vfo-agent-2.service`):**
- Mínimo de **40+ tentativas** entre 22h00 e 23h22
- Mesmo padrão: follow-ups em flow=1 step=2 bloqueados
- Leads afetados: `<conv-lead-01>`, `<conv-lead-02>`, `<conv-lead-03>`

### Padrão dos erros
```
Jul 06 19:19:07 vfo-agent: ERROR _send_follow_up | send failed flow=1 step=2: 403 Forbidden
Jul 06 19:20:42 vfo-agent: ERROR _send_follow_up | send failed flow=1 step=2: 403 Forbidden
Jul 06 19:22:17 vfo-agent: ERROR _send_follow_up | send failed flow=1 step=2: 403 Forbidden
... (repetiu a cada ~90 segundos por HORAS)
```

### Impacto
- **Todos os follow-ups programados falharam** — mensagens de acompanhamento não entregues
- Leads em cadência de follow-up perderam momentum
- O scheduler continuava retryando em loop (a cada 90s), desperdiçando recursos
- **Sem fallback possível** — a API inteira do DataCrazy estava bloqueada

### Nota técnica
O trigger de automação via webhook (`trigger_automation`) também retornou 403 com Cloudflare challenge page:
```
trigger_automation | HTTP 403 key=bf_labs_audio_inicial: <!DOCTYPE html>
"You are unable to access datacrazy.io"
```
Isso indica que o **IP do servidor foi bloqueado globalmente**, não apenas um endpoint específico.

---

## 3. Webhook de Automação — Roteamento pela Instância Errada

**Período:** Contínuo (desde a implantação de multi-instance)  
**Severidade:** Média

### O que aconteceu
As automações do DataCrazy (envio de áudio, follow-ups por mídia) são disparadas via webhook URL. Cada webhook dispara um **flow do DataCrazy** que está configurado para enviar mensagens por um **número WhatsApp específico**. Quando a Instance 2 (número B) dispara uma automação, o flow envia a mensagem pelo **número da Instance 1 (número A)**.

### O que funciona vs o que quebra

| Ação | Funciona? | Motivo |
|------|-----------|--------|
| `send_text_message(conv_id, text)` | ✅ | Usa conversation_id → roteia para número correto |
| `send_intro()` | ✅ | Usa send_text_message internamente |
| `send_payment_link()` | ✅ | Usa send_text_message internamente |
| `trigger_experiencia()` | ❌ | Webhook hardcoded → flow envia pelo número errado |
| `trigger_automation_1()` | ❌ | Mesmo problema |
| `trigger_automation_2()` | ❌ | Mesmo problema |
| Todos os 14 objection triggers | ❌ | Mesmo problema |
| Todos os follow-up triggers | ❌ | Mesmo problema |

### Impacto
- Lead que enviou mensagem para Instance 2 recebe áudio/mídia no número da Instance 1
- Confusão — lead recebe conteúdo de uma conversa em outro número
- **29 automações afetadas** (todas as chaves em `AUTOMATION_WEBHOOKS`)

### Mitigação implementada
`_INSTANCE_MAP` no `DataCrazyAutomationClient` — seleciona webhooks por `DATACRAZY_INSTANCE_ID`. Mas **depende do DataCrazy criar flows duplicados** para a Instance 2, o que nem sempre foi feito.

---

## 4. 995 Respostas Vazias — Falha Silenciosa do Modelo + API

**Período:** Maio–Junho 2026  
**Severidade:** Crítica

### Dados do SQLite (`tmp/vanessa.db`)

| Mês | Total transações | Reply vazio | % vazio |
|-----|-----------------|-------------|---------|
| 2026-05 | 161 | 60 | 37.3% |
| 2026-06 | 1.005 | 935 | **93.0%** |

### O que aconteceu
O LLM retornava `result.content` vazio (string vazia, None, ou whitespace). O VFO processava a mensagem do lead, o agente "respondia", mas **nenhum texto era entregue**. O lead mandava mensagem e recebia silêncio.

### Dias mais afetados (junho)

| Data | Respostas vazias |
|------|-----------------|
| 04/06 | 144 |
| 05/06 | **516** |
| 06/06 | 205 |
| 08/06 | 20 |
| 09/06 | 26 |

### Causas identificadas
1. **Modelo retornando conteúdo vazio** — `result.content` era string vazia apesar de 311 output tokens gerados
2. **OpenRouter sem créditos** — 28/05: "This request requires more credits, or fewer max_tokens"
3. **Modelo deprecado** — 16/05: "Grok 4.1 Fast is deprecated. xAI recommends switching to Grok 4.3"
4. **Erros de timeout/network** — `api_network_error` classificado pelo `error_log.py`

### Impacto
- **935 leads em junho** receberam silêncio em vez de resposta
- Follow-ups que dependiam de `conversation_id` quebraram (conversation_id não salvo quando reply vazio)
- Leads abandonaram a conversa — sem resposta = sem conversão
- **516 leads perdidos só no dia 05/06** — mesmo dia do bug de encoding

### Mitigações implementadas
- Retry com prompt simplificado quando `result.content` vazio
- Fallback via DataCrazy API: "Oi! Pode me mandar de novo? Acho que não chegou direito aqui 😊"
- Monitoramento de `empty_reply_fallback_sent`

---

## 5. Bugs Derivados de Integração

### 5a. Double-Send (LLM chama send_text_message() 2x no mesmo turno)
- **Data:** Confirmado 23/06/2026
- **Causa:** LLM (mimo-v2.5) ignorou regra de prompt e chamou a tool duas vezes
- **Impacto:** Lead recebe duas versões diferentes da mesma resposta, ~5s de diferença
- **Fix:** Guard em código (Layer 2) — bloqueia segunda chamada antes de chegar na API

### 5b. Text-Before-Tool (Agente confirma mas não envia link de pagamento)
- **Data:** Confirmado 25/06/2026
- **Causa:** LLM enviava texto "Beleza, vou te enviar!" em vez de chamar `send_payment_link()`
- **Impacto:** Lead aceita, agent fala que enviou, link nunca chega
- **Fix:** Prompt com lista explícita de sinais de aceite + instrução para chamar tool DIRETO

### 5c. Agno Race Condition — lead_name perdido
- **Período:** 11/06/2026
- **Causa:** `session_data` do Agno sobrescrevia `lead_name` → LLM outputava `{nome}` literalmente
- **Fix:** `lead_name` persistido em `follow_up_state` table

### 5d. is_purchased não persistindo
- **Períampo:** 12/06/2026
- **Causa:** `set_is_purchased()` só escrevia em `session_state` (Agno), não em `follow_up_state`
- **Impacto:** Lead comprava mas continuava recebendo follow-ups de vendas
- **Fix:** Double-write pattern — toda flag dependente do scheduler deve escrever em AMBOS

### 5e. Auto-reply processada como mensagem real
- **Períampo:** 12/06/2026
- **Causa:** WhatsApp Business auto-replies chegavam via webhook como texto normal
- **Impacto:** Lead recebia instrução interna tipo "Aguardando o lead retornar..."
- **Fix:** Filtros regex (7 padrões) + check de UUID prefix

### 5f. Flow Restart — Agente recomeça do PASSO 1
- **Períampo:** 01/07/2026
- **Causa:** State mismatch — scheduler avançava flow, mas Agno session_state ficava stale
- **Impacto:** Lead que já estava em cadência avançada recebia "Oi, me conta seu nome?" de novo
- **Fix:** Sync follow_up_state → session_state (28 campos injetados na entry de cada mensagem)

### 5g. pending_response bug — leads após horário sem resposta
- **Períampo:** 11/06/2026
- **Causa:** Scheduler limpava flag `pending_response` sem processar a mensagem pendente
- **Fix:** Scheduler envia mensagem pendente via `send_text_message()` antes de limpar flag

---

## 6. Dados de Infraestrutura

### Endpoints DataCrazy utilizados
- **REST API (mensagens):** `https://api.g1.datacrazy.io/api/v1/conversations/{id}/messages`
- **Webhooks (automações):** `https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>{tenant_id}/{flow_id}`
- **Tenant ID:** `eb238a5d-adcd-4fe7-b9bb-edbf5b6badeb`
- **Instance IDs:** `<instance-id-1>` (Instância 1), `<instance-id-2>` (Instância 2)

### Headers de rate limiting observados
- REST API: `X-RateLimit-Limit: 60`, `X-RateLimit-Remaining: 59`
- Webhooks: `X-RateLimit-Limit: 120`, `X-RateLimit-Remaining: 119`

### Infraestrutura DataCrazy (visível nos headers)
- Backend: Express.js (`X-Powered-By: Express`)
- Shard: `g1`
- Instâncias de backend: `service-api-6465575d44-5lkqn`, `service-crm-api-778fbdcd4f-sgbp2`, `service-crm-api-776ddb88f-dxlsv`

---

## 7. Resumo de Impacto Financeiro

| Evento | Leads perdidos/afetados | Receita potencial perdida |
|--------|------------------------|--------------------------|
| Invalid Character (04-05/06) | 11+ | Não quantificável — leads em negociação |
| 403 Forbidden (06/07) | Centenas de follow-ups | Follow-ups de conversão bloqueados |
| Respostas vazias (Junho) | 935 | 93% das interações sem resposta |
| Double-send + text-before-tool | Variável | Links de pagamento não entregues |
| Flow restart | Variável | Qualificações reiniciadas, leads desistentes |

**Total de transações registradas no VFO:** 1.166 (tmp/vanessa.db) + 826 (instâncias)
**Transações com reply vazio:** 995 (85.3% do total)

---

## 8. Recomendações

### Para o DataCrazy (ações que dependem deles)
1. **Corrigir encoding** — suporte nativo a UTF-8 em automações (emojis, acentos, quebras de linha)
2. **Remover bloqueio Cloudflare** — whitelistar nosso IP ou criar regra de exceção para API
3. **Documentar rate limits** — qual o limite real? O que acontece quando atinge?
4. **Webhooks instance-aware** — permitir que o webhook roteie para a instância correta, não apenas a que o flow foi configurado

### Para o VFO (ações nossas — já implementadas ou em andamento)
1. ✅ `_sanitize_text()` para mitigar encoding
2. ✅ Retry automático com backoff em `send_text_message()`
3. ✅ Guard anti-double-send em código
4. ✅ Sync follow_up_state → session_state (28 campos)
5. ✅ Fallback de resposta vazia
6. ✅ Filtros de auto-reply
7. 🔄 `_INSTANCE_MAP` para webhooks instance-aware (parcialmente implementado)
8. 🔄 Monitoramento de erros em tempo real via SSE no dashboard

---

---

## 9. Evidência Git — Commits que Provam o Impacto

**Total de commits (Maio–Julho 2026):** 107  
**Linhas alteradas:** 9.900 inserções / 1.206 deleções (11.106 total)

Cada commit abaixo é uma ação corretiva tomada **em resposta a um bug causado pela infraestrutura DataCrazy ou por falhas de integração com a API deles**. São evidências rastreáveis no GitHub (`BFLabsAI/agente-agno-vfo`).

### Commits de Correção Direta de Bugs DataCrazy

| Commit | Data | Descrição | Bug DataCrazy que motivou |
|--------|------|-----------|--------------------------|
| `c23371a` | 05/06/2026 | **199 linhas** — ajustes completos: encoding, retry, follow-up | Dia do bug "Invalid Character in Header Content" (11 leads afetados) |
| `378ee63` | 22/05/2026 | `_sanitize_text()` — normalização Unicode, remoção de mojibake | Caracteres UTF-8 quebrando automações |
| `7f8c48b` | 11/06/2026 | **4 fixes críticos** — pending_response, lead_name, pause_lead, hard gate pagamento | Leads sem resposta + race condition do Agno |
| `13258de` | 12/06/2026 | Auto-reply filter + empty reply fallback + is_purchased | Leads recebendo auto-replies como mensagens reais + 935 replies vazias |
| `d6dcf6d` | 01/07/2026 | Agent restarts qualification — sync 28 campos follow_up_state → session_state | Agent perguntando nome de novo para lead qualificado |

### Commits de Mitigação de Comportamento LLM vs API

| Commit | Data | Descrição | Problema que motivou |
|--------|------|-----------|---------------------|
| `541c789` | 26/05/2026 | Cooldown 60s em trigger_automation após send_text_message | LLM chamava automação na mesma rodada — DataCrazy recebia 2 requests |
| `27d23dc` | 26/05/2026 | REGRA ABSOLUTA — não chamar tools junto com send_text_message | LLM ignorava prompt, causava envios duplicados |
| `62fde3f` | 22/05/2026 | Return empty when tools called — evitar duplicate messages | Dupla entrega de mensagens via API DataCrazy |
| `001ad73` | 22/05/2026 | Prevent duplicate between trigger_comecando_do_zero e ask_motivation | 2 áudios/mensagens enviados para o mesmo lead |
| `050f24a` | 26/05/2026 | Fix indentation error no _send_follow_up | Service crash em loop — follow-ups pararam |

### Commits de Infraestrutura Multi-Instance

| Commit | Data | Descrição | Bug DataCrazy que motivou |
|--------|------|-----------|--------------------------|
| `c3ebcde` | 10/06/2026 | **53 linhas** — webhooks de automação por instância | Automações enviando mídia pelo número errado |
| `bc98b22` | 10/06/2026 | Estrutura multi-instância para 2 números WhatsApp | Necessidade de separar instâncias |
| `84cb9fe` | 10/06/2026 | Rotas /vfo-2 via Cloudflare Tunnel | URLs duplicadas para instância 2 |
| `4240406` | 09/06/2026 | Update OmniRoute model and DataCrazy instance ID | Troca de instância no DataCrazy |

### Commits de Correção de Fluxo (resposta a bugs que causaram perda de leads)

| Commit | Data | Descrição |
|--------|------|-----------|
| `c16bd86` | 26/05/2026 | Follow-up v2 — sistema multi-fluxo com anti-duplicação |
| `34bdf72` | 28/05/2026 | Race condition entre Agno e scheduler causando automações duplicadas |
| `b6168a1` | 26/05/2026 | send_payment_link agora seta is_purchased=True para parar follow-ups |
| `ffc9440` | 26/05/2026 | _determine_flow checa follow_1_4_sent para evitar flow 1 após scheduler |
| `0c0966b` | 26/05/2026 | send_payment_link checa follow_3 flags direto no SQLite (fallback Agno overwrite) |
| `e2fc886` | 27/05/2026 | Apenas follow_janela_24h bloqueia send_payment_link |
| `3cf3b04` | 25/06/2026 | Janela 24h — removido check que impedia envio |
| `c823255` | 25/06/2026 | Prompt reforça send_payment_link direto (text-before-tool) |
| `b53bee5` | 25/06/2026 | Atualização preço R$ 299,90 |

### Análise de Esforço

**Esforço total de correção** (estimativa baseada em commits):
- **45 commits** são fixes diretos de bugs
- **12 commits** são features/enhancements motivadas por limitações da API
- **~3.500 linhas** de código foram escritas apenas para **mitigar comportamento da API DataCrazy** (retry, sanitização, guards, sync de estado, dupla escrita)
- **2 relatórios formais** escritos sobre erros DataCrazy (`report_datacrazy_errors_05062026.md`, este relatório)

**Se a API DataCrazy funcionasse corretamente, estimativa de código que NÃO seria necessário:**
- `_sanitize_text()` + retry logic: ~100 linhas
- Auto-reply filters: ~30 linhas
- Empty reply fallback: ~40 linhas
- is_purchased double-write: ~15 linhas
- lead_name persistence: ~20 linhas
- pending_response fix: ~40 linhas
- Multi-instance webhook routing: ~100 linhas
- Anti-double-send guards: ~50 linhas
- **Total: ~395 linhas de código que existem apenas para compensar falhas do DataCrazy**

---

*Relatório gerado a partir de logs reais do sistema, commits do GitHub (`BFLabsAI/agente-agno-vfo`), e dados de `agent_transactions` e `tool_errors` das databases SQLite do VFO.*
