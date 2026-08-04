# Implementação Follow-Up — Vanessa Agent (1d4x)

## Contexto Atual

O agente Vanessa é **puramente reativo** — só processa mensagens quando chegam via webhook do DataCrazy. Não existe mecanismo de rastreamento de última interação, agendamento de mensagens proativas ou follow-up automático após silêncio.

---

## Restrição da API Oficial

WhatsApp Business API permite enviar mensagens **apenas dentro de 24h** após a última mensagem recebida do lead. Após esse período, só via template (custo adicional + aprovação Meta).

**Estratégia 1d4x**: 4 mensagens ao longo de 24h, espaçadas para não ser spam.

---

## Arquitetura Proposta

### 1. Tracking de Última Interação

**Campos no session_state** (adicionar em `agent_factory.py` → state dict):
```python
"last_lead_message_at": None,  # ISO 8601 UTC — timestamp da última msg RECEBIDA do lead
"follow_up_count": 0,          # Follow-ups enviados nesta sessão
"follow_up_started_at": None,  # ISO 8601 UTC — início do ciclo de follow-up
```

**Propriedades em `context.py`:**
```python
@property
def last_lead_message_at(self) -> str:
    return self._s.get("last_lead_message_at", "")

def set_last_lead_message_at(self, v: str) -> None:
    self._s["last_lead_message_at"] = v

@property
def follow_up_count(self) -> int:
    return self._s.get("follow_up_count", 0)

def set_follow_up_count(self, v: int) -> None:
    self._s["follow_up_count"] = v

def increment_follow_up_count(self) -> None:
    self._s["follow_up_count"] = self._s.get("follow_up_count", 0) + 1

@property
def follow_up_started_at(self) -> str:
    return self._s.get("follow_up_started_at", "")

def set_follow_up_started_at(self, v: str) -> None:
    self._s["follow_up_started_at"] = v
```

**Onde atualizar:** Em `whatsapp_api.py` → `_handle_datacrazy_message()`, após receber mensagem do lead:
```python
from datetime import datetime, timezone
agent.session_state["last_lead_message_at"] = datetime.now(timezone.utc).isoformat()
```

---

### 2. Background Scheduler

**Novo arquivo: `app/follow_up_scheduler.py`**

Responsabilidades:
- Rodar como `asyncio.Task` no startup do FastAPI
- A cada **5 minutos**, consulta sessões ativas no SQLite
- Verifica elegibilidade e envia follow-ups
- Atualiza `follow_up_count` e `follow_up_started_at`

**Intervalos (MODO TESTE):**

| Follow-up | Tempo após última msg | Descrição |
|-----------|----------------------|-----------|
| 1 | 10s | Primeiro reengajamento |
| 2 | 20s | Segundo toque |
| 3 | 30s | Terceiro toque |
| 4 | 40s | Último toque |

**Intervalos (PRODUÇÃO — após testes):**

| Follow-up | Tempo após última msg | Descrição |
|-----------|----------------------|-----------|
| 1 | 15min | Primeiro reengajamento |
| 2 | 45min | Segundo toque |
| 3 | 2h | Terceiro toque |
| 4 | 4h | Último toque |

---

### 3. Templates de Follow-up

| # | Copy | Automação |
|---|------|-----------|
| 1 | "Oi, {nome} 💛 é a Vanessa aqui. Passei aqui só pra te responder com calma e ver se você conseguiu olhar minha mensagem. Ficou alguma duvida?" | — |
| 2 | "Oiii voltei porque sei que muita gente chega aqui com medo de dar errado de novo, e eu entendo de verdade. Então preferi mostrar uma de nossas alunas que é nossos cases de sucesso, e to ansiosa para em breve ser você." | follow_up_video_prova_social |
| 3 | "{nome}. Até aqui eu quis te deixar bem à vontade, mas preciso ser sincera com você: ganhar dinheiro com a internet e mudar sua vida com nosso treinamento ainda faz sentido para você?" | — |
| 4 | "Vou te enviar a história de uma mãe que começou cheia de medo, igual muita gente que fala comigo, e hoje vive só do digital. Eu vou finalizar por aqui pra não ficar insistindo com você, mas queria saber: você vai continuar esperando ou vai dar o passo para mudar de vida?" | follow_up_foto_historia |

**Webhooks de automação:**
- follow_up_video_prova_social: `https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>`
- follow_up_foto_historia: `https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>`

**Templates em:** `data/follow_up_templates.json`

---

### 4. Regras de Negócio (Anti-Spam)

1. Máximo **4 follow-ups** por ciclo de 24h
2. Intervalo mínimo de **2.5h** entre mensagens
3. Se lead responder → **reseta ciclo** (zera `follow_up_count`, atualiza `last_lead_message_at`)
4. Se `is_purchased=True` → **não envia**
5. Se lead não qualificado / sem nome → **não envia** follow-up avançado
6. Se janela de 24h expirou → **não envia** (respeitar API oficial)

---

### 5. Integração com Fluxo Existente

- Lead responde durante ciclo → webhook processa normalmente, atualiza timestamp, reseta contador
- Após 4 follow-ups sem resposta → sessão entra em estado "dormant" (`follow_up_expired = True`)
- Futuro: templates aprovados pelo Meta para reengajamento fora da janela

---

## Arquivos a Serem Criados/Modificados

### Novos:
| Arquivo | Descrição |
|---------|-----------|
| `app/follow_up_scheduler.py` | Background task que verifica e envia follow-ups |
| `data/follow_up_templates.json` | Templates de mensagem por fase do funil |

### Modificados:
| Arquivo | Mudança |
|---------|---------|
| `app/context.py` | Propriedades `last_lead_message_at`, `follow_up_count`, `follow_up_started_at` |
| `app/agent_factory.py` | Campos no `state` dict |
| `app/whatsapp_api.py` | Atualizar timestamp no handler + iniciar scheduler no startup |
| `tools/vanessa.py` | (Opcional) Tool `get_follow_up_status()` para debug |
| `prompts/vanessa.py` | Instrução sobre follow-ups automáticos |

---

## Fluxo de Execução

```
┌─────────────────────────────────────────────────────────┐
│ FLUXO PRINCIPAL                                         │
├─────────────────────────────────────────────────────────┤
│ Lead envia msg → Webhook → MessageBuffer (20s debounce) │
│      ↓                                                  │
│ _handle_datacrazy_message()                             │
│   • Atualiza last_lead_message_at                       │
│   • Reseta follow_up_count = 0                          │
│      ↓                                                  │
│ Agent processa → Resposta enviada                       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ BACKGROUND (a cada 5 min)                               │
├─────────────────────────────────────────────────────────┤
│ follow_up_scheduler.run()                               │
│      ↓                                                  │
│ Consulta sessões no SQLite                              │
│      ↓                                                  │
│ Para cada sessão:                                       │
│   • Verifica regras de negócio (seção 4)                │
│   • Se elegível → envia via DataCrazy API               │
│   • Atualiza follow_up_count                            │
└─────────────────────────────────────────────────────────┘
```

---

## Testes

1. **Unitário**: Lógica de intervalos e seleção de template
2. **Integração**: Simular sessão e verificar timing do scheduler
3. **Manual**: Enviar msg de teste, aguardar 3h, verificar envio
4. **Edge cases**: Lead responde durante ciclo (reset); 24h expiram (parar envio)

---

## Próximos Passos (Fora do Escopo 1d4x)

- Templates aprovados pelo Meta para reengajamento após 24h
- Horário comercial (não enviar entre 22h-8h)
- Score de engajamento para priorizar leads
- A/B testing de mensagens
- Dashboard com status de follow-up no admin
