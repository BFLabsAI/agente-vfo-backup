# Follow-up v2 — Implementação em Fluxos (Árvore de Decisão)

## Visão Geral

Substituir o sistema atual de follow-up (fluxo único com 4 passos) por uma estrutura em **3 fluxos independentes**, onde o lead transiciona entre fluxos conforme seu progresso no funil de vendas.

### Diagrama de Fluxo

```
Lead entra no sistema
        │
        ▼
┌───────────────────────┐
│   FLUXO 1             │  Lead não respondeu + automação 1 NÃO foi enviada
│   (Pré-automação 1)   │
│                       │
│  F1.1 → 30min → Aut.1 │  (audio nível de consciência)
│  F1.2 → 1h   → texto  │  (pergunta experiência)
│  F1.3 → 2h   → Aut.   │  (follow3-pt1)
│  F1.4 → 5h   → texto  │  + Aut.1 (msg + automação 1)
│                       │
└───────────┬───────────┘
            │  Lead responde + Aut.1 já enviada
            ▼
┌───────────────────────┐
│   FLUXO 2             │  Aut.1 enviada, lead parou de responder
│   (Pós-automação 1)   │
│                       │
│  F2.1 → 20min → texto │  (mensagem Vanessa)
│  F2.2 → 2h   → Aut.   │  (meme via DataCrazy)
│  F2.3 → 4h   → Aut.   │  (lucros + quebra objeção)
│                       │
└───────────┬───────────┘
            │  Lead responde + Aut.2 já enviada
            ▼
┌───────────────────────┐
│   FLUXO 3             │  Aut.2 enviada, lead parou de responder
│   (Pós-automação 2)   │
│                       │
│  F3.1 → 20min → Aut.  │  (vídeo motivacional)
│  F3.2 → 2h   → Aut.  │  (prova social + resultados)
│  F3.3 → 3h   → Aut.  │  (sorteio + oferta R$299,90)
│                       │
└───────────────────────┘
```

### Regras de Transição

1. **Lead começa no Fluxo 1** — quando `last_lead_message_at` é definido (primeira interação ou resposta)
2. **Reset ao responder** — quando o lead responde, o scheduler recalcula o fluxo correto:
   - Se `automation_1_sent == False` → **Fluxo 1** (reset, começa do zero)
   - Se `automation_1_sent == True` e `automation_2_sent == False` → **Fluxo 2**
   - Se `automation_2_sent == True` → **Fluxo 3**
3. **Conclusão** — quando todos os follows de um fluxo foram enviados, `follow_up_expired = True`
4. **Janela de 24h** — se passar 24h sem resposta, para de enviar (mesmo comportamento atual)
5. **Anti-duplicação** — automações que já estão no fluxo normal (Aut.1 no F1.1 e F1.4) não devem ser re-disparadas se já foram enviadas pelo agente principal

---

## Arquivos a Serem Alterados

### 1. `app/agent_factory.py` — Novos Campos de Estado

Adicionar ao dicionário `state`:

```python
# Follow-up tracking (v2 - multi-flow)
"last_lead_message_at": "",
"follow_up_flow": 0,            # 0=nenhum, 1=pré-automação1, 2=pós-automação1, 3=pós-automação2
"follow_up_flow_count": 0,      # quantos follows já enviou no fluxo atual
"follow_up_flow_started_at": "", # quando o fluxo atual começou
"follow_up_expired": False,      # True quando todos os follows do fluxo foram enviados

# Flags por follow-up enviado (anti-duplicação)
# Fluxo 1
"follow_1_1_sent": False,       # F1.1: audio nível de consciência (30min)
"follow_1_2_sent": False,       # F1.2: pergunta experiência (1h)
"follow_1_3_sent": False,       # F1.3: follow3-pt1 (2h)
"follow_1_4_sent": False,       # F1.4: texto + Aut.1 (5h)
# Fluxo 2
"follow_2_1_sent": False,       # F2.1: meme Vanessa (20min)
"follow_2_2_sent": False,       # F2.2: meme DataCrazy (2h)
"follow_2_3_sent": False,       # F2.3: lucros + quebra objeção (4h)
# Fluxo 3
"follow_3_1_sent": False,       # F3.1: vídeo motivacional (20min)
"follow_3_2_sent": False,       # F3.2: prova social + resultados (2h)
"follow_3_3_sent": False,       # F3.3: sorteio + oferta R$299,90 (3h)
```

**Campos a remover** (descontinuados):
- `follow_up_count` → substituído por `follow_up_flow_count`
- `follow_up_started_at` → substituído por `follow_up_flow_started_at`

**Adicionar também** (não existem no state inicial, são setados pelos tools):
```python
"automation_1_sent": False,
"automation_2_sent": False,
```

### 2. `app/context.py` — Propriedades Atualizadas

Substituir as propriedades de follow-up (linhas 297-328) por:

```python
# --- Follow-up tracking (v2) ---
@property
def last_lead_message_at(self) -> str:
    return self._s.get("last_lead_message_at", "")

def set_last_lead_message_at(self, v: str) -> None:
    self._s["last_lead_message_at"] = v

@property
def follow_up_flow(self) -> int:
    return self._s.get("follow_up_flow", 0)

def set_follow_up_flow(self, v: int) -> None:
    self._s["follow_up_flow"] = v

@property
def follow_up_flow_count(self) -> int:
    return self._s.get("follow_up_flow_count", 0)

def set_follow_up_flow_count(self, v: int) -> None:
    self._s["follow_up_flow_count"] = v

def increment_follow_up_flow_count(self) -> None:
    self._s["follow_up_flow_count"] = self._s.get("follow_up_flow_count", 0) + 1

@property
def follow_up_flow_started_at(self) -> str:
    return self._s.get("follow_up_flow_started_at", "")

def set_follow_up_flow_started_at(self, v: str) -> None:
    self._s["follow_up_flow_started_at"] = v

@property
def follow_up_expired(self) -> bool:
    return self._s.get("follow_up_expired", False)

def set_follow_up_expired(self, v: bool) -> None:
    self._s["follow_up_expired"] = v

# --- Flags por follow-up enviado (anti-duplicação) ---
# Fluxo 1
@property
def follow_1_1_sent(self) -> bool:
    return self._s.get("follow_1_1_sent", False)

def set_follow_1_1_sent(self, v: bool) -> None:
    self._s["follow_1_1_sent"] = v

@property
def follow_1_2_sent(self) -> bool:
    return self._s.get("follow_1_2_sent", False)

def set_follow_1_2_sent(self, v: bool) -> None:
    self._s["follow_1_2_sent"] = v

@property
def follow_1_3_sent(self) -> bool:
    return self._s.get("follow_1_3_sent", False)

def set_follow_1_3_sent(self, v: bool) -> None:
    self._s["follow_1_3_sent"] = v

@property
def follow_1_4_sent(self) -> bool:
    return self._s.get("follow_1_4_sent", False)

def set_follow_1_4_sent(self, v: bool) -> None:
    self._s["follow_1_4_sent"] = v

# Fluxo 2
@property
def follow_2_1_sent(self) -> bool:
    return self._s.get("follow_2_1_sent", False)

def set_follow_2_1_sent(self, v: bool) -> None:
    self._s["follow_2_1_sent"] = v

@property
def follow_2_2_sent(self) -> bool:
    return self._s.get("follow_2_2_sent", False)

def set_follow_2_2_sent(self, v: bool) -> None:
    self._s["follow_2_2_sent"] = v

@property
def follow_2_3_sent(self) -> bool:
    return self._s.get("follow_2_3_sent", False)

def set_follow_2_3_sent(self, v: bool) -> None:
    self._s["follow_2_3_sent"] = v

# Fluxo 3
@property
def follow_3_1_sent(self) -> bool:
    return self._s.get("follow_3_1_sent", False)

def set_follow_3_1_sent(self, v: bool) -> None:
    self._s["follow_3_1_sent"] = v

@property
def follow_3_2_sent(self) -> bool:
    return self._s.get("follow_3_2_sent", False)

def set_follow_3_2_sent(self, v: bool) -> None:
    self._s["follow_3_2_sent"] = v

@property
def follow_3_3_sent(self) -> bool:
    return self._s.get("follow_3_3_sent", False)

def set_follow_3_3_sent(self, v: bool) -> None:
    self._s["follow_3_3_sent"] = v
```

### 3. `data/follow_up_templates.json` — 3 Conjuntos de Templates

Substituir o arquivo atual por uma estrutura com chaves por fluxo:

```json
{
  "flow_1": [
    {
      "step": 1,
      "delay_seconds": 1800,
      "message": "",
      "automation": "bf_labs_audio_inicial",
      "note": "Só envia se automation_1_sent == False"
    },
    {
      "step": 2,
      "delay_seconds": 3600,
      "message": "Fiquei na dúvida se você tá começando do zero ou já tem uma noção...me conta rapidinho pra eu te explicar certinho.",
      "automation": null
    },
    {
      "step": 3,
      "delay_seconds": 7200,
      "message": "",
      "automation": "bf_labs_follow3_pt1"
    },
    {
      "step": 4,
      "delay_seconds": 18000,
      "message": "Como estou livre agora, Vou te explicando aqui, e quando você conseguir ver com calma, você me responde ta bem!",
      "automation": "bf_labs_automacao1",
      "note": "Só envia automação se automation_1_sent == False"
    }
  ],
  "flow_2": [
    {
      "step": 1,
      "delay_seconds": 1200,
      "message": "Oieee, Tô quase mandando mensagem pra mim mesma de tanto que fiquei falando sozinha aqui kkkkk",
      "automation": null
    },
    {
      "step": 2,
      "delay_seconds": 7200,
      "message": "",
      "automation": "bf_labs_follow2_pt2"
    },
    {
      "step": 3,
      "delay_seconds": 14400,
      "message": "",
      "automation": "bf_labs_follow3_pt2"
    }
  ],
  "flow_3": [
    {
      "step": 1,
      "delay_seconds": 1200,
      "message": "",
      "automation": "bf_labs_follow1_pt3"
    },
    {
      "step": 2,
      "delay_seconds": 7200,
      "message": "",
      "automation": "bf_labs_follow2_pt3"
    },
    {
      "step": 3,
      "delay_seconds": 10800,
      "message": "",
      "automation": "bf_labs_follow3_pt3",
      "handle_response": true,
      "response_price": 299.90,
      "note": "Se lead responder com interesse após este follow, enviar link de pagamento R$299,90"
    }
  ]
}
```

**Observações sobre os templates:**
- `delay_seconds` em produção. Valores de teste serão definidos como constantes no scheduler (igual ao sistema atual)
- Steps com `message: ""` só disparam automação (sem texto do agente)
- Steps com `automation: null` só enviam texto
- Steps com ambos enviam texto e depois disparam automação
- `handle_response: true` indica que o agente deve processar a resposta do lead após este follow

### 4. `app/datacrazy_automation.py` — Novos Webhooks

Adicionar ao dicionário `AUTOMATION_WEBHOOKS`:

```python
# Novos webhooks de follow-up (v2)
"bf_labs_audio_inicial": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_follow3_pt1": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_automacao1": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_follow2_pt2": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_follow3_pt2": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_follow1_pt3": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_follow2_pt3": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
"bf_labs_follow3_pt3": "https://api.datacrazy.io/v1/crm/api/crm/<webhook-de-fluxo>",
```

**Nota:** `bf_labs_audio_inicial` e `bf_labs_automacao1` apontam para os mesmos webhooks que `pergunta_experiencia` e `automacao_1` respectivamente (são as mesmas automações do fluxo normal, reutilizadas nos follows).

### 5. `app/follow_up_scheduler.py` — Reescrita do Scheduler

#### 5.1 Constantes de Intervalo

```python
# Polling interval
_POLL_INTERVAL = 5

# --- Intervalos de PRODUÇÃO (seconds) ---
_INTERVALS = {
    1: {1: 1800, 2: 3600, 3: 7200, 4: 18000},    # 30min, 1h, 2h, 5h
    2: {1: 1200, 2: 7200, 3: 14400},               # 20min, 2h, 4h
    3: {1: 1200, 2: 7200, 3: 10800},               # 20min, 2h, 3h
}

# --- Intervalos de TESTE (seconds) ---
_INTERVALS_TEST = {
    1: {1: 90, 2: 120, 3: 180, 4: 240},
    2: {1: 60, 2: 90, 3: 120},
    3: {1: 60, 2: 90, 3: 120},
}
```

#### 5.2 Função `_determine_flow(state)` — Lógica de Determinação do Fluxo

```python
def _determine_flow(state: dict) -> int:
    """
    Determina qual fluxo de follow-up o lead deve estar.
    Retorna 1, 2, ou 3.
    """
    if state.get("automation_2_sent"):
        return 3
    if state.get("automation_1_sent"):
        return 2
    return 1
```

#### 5.3 Função `_get_follow_flag_key(flow, step)` — Mapeamento Flag por Follow

```python
def _get_follow_flag_key(flow: int, step: int) -> str:
    """Retorna a chave da flag de envio para um follow específico."""
    return f"follow_{flow}_{step}_sent"
```

#### 5.4 Função `_is_eligible(state)` — Nova Lógica de Elegibilidade com Flags

```python
def _is_eligible(state: dict) -> tuple[int, dict] | None:
    """
    Verifica se o lead é elegível para receber um follow-up.
    Retorna (flow_number, template) se elegível, None caso contrário.
    """
    # Pular se comprou
    if state.get("is_purchased"):
        return None

    # Pular se follow-up expirou
    if state.get("follow_up_expired"):
        return None

    # Deve ter timestamp de última mensagem
    last_msg = state.get("last_lead_message_at", "")
    if not last_msg:
        return None

    # Parse do timestamp
    try:
        last_dt = datetime.fromisoformat(last_msg)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

    now = datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()

    # Janela de 24h
    if elapsed > 86400:
        return None

    # Determinar fluxo atual
    flow = _determine_flow(state)

    # Carregar templates do fluxo
    templates = _load_templates()
    flow_key = f"flow_{flow}"
    flow_templates = templates.get(flow_key, [])

    if not flow_templates:
        return None

    # Contagem atual no fluxo
    count = state.get("follow_up_flow_count", 0)
    current_flow = state.get("follow_up_flow", 0)

    # Se mudou de fluxo, resetar contagem
    if current_flow != flow:
        # Encontrar o primeiro follow NÃO enviado do novo fluxo
        for tpl in flow_templates:
            flag_key = _get_follow_flag_key(flow, tpl["step"])
            if not state.get(flag_key, False):
                return (flow, tpl)
        # Todos já enviados neste fluxo
        return None

    # Já enviou todos do fluxo?
    if count >= len(flow_templates):
        return None

    # Verificar tempo para o próximo follow
    next_template = flow_templates[count]

    # Verificar flag de anti-duplicação: se já foi enviado, pular para o próximo
    flag_key = _get_follow_flag_key(flow, next_template["step"])
    if state.get(flag_key, False):
        # Já enviado — buscar o próximo não enviado
        for tpl in flow_templates[count + 1:]:
            next_flag = _get_follow_flag_key(flow, tpl["step"])
            if not state.get(next_flag, False):
                next_template = tpl
                break
        else:
            # Todos os próximos já foram enviados
            return None

    flow_started = state.get("follow_up_flow_started_at", "")

    if flow_started:
        try:
            started_dt = datetime.fromisoformat(flow_started)
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
            time_in_flow = (now - started_dt).total_seconds()
        except (ValueError, TypeError):
            time_in_flow = elapsed
    else:
        time_in_flow = elapsed

    required_delay = _INTERVALS.get(flow, {}).get(
        next_template["step"],
        next_template.get("delay_seconds", 60)
    )

    if time_in_flow >= required_delay:
        # Verificar anti-duplicação para automações do fluxo normal
        if flow == 1:
            if next_template["step"] == 1 and state.get("automation_1_sent"):
                # Aut.1 já foi enviada pelo agente, pular para o próximo
                for tpl in flow_templates[1:]:
                    if not state.get(_get_follow_flag_key(1, tpl["step"]), False):
                        return (flow, tpl)
                return None
            if next_template["step"] == 4 and state.get("automation_1_sent"):
                # Aut.1 já enviada, só enviar texto
                next_template = {**next_template, "automation": None}

        return (flow, next_template)

    return None
```

#### 5.5 Função `_reset_follow_up(session_id)` — Reset com Recálculo de Fluxo

**IMPORTANTE:** Ao transicionar de fluxo, as flags do fluxo anterior NÃO são resetadas (para não re-disparar follows já enviados). Apenas `follow_up_flow_count` e `follow_up_flow_started_at` são resetados.

```python
async def _reset_follow_up(session_id: str) -> None:
    """Reset follow-up state when lead responds. Recalcula o fluxo."""
    try:
        conn = sqlite3.connect(SESSION_DB_PATH)
        row = conn.execute(
            "SELECT session_data FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row:
            data = json.loads(row[0])
            while isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                state = data.get("session_state", {})
                if isinstance(state, dict):
                    # Recalcular fluxo baseado no estado atual
                    new_flow = _determine_flow(state)
                    old_flow = state.get("follow_up_flow", 0)

                    state["follow_up_flow"] = new_flow
                    state["follow_up_flow_count"] = 0
                    state["follow_up_flow_started_at"] = ""
                    state["follow_up_expired"] = False
                    state["last_lead_message_at"] = datetime.now(timezone.utc).isoformat()

                    # Flags NÃO são resetadas — preservam o histórico de envios
                    # O _is_eligible() já verifica as flags antes de sugerir um follow

                    data["session_state"] = state
                    conn.execute(
                        "UPDATE agno_sessions SET session_data = ? WHERE session_id = ?",
                        (json.dumps(data), session_id),
                    )
                    conn.commit()
                    logger.info(
                        "_reset_follow_up | session=%s flow: %d -> %d",
                        session_id, old_flow, new_flow,
                    )

        conn.close()
    except Exception as exc:
        logger.error("_reset_follow_up | error: %s", exc)
```

#### 5.6 Função `_send_follow_up()` — Atualizada com Flags

Após enviar com sucesso, seta a flag `follow_{flow}_{step}_sent = True`:

```python
async def _send_follow_up(
    session_id: str,
    state: dict,
    flow: int,
    template: dict[str, Any],
    automation_client: DataCrazyAutomationClient,
) -> bool:
    """Send a follow-up message for the given flow."""
    phone = _extract_phone(session_id)
    conversation_id = state.get("conversation_id", "")
    external_id = state.get("external_id", "")
    from_number = state.get("from_number", phone)

    if not conversation_id:
        logger.warning("_send_follow_up | no conversation_id for session=%s", session_id)
        return False

    # Enviar texto (se houver)
    message_text = template.get("message", "")
    if message_text:
        message = _format_message(message_text, state)
        logger.info("_send_follow_up | session=%s flow=%d step=%d msg=%r",
                     session_id, flow, template["step"], message[:80])
        result = await automation_client.send_text_message(conversation_id, message)
        if result.get("status") != "success":
            logger.error("_send_follow_up | send failed flow=%d step=%d: %s", flow, template["step"], result)
            return False

    # Disparar automação (se houver)
    automation_key = template.get("automation")
    if automation_key:
        logger.info("_send_follow_up | triggering automation=%s", automation_key)
        await automation_client.trigger_automation(
            automation_key,
            conversation_id=conversation_id,
            contact_id=from_number,
            external_id=external_id,
        )

    # Atualizar estado no SQLite
    step = template["step"]
    flag_key = _get_follow_flag_key(flow, step)
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        conn = sqlite3.connect(SESSION_DB_PATH)
        row = conn.execute(
            "SELECT session_data FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row:
            data = json.loads(row[0])
            while isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                state = data.get("session_state", {})
                if isinstance(state, dict):
                    # Setar flag de envio
                    state[flag_key] = True

                    # Atualizar contagem (encontrar o step correto na ordem)
                    state["follow_up_flow"] = flow
                    state["follow_up_flow_count"] = step
                    if not state.get("follow_up_flow_started_at"):
                        state["follow_up_flow_started_at"] = now_iso

                    # Carregar templates para saber quantos o fluxo tem
                    templates = _load_templates()
                    flow_templates = templates.get(f"flow_{flow}", [])
                    if step >= len(flow_templates):
                        state["follow_up_expired"] = True

                    data["session_state"] = state
                    conn.execute(
                        "UPDATE agno_sessions SET session_data = ? WHERE session_id = ?",
                        (json.dumps(data), session_id),
                    )
                    conn.commit()
                    logger.info(
                        "_send_follow_up | state updated: flow=%d step=%d flag=%s expired=%s",
                        flow, step, flag_key, state["follow_up_expired"],
                    )

        conn.close()
    except Exception as exc:
        logger.error("_send_follow_up | db update error: %s", exc)

    return True
```

#### 5.7 Loop Principal — Atualizado

```python
async def follow_up_scheduler_loop() -> None:
    """Main loop — runs as background task."""
    logger.info("follow_up_scheduler | starting (poll_interval=%ds)", _POLL_INTERVAL)
    automation = DataCrazyAutomationClient()

    while True:
        try:
            sessions = _get_active_sessions()
            logger.info("follow_up_scheduler | checking %d sessions", len(sessions))

            for session in sessions:
                session_id = session["session_id"]
                state = session["state"]

                result = _is_eligible(state)
                if result:
                    flow, template = result
                    logger.info("follow_up_scheduler | eligible: session=%s flow=%d step=%d",
                               session_id, flow, template["step"])
                    await _send_follow_up(session_id, state, flow, template, automation)

        except Exception as exc:
            logger.error("follow_up_scheduler | loop error: %s", exc, exc_info=True)

        await asyncio.sleep(_POLL_INTERVAL)
```

### 6. `app/whatsapp_api.py` — Garantir Reset no Momento Correto

O `_reset_follow_up(session_id)` já é chamado na linha 413 após o agente processar a mensagem. Nenhuma alteração necessária neste arquivo, pois a nova função `_reset_follow_up` já recalcula o fluxo automaticamente.

### 7. `tools/vanessa.py` — Link de Pagamento do Sorteio (Fluxo 3, Follow 3)

Adicionar lógica no agente para quando o lead responder com interesse após o follow 3 do fluxo 3 (sorteio/oferta R$299,90), enviar o link de pagamento correspondente.

No system prompt (`prompts/vanessa.py`), adicionar instrução:

```
Se o lead responder com interesse após receber a mensagem do sorteio/oferta de R$299,90,
envie o link de pagamento usando send_payment_link(tier=2) que corresponde ao valor R$299,90.
```

### 8. `tools/vanessa.py` — Atualizar `get_lead_info()` com Status dos Follow-ups

Atualizar a tool `get_lead_info()` (tools/vanessa.py:716) para incluir o status completo dos follow-ups:

```python
# Dentro de get_lead_info(), adicionar ao dicionário de retorno:
"follow_up_status": {
    "current_flow": ctx.follow_up_flow,
    "flow_count": ctx.follow_up_flow_count,
    "expired": ctx.follow_up_expired,
    "flow_1": {
        "follow_1_1": ctx.follow_1_1_sent,
        "follow_1_2": ctx.follow_1_2_sent,
        "follow_1_3": ctx.follow_1_3_sent,
        "follow_1_4": ctx.follow_1_4_sent,
    },
    "flow_2": {
        "follow_2_1": ctx.follow_2_1_sent,
        "follow_2_2": ctx.follow_2_2_sent,
        "follow_2_3": ctx.follow_2_3_sent,
    },
    "flow_3": {
        "follow_3_1": ctx.follow_3_1_sent,
        "follow_3_2": ctx.follow_3_2_sent,
        "follow_3_3": ctx.follow_3_3_sent,
    },
},
```

Isso permite que o agente consulte exatamente quais follow-ups já foram enviados para evitar duplicação.

### 9. Mecanismo de Anti-Duplicação — Resumo

O sistema de anti-duplicação opera em **3 camadas**:

| Camada | Onde | Como |
|--------|------|------|
| **1. Flags por follow** | `session_state` | `follow_{flow}_{step}_sent = True` após envio. Scheduler verifica antes de sugerir |
| **2. Flags de automação** | `session_state` | `automation_1_sent`, `automation_2_sent` — evita re-disparar automações do fluxo normal |
| **3. Persistência SQLite** | `agno_sessions` | Estado sobrevive a restart do servidor. Flags nunca são perdidas |

**Fluxo de verificação no scheduler:**
```
1. _is_eligible() é chamado
2. Verifica se o follow já foi enviado (flag follow_{flow}_{step}_sent)
3. Se já enviado, pula para o próximo follow não enviado
4. Se Aut.1 já enviada (automation_1_sent), pula F1.1 e remove automação do F1.4
5. Só então verifica o tempo de delay
6. Após enviar, seta a flag = True no SQLite
```

**Reset inteligente:**
- Quando o lead responde, `_reset_follow_up()` recalcula o fluxo
- Flags do fluxo anterior NÃO são resetadas (histórico preservado)
- Apenas `follow_up_flow_count` e `follow_up_flow_started_at` são resetados
- `_is_eligible()` encontra o primeiro follow não enviado do novo fluxo

---

## Tabela de Webhooks — Mapeamento Completo

| Fluxo | Follow | Key no Template | Webhook DataCrazy | Automação |
|-------|--------|-----------------|-------------------|-----------|
| 1 | 1 | `bf_labs_audio_inicial` | `.../ce7549d0-...` | Audio nível de consciência |
| 1 | 2 | `null` | — | Só texto |
| 1 | 3 | `bf_labs_follow3_pt1` | `.../569d1b7c-...` | Follow3 parte 1 |
| 1 | 4 | `bf_labs_automacao1` | `.../6f66525d-...` | Automação 1 (reutilizada) |
| 2 | 1 | `null` | — | Só texto (meme) |
| 2 | 2 | `bf_labs_follow2_pt2` | `.../eab2d163-...` | Meme via DataCrazy |
| 2 | 3 | `bf_labs_follow3_pt2` | `.../5cbfb53a-...` | Lucros + quebra objeção |
| 3 | 1 | `bf_labs_follow1_pt3` | `.../e6f590b6-...` | Vídeo motivacional |
| 3 | 2 | `bf_labs_follow2_pt3` | `.../9c37cdb2-...` | Prova social + resultados |
| 3 | 3 | `bf_labs_follow3_pt3` | `.../f9156f19-...` | Sorteio + oferta R$299,90 |

---

## Ordem de Implementação

### Fase 1 — Preparação (sem quebrar nada)
1. Adicionar `automation_1_sent`, `automation_2_sent` e todas as 10 flags de follow-up ao state inicial em `agent_factory.py`
2. Adicionar novos webhooks em `datacrazy_automation.py`
3. Criar o novo `data/follow_up_templates.json` (v2) — **não substituir o atual ainda**

### Fase 2 — Refatorar o Scheduler
4. Atualizar `app/context.py` com novas propriedades de follow-up + flags por follow
5. Reescrever `app/follow_up_scheduler.py` com a lógica multi-fluxo + verificação de flags
6. Atualizar `app/agent_factory.py` com novos campos de estado

### Fase 3 — Tools e Integração
7. Atualizar `get_lead_info()` em `tools/vanessa.py` para mostrar status dos follow-ups
8. Trocar `data/follow_up_templates.json` pelo v2

### Fase 4 — Testes
9. Testar com intervalos curtos (modo teste) cada fluxo isoladamente
10. Testar transição Fluxo 1 → Fluxo 2 (lead responde após Aut.1)
11. Testar transição Fluxo 2 → Fluxo 3 (lead responde após Aut.2)
12. Testar anti-duplicação: flags preservadas após reset
13. Testar anti-duplicação: Aut.1 já enviada pelo agente não re-dispara no F1.1/F1.4
14. Testar resposta de interesse no sorteio (Fluxo 3, Follow 3) → link R$299,90
15. Testar restart do servidor: flags persistem no SQLite

### Fase 5 — Produção
16. Ativar intervalos de produção
17. Monitorar logs do scheduler por 24h
18. Verificar métricas de conversão por fluxo

---

## Riscos e Mitigações

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| Aut.1 duplicada (follow + agente) | Lead recebe conteúdo repetido | Anti-duplicação: verificar `automation_1_sent` antes de disparar |
| Lead responde rápido, fluxo errado | Follow enviado no momento errado | `_reset_follow_up` recalcula fluxo a cada resposta |
| Janela de 24h muito curta para Fluxo 3 | Lead perde follow-ups do sorteio | Considerar extender para 48h no Fluxo 3 (ou remover janela) |
| Webhook DataCrazy falha | Follow não entregue | Log de erro + retry no próximo poll (5s) |
| Migração de estado (sessões existentes) | Sessões antigas sem novos campos | `_determine_flow()` usa `.get()` com defaults — backward compatible |

---

## Observações Importantes

1. **`bf_labs_audio_inicial`** aponta para o mesmo webhook de `pergunta_experiencia` — é a mesma automação, só mapeada com nome diferente para clareza nos templates
2. **`bf_labs_automacao1`** aponta para o mesmo webhook de `automacao_1` — reutilizada no Fluxo 1 Follow 4
3. **O campo `follow_up_flow_started_at`** deve ser setado quando o primeiro follow do fluxo é enviado (não quando o fluxo é determinado), para que o delay do primeiro follow seja relativo ao momento em que começou a enviar
4. **Sessões existentes** que já têm `follow_up_count > 0` no sistema antigo precisarão de migração: ao carregar, se tiver `follow_up_count` mas não `follow_up_flow`, tratar como Fluxo 1 com `follow_up_flow_count = follow_up_count`
