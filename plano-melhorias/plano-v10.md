# Plano de Melhorias — Agente Vanessa (v10)

> Documento criado em: 2026-05-07
> Status: Aguardando validação

---

## 1. Fluxo Inicial — Flexível, Não Fixo em 3 Perguntas

### Problema Atual
O prompt atual (Passo 2) força exatamente **3 perguntas de qualificação** antes de acionar a automação:
1. "Você está começando agora ou já fez algum curso?"
2. "O que te fez buscar isso agora?"
3. "Se pudesse mudar uma coisa na sua vida financeira, o que seria?"

Isso torna a conversa mecânica e pode afastar leads já engajados.

### Proposta de Mudança
- **Fazer perguntas de forma natural e adaptativa**, não fixa em 3
- **Monitorar sinais de engajamento** do lead (respostas longas, perguntas de volta, entusiasmo)
- Quando o lead demonstrar engajamento → perguntar: *"Posso te mandar alguns áudios e vídeos rápidos explicando como funciona o curso?"*
- Só após o lead dar abertura → acionar `trigger_automation_1()`

### Sugestão de Implementação
- Adicionar campo `engagement_score` no `SessionContext` (0-10)
- Regras de pontuação:
  - Lead responde com frase longa (>20 chars): +2
  - Lead faz pergunta de volta: +3
  - Lead usa palavras positivas ("legal", "interessante", "quero saber"): +2
  - Lead responde monossílabo ("sim", "ok", "é"): +0
- Quando `engagement_score >= 5` → Vanessa pode perguntar se pode enviar os áudios/vídeos
- Mínimo de 1 pergunta de qualificação sempre (perfil do lead)

### Observações
- Não remover completamente a qualificação — é importante para personalizar o fechamento
- A IA deve ter liberdade para adaptar o número de perguntas ao contexto
- O `nextActionHint` das tools deve refletir essa flexibilidade

---

## 2. Correção da Mensagem Inicial — Lead Já Pergunta "Como Funciona?"

### Problema Atual
Quando o lead chega perguntando "Oii tenho interesse! Como funciona?", a IA às vezes **pula direto para a automação** sem:
1. Perguntar o nome
2. Validar dúvidas
3. Entender a situação do lead

### Proposta de Mudança
- **Regra absoluta:** SEMPRE perguntar o nome primeiro, independente do que o lead disser
- Se o lead já demonstrou interesse → reconhecer e validar, MAS ainda assim perguntar o nome
- Após saber o nome → fazer 1-2 perguntas de qualificação (adaptativas, não fixas)
- Só após entender a situação → perguntar se pode explicar (e então acionar automação)

### Exemplo de Fluxo Correto
```
Lead: "Oii tenho interesse! Como funciona?"
Vanessa: "Oii! Tudo bem? Sou a Vanessa, mas pode me chamar de Van! 😊
          , me diz: como você se chama?"

Lead: "Sou a Maria"
Vanessa: "Prazer Maria! Me conta: você já conhece algo sobre ganhar dinheiro pela internet
          ou tá começando do zero?"

Lead: "Tô começando do zero"
Vanessa: "Entendi! E o que te fez buscar isso agora? Tem alguma meta ou sonho?"

Lead: "Quero uma renda extra pra ajudar em casa"
Vanessa: "Entendi perfeitamente, Maria. Posso te mandar alguns áudios e vídeos rápidos
          explicando como funciona o método? É bem prático."

Lead: "Pode mandar sim!"
→ trigger_automation_1()
```

### Sugestão de Implementação
- Adicionar regra explícita no prompt: "SEMPRE pergunte o nome PRIMEIRO, mesmo que o lead já tenha demonstrado interesse ou perguntado como funciona"
- Adicionar flag `name_collected` no contexto para controle
- Reforçar no prompt que a automação NUNCA deve ser acionada antes de saber o nome E entender a situação

---

## 3. Preços Sempre no Final — Só Após o Lead Entender o Valor

### Problema Atual
A IA às vezes menciona preço antes do lead ter visto o conteúdo da automação 1 (apresentação do curso).

### Proposta de Mudança
- **Regra absoluta:** Preço SÓ é mencionado após:
  1. Lead ter assistido o conteúdo da automação 1 (apresentação)
  2. Lead ter entendido o valor do produto e entregáveis
  3. Lead ter demonstrado interesse em adquirir OU perguntado sobre preço

### Fluxo Quando Lead Pergunta Preço ANTES de Ver o Conteúdo
A Vanessa **NÃO** redireciona direto para automação. Ela faz uma abordagem consultiva:

```
Lead: "Quanto custa?" (antes de ver automação 1)
Vanessa: "{nome}, antes de te falar o valor, quero saber: você já entendeu 
          direitinho como funciona o curso e o que está incluso? 
          Ficou alguma dúvida?"

→ Se NÃO entendeu → trigger_automation_2() (explica como funciona o curso)
→ Se tem dúvidas → responder as dúvidas com send_text_message()
→ Se entendeu, sem dúvidas, e se identificou → aí sim falar de valores
```

### Sugestão de Implementação
- Adicionar flag `content_seen` no `SessionContext` (setado após `trigger_automation_1()`)
  - O que é: campo booleano que trava a IA de mencionar preço antes do lead ver a apresentação
  - Inicia `False` → muda para `True` após `trigger_automation_1()`
  - Regra no prompt: "NUNCA mencione preço se `content_seen` for falso"
- Se lead perguntar preço antes → Vanessa pergunta se entendeu o produto → decide entre automação 2, responder dúvidas, ou falar de preço

---

## 4. Negociação de Preço — Validar Dor e Perguntar Quanto Pode Investir

### Problema Atual
A descida de tiers é fixa (499 → 399 → 299) sem negociação real. A IA não pergunta quanto o lead pode investir.

### Proposta de Mudança — Nova Estrutura de Preços

**O tier de R$499 NÃO está mais sendo ofertado.**

| Tier | Valor | Parcelas | Link |
|---|---|---|---|
| 1 | R$399,00 | 12x R$41,15 | `LINK_PADRAO` |
| 2 | R$299,00 | 12x R$31,02 | `LINK_DESCONTO` |
| 3 | R$249,00 | — | `https://pay.kiwify.com.br/COCyYNU?afid=LEjIA9wW&src=vanlxyads` |
| 4 | R$199,00 | — | `https://pay.kiwify.com.br/lj7aq9a?afid=LEjIA9wW&src=vanlxyads` |
| 5 | R$179,00 | — | `https://pay.kiwify.com.br/7fPOC7X?afid=LEjIA9wW&src=vanlxyads` |
| Desafio 7 dias | R$47,00 | — | `https://pay.cakto.com.br/m42xe54` |

### Novo Fluxo de Negociação

```
Lead: "Achei caro"
Vanessa: "{nome}, entendo totalmente. Me conta: o que mais te preocupa? 
          É o valor em si, ou tá com medo de não dar certo?"
          → VALIDAR A DOR

Lead: "É o valor mesmo, tá apertado"
Vanessa: "Te entendo demais. E sendo sincera comigo: quanto você teria 
          disponível pra investir no momento? Assim eu vejo o que consigo fazer por você."
          → NEGOCIAR

Lead: "Teria uns 200 reais"
→ Vanessa oferece o tier mais próximo (R$199)

Lead: "Não tenho nem 100 reais"
→ Vanessa oferece o desafio de 7 dias (R$47)

Lead: "Não tenho nada"
→ NÃO é lead qualificado. Encerrar com empatia.
```

### Sugestão de Implementação
- Adicionar nova tool `negotiate_price()` ou expandir `present_price()` para aceitar valor customizado
- Adicionar campo `negotiated_amount` no `SessionContext`
- Adicionar campo `lead_budget` no `SessionContext` (quanto o lead disse que pode pagar)
- Nova tool `send_challenge_link()` para o desafio de 7 dias (R$47)
- Atualizar `send_payment_link()` para suportar os novos tiers (1-5 + desafio)

### Links Atualizados
```python
LINK_PADRAO = "https://pay.kiwify.com.br/G44fCQz?afid=LEjIA9wW&src=vanlxyads"      # R$399
LINK_DESCONTO = "https://pay.kiwify.com.br/x1rMBUT?afid=LEjIA9wW&src=vanlxyads"      # R$299
LINK_TIER_3 = "https://pay.kiwify.com.br/COCyYNU?afid=LEjIA9wW&src=vanlxyads"        # R$249
LINK_TIER_4 = "https://pay.kiwify.com.br/lj7aq9a?afid=LEjIA9wW&src=vanlxyads"        # R$199
LINK_TIER_5 = "https://pay.kiwify.com.br/7fPOC7X?afid=LEjIA9wW&src=vanlxyads"        # R$179
LINK_DESAFIO = "https://pay.cakto.com.br/m42xe54"                                     # R$47
```

### Observações Críticas
- O tier de R$499 deve ser **removido completamente** do código e do prompt
- A IA deve SEMPRE validar a dor antes de oferecer desconto
- A pergunta "quanto você teria disponível?" é fundamental — transforma a conversa de "está caro" para "vamos encontrar uma solução"
- Se o lead não tem nem R$47 → não é lead qualificado. A IA deve encerrar com empatia mas sem insistir

---

## 5. Desafio de 7 Dias — Última Opção para Leads Sem Budget

### Problema Atual
Não existe menção ao desafio de 7 dias como opção de entrada.

### Proposta de Mudança
- Quando o lead disser que não tem dinheiro para nenhum dos tiers → oferecer o desafio de 7 dias por R$47
- Posicionar como "primeiro passo" e "oportunidade de começar com pouco"
- Se o lead não tem nem R$47 → classificar como "não qualificado" e encerrar com empatia

### Exemplo de Mensagem
```
"{nome}, entendo perfeitamente. Olha, se tá realmente apertado, tenho uma opção 
bem acessível: o Desafio de 7 Dias por apenas R$47. É um ótimo ponto de partida 
pra você já começar a aplicar o método. O que acha?"
```

### Sugestão de Implementação
- Nova tool `send_challenge_link()`:
  - Envia texto explicativo + link do Cakto
  - Set flag `challenge_offered = True` no contexto
- Adicionar regra no prompt sobre quando oferecer o desafio

---

## Resumo das Mudanças Necessárias

### Arquivos a Modificar

| Arquivo | Mudança |
|---|---|
| `prompts/vanessa.py` | Reescrever fluxo inicial, regras de preço, negociação |
| `tools/vanessa.py` | Atualizar tiers, adicionar `send_challenge_link()`, expandir `present_price()` |
| `app/context.py` | Adicionar campos: `engagement_score`, `content_seen`, `lead_budget`, `negotiated_amount`, `challenge_offered` |

### Novos Campos no SessionContext
```python
"engagement_score": 0,        # 0-10, mede engajamento do lead
"content_seen": False,        # True após automação 1
"lead_budget": 0,             # Quanto o lead disse que pode pagar
"negotiated_amount": 0,       # Valor negociado final
"challenge_offered": False,   # Se já ofereceu o desafio
"name_collected": False,      # Se já sabe o nome do lead
"is_qualified": False,        # Lead qualificado (tem budget >= R$47)
```

### Tiers Atualizados
```
Tier 1: R$399  → LINK_PADRAO (já existe)
Tier 2: R$299  → LINK_DESCONTO (já existe)
Tier 3: R$249  → LINK_TIER_3 (novo)
Tier 4: R$199  → LINK_TIER_4 (novo)
Tier 5: R$179  → LINK_TIER_5 (novo)
Desafio: R$47  → LINK_DESAFIO (novo, Cakto)
```

---

## Pontos Adicionais Sugeridos (Fora dos 5 Originais)

### A. Flag de "Lead Qualificado" ✅ IMPLEMENTAR
- Adicionar `is_qualified` no contexto
- Lead é qualificado se: nome coletado + perfil salvo + demonstrou interesse real
- Lead NÃO qualificado se: não tem budget nem para o desafio (R$47)
- Útil para métricas e relatórios no admin

### B. Log de Negociação ✅ IMPLEMENTAR
- Registrar no `log_store` quando o lead menciona um budget
- Registrar qual tier foi oferecido e qual foi aceito
- Útil para análise de conversão por faixa de preço

### C. Timeout de Engajamento ❌ NÃO IMPLEMENTAR AGORA
- Reservado para versão futura

### D. Personalização por Perfil ✅ IMPLEMENTAR
- Se lead é "iniciante" → linguagem mais simples, mais acolhimento
- Se lead é "experiente_ruim" → focar em superar experiências passadas
- Se lead é "experiente" → focar em diferenciais, próximo nível
- Reforçar no prompt com exemplos de linguagem por perfil

---

## Ordem Sugerida de Implementação

1. **Prioridade ALTA:** Atualizar tiers de preço (remover R$499, adicionar R$249, R$199, R$179)
2. **Prioridade ALTA:** Corrigir fluxo inicial (sempre pedir nome primeiro, qualificação flexível)
3. **Prioridade ALTA:** Adicionar negociação de preço (validar dor + perguntar budget)
4. **Prioridade ALTA:** Correção do fluxo de preço antecipado (perguntar se entendeu → automação 2 / dúvidas / preço)
5. **Prioridade MÉDIA:** Adicionar desafio de 7 dias (tool + link)
6. **Prioridade MÉDIA:** Flag `is_qualified` + personalização por perfil
7. **Prioridade MÉDIA:** Log de negociação no `log_store`

---

*Aguardando validação para iniciar implementação.*
