# Plano de Melhorias — Agente Vanessa (v11)

> Documento criado em: 2026-05-11
> Status: Aguardando validação

---

## 1. Controle de Automação Enviada — Evitar Pular Etapas

### Problema Identificado
O agente **não rastre se a automação 1 foi realmente enviada** antes de avançar no fluxo. Houve um caso real onde:
- O agente fez as perguntas iniciais
- Na terceira interação, o lead perguntou 3 coisas de uma vez: "quanto é a mentoria", "consegue me ajudar", etc.
- O agente **pulou direto para perguntar se a pessoa viu ou tem dúvida sobre o curso**, sem nunca ter enviado a automação 1

Isso quebra o fluxo comercial porque o lead nunca viu o conteúdo de apresentação.

### Proposta de Mudança

#### 1.1 — Flag `automation_1_sent` no SessionContext
- Adicionar campo booleano `automation_1_sent` (inicia `False`, muda para `True` quando `trigger_automation_1()` é chamada com sucesso)
- **Regra no prompt:** "NUNCA pergunte se o lead viu o conteúdo ou tem dúvidas sobre a apresentação SEMPRE que `automation_1_sent` for `False`"

#### 1.2 — Regra de Bloqueio de Preço por Automação
- **Regra absoluta:** Preço só pode ser mencionado APÓS `automation_1_sent == True`
- Se o lead perguntar preço antes → Vanessa responde que precisa explicar como funciona primeiro → pergunta se pode enviar áudios/vídeos → só após o "sim" aciona automação 1

#### 1.3 — Tratamento de Mensagens Multi-pergunta do Lead
- Quando o lead fizer múltiplas perguntas de uma vez, o agente deve:
  1. **Responder a pergunta mais simples/direta primeiro** (ex: "consegue me ajudar?" → "Claro que consigo!")
  2. **Validar o interesse** ("Que bom que você tem interesse!")
  3. **Seguir o fluxo normal** — se automação 1 ainda não foi enviada, NÃO pular para tratamento de dúvidas de conteúdo. Em vez disso, conduzir para qualificação → automação 1 → SÓ DEPOIS tratar as outras perguntas

### Sugestão de Implementação
```python
# context.py — novo campo
@property
def automation_1_sent(self) -> bool:
    return self._s.get("automation_1_sent", False)

def set_automation_1_sent(self, v: bool) -> None:
    self._s["automation_1_sent"] = v
```

```python
# tools/vanessa.py — dentro de trigger_automation_1()
# Após sucesso:
ctx.set_automation_1_sent(True)
```

### Regras a Adicionar no Prompt
```
REGRA DE CONTROLE DE AUTOMAÇÃO — siga rigorosamente:
  - ANTES de perguntar se o lead viu o conteúdo ou tem dúvidas, VERIFIQUE se a automação 1 já foi enviada.
  - Se a automação 1 NÃO foi enviada → NÃO pergunte sobre dúvidas do conteúdo.
  - Se o lead perguntar preço e automação 1 NÃO foi enviada → diga que precisa explicar como funciona primeiro.
  - Se o lead fez múltiplas perguntas → responda a mais simples, mas NÃO pule etapas do fluxo.
```

---

## 2. Reposicionamento de Linguagem — "Capacitação/Treinamento" em vez de "Curso"

### Problema Identificado
O agente às vezes usa a palavra **"curso"**, o que pode gerar objeção em leads que já tiveram experiência ruim com "cursos de ganhar dinheiro pela internet". O posicionamento correto é **capacitação** e **treinamento**.

### Proposta de Mudança

#### 2.1 — Regra de Linguagem no Prompt
- Substituir todas as menções de "curso" por "capacitação", "treinamento" ou "método"
- Exceção: quando o lead usar a palavra "curso", a Vanessa pode usar também para espelhar a linguagem do lead
- Adicionar regra explícita: "NUNCA diga 'vendo curso' ou 'tenho um curso'. Diga 'ofereço uma capacitação', 'um treinamento prático', 'um método'"

#### 2.2 — Atualizações no Prompt
Trechos a modificar:

| Trecho Atual | Novo Trecho |
|---|---|
| "como funciona o curso" | "como funciona o treinamento" |
| "curso de vender curso" | "capacitação de vender capacitação" |
| "vendo curso" | "ofereço capacitação/treinamento" |
| "incluso no curso" | "incluso na capacitação" |

#### 2.3 — Atualizações nas Tools
- `trigger_automation_2()` — mensagem "Vou te explicar certinho como funciona, olha só:" está OK (não menciona "curso")
- `present_price()` — usar "capacitação completa" em vez de "curso completo"
- `phase2_sequence.json` — revisar se há menções a "curso" (há: "piramide, curso de vender curso" → mudar para "pirâmide, capacitação de vender capacitação")

### Regras a Adicionar no Prompt
```
REGRAS DE POSICIONAMENTO — siga rigorosamente:
  - NUNCA diga que "vende curso". Use SEMPRE: "capacitação", "treinamento" ou "método".
  - Exemplos corretos: "ofereço uma capacitação prática", "um treinamento passo a passo", "o método que eu uso"
  - Exemplos incorretos: "vendo curso", "meu curso", "compre o curso"
  - Se o lead usar a palavra "curso", você PODE espelhar e usar também, mas prefira "capacitação/treinamento"
  - O produto é uma CAPACITAÇÃO PRÁTICA para gerar renda pela internet, NÃO um curso teórico
```

---

## 3. Revisão da Automação 2 — Agregar Valor no Momento do Preço

### Problema Identificado
A automação 2 está configurada como "explicar como funciona o curso". Porém, o uso correto é **agregar valor no momento de falar o preço**, não para tirar dúvidas de funcionamento.

### Proposta de Mudança

#### 3.1 — Novo Propósito da Automação 2
- **Quando acionar:** APENAS na **primeira vez** que for falar o preço, E somente se:
  1. O lead já respondeu as perguntas iniciais de qualificação
  2. A automação 1 já foi acionada e o lead já viu o conteúdo
  3. O lead perguntou sobre preço OU demonstrou interesse em saber o valor
- **Quando NÃO acionar:**
  - Quando o lead tiver objeção de preço (já está no processo de negociação)
  - Quando o lead já viu a automação 2 antes
  - Quando o lead ainda não passou pela qualificação inicial

#### 3.2 — Flag `automation_2_sent` no SessionContext
- Adicionar campo booleano `automation_2_sent` (inicia `False`, muda para `True` quando `trigger_automation_2()` é chamada)
- **Regra:** Só acionar automação 2 se `automation_2_sent == False`

#### 3.3 — Novo Fluxo de Preço com Automação 2
```
Lead: "Quanto é?" (depois de ver automação 1)

Vanessa: "{nome}, que bom que você quer saber! Antes de te falar o valor, 
          vou te mandar um material rápido que mostra tudo que está incluso 
          e como o treinamento pode te ajudar. Pode ser?"
          → Aguardar resposta

Lead: "Pode ser!"
          → trigger_automation_2() (agrega valor, mostra entregáveis, transformação)
          → automation_2_sent = True

[AUTOMAÇÃO 2 TERMINA]

Vanessa: "Então, {nome}, o investimento é R$399,90 à vista ou 12x de R$41,15. 
          Faz sentido pra você?"
          → present_price(tier=1)

[SE LEAD ACHAR CARO → NEGOCIAÇÃO NORMAL, SEM re-acionar automação 2]
```

#### 3.4 — Atualização da Tool `trigger_automation_2()`
- Mudar o texto preamble de "Vou te explicar certinho como funciona, olha só:" para algo que agregue valor:
  - Novo texto: "Antes de te falar o valor, olha só tudo que está incluso na capacitação:"
- Atualizar docstring para refletir o novo propósito

### Sugestão de Implementação
```python
# context.py — novo campo
@property
def automation_2_sent(self) -> bool:
    return self._s.get("automation_2_sent", False)

def set_automation_2_sent(self, v: bool) -> None:
    self._s["automation_2_sent"] = v
```

```python
# tools/vanessa.py — dentro de trigger_automation_2()
# Mudar preamble:
await automation.send_text_message(conv_id, "Antes de te falar o valor, olha só tudo que está incluso na capacitação:")

# Após sucesso:
ctx.set_automation_2_sent(True)
```

### Regras a Adicionar no Prompt
```
AUTOMAÇÃO 2 — AGREGAR VALOR NO PREÇO — siga rigorosamente:
  - A automação 2 serve para AGREGAR VALOR antes de falar o preço.
  - Quando acionar: NA PRIMEIRA VEZ que for falar o preço, APÓS automação 1 já ter sido enviada.
  - Pré-requisitos para acionar:
    1. Lead respondeu perguntas iniciais de qualificação
    2. Automação 1 já foi enviada (automation_1_sent == True)
    3. Lead perguntou sobre preço OU demonstrou interesse
    4. Automação 2 ainda NÃO foi enviada (automation_2_sent == False)
  - Quando NÃO acionar:
    - Quando o lead tiver objeção de preço (já está negociando)
    - Quando automação 2 já foi enviada antes
  - Após a automação 2 → apresente o preço com present_price(tier=1)
  - Na negociação subsequente (lead acha caro) → NÃO re-acione automação 2. Siga o fluxo normal de negociação.
```

---

## 4. Ajustes Adicionais Sugeridos

### 4.1 — Flag de "Fase Atual" do Lead
**Problema:** O agente não sabe explicitamente em que fase do funil o lead está, o que pode causar confusão.

**Proposta:** Adicionar campo `funnel_phase` no SessionContext:
```python
phases = {
    0: "introduction",       # Apresentação + perguntar nome
    1: "qualification",      # Perguntas de qualificação
    2: "content_delivery",   # Automação 1 enviada
    3: "value_building",     # Automação 2 enviada (agregando valor)
    4: "price_presentation", # Preço apresentado
    5: "negotiation",        # Negociação de preço
    6: "closing",            # Link enviado, aguardando compra
    7: "closed_won",         # Comprou
    8: "closed_lost",        # Não qualificou / sem budget
}
```

**Benefício:** O agente pode consultar `funnel_phase` para saber exatamente o que fazer a seguir.

### 4.2 — Reforço da Regra Anti-Loop com Estado
**Problema:** Mesmo com a regra anti-loop, o agente às vezes repete perguntas quando o lead faz múltiplas perguntas.

**Proposta:** Adicionar campo `last_question_asked` no SessionContext para rastrear a última pergunta feita. Se o lead não respondeu, não repetir.

### 4.3 — Resposta a Mensagens Multi-pergunta
**Problema:** Quando o lead faz 3 perguntas de uma vez, o agente pode se perder.

**Proposta:** Adicionar regra explícita no prompt:
```
REGRA DE MÚLTIPLAS PERGUNTAS DO LEAD:
  - Quando o lead fizer várias perguntas de uma vez:
    1. Responda a pergunta mais simples/direta PRIMEIRO
    2. Reconheça as outras perguntas ("Vi que você também perguntou sobre X...")
    3. MAS NÃO pule etapas do fluxo. Se automação 1 não foi enviada, conduza para lá primeiro.
    4. As outras perguntas serão respondidas naturalmente ao longo do fluxo.
```

### 4.4 — Log de Estado da Conversa
**Proposta:** Registrar no `log_store` ou `transaction_log` quando:
- Automação 1 foi enviada
- Automação 2 foi enviada
- Preço foi apresentado (e qual tier)
- Link de pagamento foi enviado
- Lead foi qualificado/desqualificado

**Benefício:** Permite análise de conversão e debugging de conversas.

---

## Resumo das Mudanças Necessárias

### Arquivos a Modificar

| Arquivo | Mudança |
|---|---|
| `prompts/vanessa.py` | Adicionar regras de controle de automação, reposicionar linguagem (capacitação vs curso), redefinir propósito da automação 2, regra de múltiplas perguntas |
| `tools/vanessa.py` | Adicionar flags `automation_1_sent` e `automation_2_sent`, atualizar preamble da automação 2 |
| `app/context.py` | Adicionar campos: `automation_1_sent`, `automation_2_sent`, `funnel_phase`, `last_question_asked` |
| `data/phase2_sequence.json` | Revisar menções a "curso" e substituir por "capacitação/treinamento" |

### Novos Campos no SessionContext
```python
"automation_1_sent": False,    # True após trigger_automation_1() com sucesso
"automation_2_sent": False,    # True após trigger_automation_2() com sucesso
"funnel_phase": 0,             # 0-8, fase atual do lead no funil
"last_question_asked": "",     # Última pergunta feita ao lead (anti-repetição)
```

### Campos Existentes a Manter
```python
"content_seen": True,          # Já setado após automação 1 — manter como alias de automation_1_sent
"engagement_score": 0,         # Medir engajamento
"lead_budget": 0.0,            # Budget do lead
"negotiated_amount": 0.0,      # Valor negociado
"challenge_offered": False,    # Desafio oferecido
"is_qualified": False,         # Lead qualificado
"intro_sent": False,           # Intro enviada
"is_interested": False,        # Lead interessado
"is_purchased": False,         # Lead comprou
"payment_tier_sent": 0,        # Tier do pagamento enviado
```

---

## Ordem Sugerida de Implementação

1. **Prioridade CRÍTICA:** Flag `automation_1_sent` + regra de bloqueio no prompt (ponto 1)
2. **Prioridade CRÍTICA:** Reposicionamento de linguagem "capacitação/treinamento" (ponto 2)
3. **Prioridade CRÍTICA:** Revisão da automação 2 para agregar valor no preço (ponto 3)
4. **Prioridade ALTA:** Regra de múltiplas perguntas do lead (ponto 4.3)
5. **Prioridade MÉDIA:** Flag `funnel_phase` para controle de fase (ponto 4.1)
6. **Prioridade MÉDIA:** Flag `automation_2_sent` para evitar re-envio (ponto 3.2)
7. **Prioridade BAIXA:** Log de estado da conversa (ponto 4.4)
8. **Prioridade BAIXA:** Flag `last_question_asked` anti-repetição (ponto 4.2)

---

## Implemetação feita pelo agente
Implementações concluídas. Resumo do que foi feito:
app/context.py — 4 novos campos:
- automation_1_sent / automation_2_sent — flags de controle
- funnel_phase — fase do funil (0-8)
- last_question_asked — anti-repetição
tools/vanessa.py:
- trigger_automation_1() → seta automation_1_sent=True + funnel_phase=2
- trigger_automation_2() → preamble mudado para "Antes de te falar o valor, olha só tudo que está incluso na capacitação:" + seta automation_2_sent=True + funnel_phase=3
- present_price() → seta funnel_phase=4
- send_payment_link() → seta funnel_phase=6
- send_challenge_link() → seta funnel_phase=6
- set_lead_info() → seta funnel_phase=1 quando salva nome
- get_lead_info() → agora retorna estado completo das automações e funil
prompts/vanessa.py — 4 novas regras críticas:
- Controle de automação (trava preço sem automação 1)
- Múltiplas perguntas do lead (responde a simples, não pula fluxo)
- Posicionamento (capacitação/treinamento, nunca "curso")
- Automação 2 redefinida (agrega valor no preço, só 1x)
data/phase2_sequence.json — "curso de vender curso" → "capacitação de vender capacitação"