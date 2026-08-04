# Mapeamento Completo de Automações — VFO (Vanessa)

**Gerado em:** 2026-07-14
**Escopo:** `vfo/` — agente WhatsApp "Vanessa" (venda de capacitação de renda com produtos físicos via Shopee/TikTok Shop/Mercado Livre)
**Nota:** projeto migrado de uma infraestrutura anterior para `vfo/` em 14/07/2026.
**Fontes analisadas:** `app/datacrazy_automation.py`, `tools/vanessa.py`, `prompts/vanessa.py`, `app/context.py`, `app/agent_factory.py`, `app/follow_up_scheduler.py`, `app/follow_up_state.py`, `data/objections_library.json`, `data/follow_up_templates.json`, `data/follow_up_templates_v1.json`, `data/phase2_sequence.json`, `data/report_datacrazy_errors_05062026.md`, `plano-melhorias/*.md`, `git log`

---

## 1. Visão Geral

### 1.1 Quantas automações existem

O dicionário `DataCrazyAutomationClient.AUTOMATION_WEBHOOKS` (arquivo `app/datacrazy_automation.py`) define **25 chaves de automação** por instância (2 instâncias/números de WhatsApp, `_WEBHOOKS_V1` e `_WEBHOOKS_V2`, com URLs distintas mas as mesmas 25 chaves):

- **17 automações "de fluxo principal / qualificação / objeção"** disparadas diretamente por tools que o LLM pode chamar durante a conversa (`automacao_1`, `automacao_2`, `pergunta_experiencia`, `ja_fez_mentoria`, `precisa_computador`, `tempo_resultados`, `tempo_livre`, `experiencias_ruins`, `tem_medo`, `tem_profissao`, `outro_pais`, `e_mae`, `faz_faculdade`, `e_crista`, `como_sei_seguro`, `comecando_do_zero`, `preciso_pagar`, `vai_ver` — na verdade são 18 chaves distintas, ver tabela-mestre).
- **9 automações "bf_labs_*" reservadas ao follow-up automático (scheduler)** — `bf_labs_audio_inicial`, `bf_labs_follow3_pt1`, `bf_labs_automacao1`, `bf_labs_follow2_pt2`, `bf_labs_follow3_pt2`, `bf_labs_follow1_pt3`, `bf_labs_follow2_pt3`, `bf_labs_follow3_pt3`, `bf_labs_follow_janela_24h`. Duas delas (`bf_labs_audio_inicial` e `bf_labs_automacao1`) são apenas aliases que reaproveitam os MESMOS webhooks de `pergunta_experiencia` e `automacao_1` (confirmado no plano `follow-up-implementação2.md`, linhas 800-801).
- **1 automação pós-pagamento** — `pos_pagamento`, disparada após a venda.

Total de chaves únicas no dicionário: **25** (`automacao_1`, `automacao_2`, `pergunta_experiencia`, `ja_fez_mentoria`, `precisa_computador`, `tempo_resultados`, `tempo_livre`, `experiencias_ruins`, `tem_medo`, `tem_profissao`, `outro_pais`, `e_mae`, `faz_faculdade`, `e_crista`, `como_sei_seguro`, `comecando_do_zero`, `preciso_pagar`, `vai_ver`, `bf_labs_audio_inicial`, `bf_labs_follow3_pt1`, `bf_labs_automacao1`, `bf_labs_follow2_pt2`, `bf_labs_follow3_pt2`, `bf_labs_follow1_pt3`, `bf_labs_follow2_pt3`, `bf_labs_follow3_pt3`, `bf_labs_follow_janela_24h`, `pos_pagamento`) — confere: são 27 chaves no dicionário Python (contei linha a linha na Seção 3), das quais **17 são "acionáveis pelo LLM em conversa"** e **10 são exclusivas do scheduler de follow-up** (9 `bf_labs_*` + a `janela_24h` reaproveita `bf_labs_follow_janela_24h`), mais `pos_pagamento` acionada por código (não pelo LLM diretamente).

⚠️ Nota de precisão: a chave `preciso_pagar` na instância v2 (`_WEBHOOKS_V2`) está **vazia** (`""`), com comentário no código: `# ⚠️ Bruno não forneceu — usar fallback v1`. O client tem fallback automático para a URL v1 nesse caso (`trigger_automation`, linhas 171-175).

### 1.2 Arquitetura de disparo

```
Lead envia mensagem no WhatsApp
        ↓
DataCrazy CRM → webhook → VFO (whatsapp_api.py, fora do escopo lido)
        ↓
Agno Agent "Vanessa" (agent_factory.py) processa a mensagem
        ↓
LLM decide chamar uma tool trigger_*() (tools/vanessa.py)
        ↓
DataCrazyAutomationClient.trigger_automation(automation_key, conversation_id, contact_id, external_id)
        ↓
POST para o webhook do DataCrazy (URL específica por instância + automation_key)
        ↓
DataCrazy CRM dispara o "flow" pré-configurado no próprio CRM
        ↓
Flow envia áudio/vídeo/imagem/texto pré-gravado ao lead via WhatsApp
```

Em paralelo, existe um **segundo caminho de disparo**, independente da conversa em tempo real: o `follow_up_scheduler.py` roda em loop (`_POLL_INTERVAL = 5s`), varre todas as sessões no SQLite (`agno_sessions` + tabela dedicada `follow_up_state`) e dispara automações `bf_labs_*` por temporização (ver Seção 3 — Máquina de Estados).

O conteúdo REAL enviado (áudio, vídeo, imagem) está configurado dentro do próprio CRM DataCrazy (fora deste repositório) — o código VFO só dispara o webhook com `lead_id`/`conversation_id`/`contactId`/`phone`. O que se pôde reconstruir sobre o conteúdo vem de: (a) docstrings/comentários no código, (b) `data/objections_library.json` (que parecem ser as transcrições/roteiro dos áudios, usadas como fallback de texto), (c) `plano-melhorias/plano-v25.md` (que documenta as transcrições dos 11 áudios de objeção), (d) `data/phase2_sequence.json` (roteiro textual completo da automação 1).

### 1.3 Duas instâncias (dois números de WhatsApp)

O sistema atende **dois números** simultaneamente (`_WEBHOOKS_V1` para a instância `<instance-id-1>`, `_WEBHOOKS_V2` para `<instance-id-2>`), cada um com seu próprio conjunto de 25+ URLs de webhook apontando para os mesmos flows conceituais no CRM, mas fisicamente URLs diferentes. Isso é selecionado via `DATACRAZY_INSTANCE_ID` (config, não lido neste levantamento).

---

## 2. Tabela-mestre

| Automação (key) | Gatilho (quando é chamada) | Conteúdo enviado (resumo) | Estágio do funil | Flag/guarda de sessão |
|---|---|---|---|---|
| `pergunta_experiencia` (tool `trigger_experiencia`) | Logo após salvar o nome do lead (Passo 1b). Substitui a pergunta de qualificação textual. | Áudio perguntando se o lead conhece mercado de afiliado ou já fez mentoria/curso. | Qualificação | `experiencia_sent` (ctx + follow_up_state); bloqueia reenvio; também checa `follow_1_1_sent` (evita duplicar com o follow-up scheduler) |
| `ja_fez_mentoria` (tool `trigger_mentoria`) | Lead diz que já fez mentoria/curso antes. | Áudio direcionado a quem já tem experiência prévia. Dispara `ask_motivation()` automaticamente depois. | Qualificação | `mentoria_sent` |
| `comecando_do_zero` (tool `trigger_comecando_do_zero`) | Lead diz que nunca trabalhou com internet / não tem experiência digital / é iniciante. | Áudio para iniciantes sem experiência (transcrição completa em `objections_library.json` → "começando do zero"). Dispara `ask_motivation()` automaticamente. | Qualificação | `comecando_do_zero_sent` |
| `automacao_1` (tool `trigger_automation_1`) | Após qualificação completa (nome + experiência + motivação) e o lead autorizar "posso te mandar uns áudios e vídeos?". | Sequência longa de apresentação: textos + 2 lotes de áudio (1-3, 4-6), vídeo de saque ~R$50 mil, vídeo podcast Kiwify, bloco de provas sociais (1 vídeo + 3 imagens), termina perguntando "ficou alguma dúvida?". Roteiro completo em `data/phase2_sequence.json`. | Apresentação/conteúdo | `automation_1_sent` (ctx + follow_up_state); também seta `content_seen=True`, `follow_1_4_sent=True` (bloqueia scheduler), `funnel_phase=2` |
| `automacao_2` (tool `trigger_automation_2`) | Primeira vez que se fala de preço, APÓS automação 1 enviada E lead confirmar "sim" a "posso te mandar um material que mostra tudo que está incluso?". | Conteúdo de "agregar valor" que já inclui o preço padrão R$299,90 (tier 1). | Preço/negociação | `automation_2_sent`; hard gate: bloqueia se `automation_1_sent==False`; `funnel_phase=3` |
| `precisa_computador` (tool `trigger_precisa_computador`) | Lead pergunta se precisa de computador/notebook/celular para trabalhar. | Áudio: "não precisa de computador, dá pelo celular" (transcrição completa disponível). | Objeção (1x por lead) | `precisa_computador_sent` |
| `tempo_resultados` (tool `trigger_tempo_resultados`) | Lead pergunta quanto tempo demora para ter resultado. | Áudio sobre tempo de resultados (ex.: "primeiro resultado com 13 dias, 1 mês fez R$3.200"). | Objeção | `tempo_resultados_sent` |
| `tempo_livre` (tool `trigger_tempo_livre`) | Lead diz que tem pouco tempo livre / rotina corrida. | Áudio: "30 minutinhos livres já dá pra iniciar". | Objeção | `tempo_livre_sent` |
| `experiencias_ruins` (tool `trigger_experiencias_ruins`) | Lead diz que já comprou curso/mentoria antes e não teve resultado / foi enganado. | Áudio de empatia sobre experiências ruins anteriores. | Objeção | `experiencias_ruins_sent` |
| `tem_medo` (tool `trigger_tem_medo`) | Lead diz que está com medo/insegura/ansiosa. | Áudio de acolhimento sobre medo. | Objeção | `tem_medo_sent` |
| `tem_profissao` (tool `trigger_tem_profissao`) | Lead menciona já ter profissão (enfermeira, professora, CLT etc.). | Áudio sobre conciliar profissão atual com a renda extra. | Objeção/rapport | `tem_profissao_sent` |
| `outro_pais` (tool `trigger_outro_pais`) | Lead diz que mora fora do Brasil. | Áudio sobre alunas de outros países, ganhos em dólar/euro. | Objeção/rapport | `outro_pais_sent` |
| `e_mae` (tool `trigger_e_mae`) | Lead diz que é mãe. | Áudio de identificação/rapport com mães. | Rapport | `e_mae_sent` |
| `faz_faculdade` (tool `trigger_faz_faculdade`) | Lead diz que está cursando faculdade. | Áudio sobre conciliar com estudos. | Rapport | `faz_faculdade_sent` |
| `e_crista` (tool `trigger_e_crista`) | Lead diz que é cristã/evangélica/católica. | Áudio sobre princípios e valores da mentora. | Rapport | `e_crista_sent` |
| `como_sei_seguro` (tool `trigger_como_sei_seguro`) | Lead pergunta se é seguro / se pode confiar / se é golpe. | Áudio direcionando para o Instagram da mentora + menção a podcast de 1 milhão em resultados. | Objeção (confiança) | `como_sei_seguro_sent` |
| `preciso_pagar` (tool `trigger_preciso_pagar`) | Lead pergunta se precisa **investir dinheiro** em ferramentas/anúncios/produtos (⚠️ distinto de "precisa de computador"). | Áudio (transcrição não capturada nos JSONs — só existe no CRM). Texto equivalente em `objections_library.json` → "preciso pagar": estratégias são gratuitas, único investimento é conhecimento. | Objeção (financeira) | `preciso_pagar_sent` (contexto) / porém a tool interna usa `preciso_pagar` como key da automação — ver Seção 6 (Lacunas) sobre a divergência de nome `preciso_pagar` vs `preciso_pagar_sent`/`preciso pagar` |
| `vai_ver` (tool `trigger_vai_ver`) | Lead diz que ainda não viu o conteúdo mas vai ver depois. | Áudio + CTA automático (a própria automação já envia o CTA, diferente das demais). Texto equivalente em `objections_library.json` → "vai ver". | Objeção/retenção | `vai_ver_sent` |
| `pos_pagamento` (disparada dentro de `send_payment_link` e `send_challenge_link`, não é tool própria) | Automaticamente, logo após o link de pagamento ser enviado (tier 1-4 ou desafio R$47). | Conteúdo pós-venda (upsells, acesso vitalício etc. — não documentado em detalhe no código, apenas mencionado no comentário `# Trigger pós-pagamento automation (upsells, acesso vitalício, etc.)`). | Pós-venda | Nenhuma flag de "já enviado" — dispara sempre que um link de pagamento é enviado (best-effort, falha não bloqueia: `except Exception as auto_exc: logger.warning(...)`) |
| `bf_labs_audio_inicial` (scheduler, Fluxo 1 / step 1) | Scheduler dispara 30min após última msg do lead, SE `automation_1_sent==False` e `experiencia_sent`/`follow_1_1_sent` ainda não setados. | Mesmo webhook de `pergunta_experiencia` (alias). | Reengajamento pré-qualificação | `follow_1_1_sent` |
| `bf_labs_follow3_pt1` (scheduler, Fluxo 1 / step 3) | Scheduler, 2h após última msg, dentro do Fluxo 1. | Conteúdo de reengajamento (não documentado em detalhe). | Reengajamento | `follow_1_3_sent` |
| `bf_labs_automacao1` (scheduler, Fluxo 1 / step 4) | Scheduler, 5h após última msg, dentro do Fluxo 1, SE `automation_1_sent==False`. | Mesmo webhook de `automacao_1` (alias) — reenvia a apresentação completa via follow-up. | Reengajamento pré-conteúdo | `follow_1_4_sent`; sincroniza com `automation_1_sent=True` |
| `bf_labs_follow2_pt2` (scheduler, Fluxo 2 / step 2) | Scheduler, 2h após entrar no Fluxo 2 (pós automação 1 enviada, pré automação 2). | Conteúdo de reengajamento pós-apresentação. | Reengajamento pós-conteúdo | `follow_2_2_sent` |
| `bf_labs_follow3_pt2` (scheduler, Fluxo 2 / step 3) | Scheduler, 4h após entrar no Fluxo 2. | Conteúdo de reengajamento. | Reengajamento pós-conteúdo | `follow_2_3_sent` |
| `bf_labs_follow1_pt3` (scheduler, Fluxo 3 / step 1) | Scheduler, 20min após entrar no Fluxo 3 (pós automação 2 / preço já apresentado). | Conteúdo de reengajamento pós-preço. | Reengajamento pós-preço | `follow_3_1_sent` |
| `bf_labs_follow2_pt3` (scheduler, Fluxo 3 / step 2) | Scheduler, 2h após entrar no Fluxo 3. | Conteúdo de reengajamento. | Reengajamento pós-preço | `follow_3_2_sent` |
| `bf_labs_follow3_pt3` (scheduler, Fluxo 3 / step 3) | Scheduler, 3h após entrar no Fluxo 3. | Conteúdo final do fluxo 3 — template documenta `handle_response: true, response_price: 299.9` (se lead responder com interesse, deve receber link de R$299,90). | Reengajamento final / conversão | `follow_3_3_sent`; marca `follow_up_expired=True` ao final do fluxo |
| `bf_labs_follow_janela_24h` (scheduler, especial) | Scheduler, entre 23h e 24h após o PRIMEIRO contato do lead (`lead_first_contact_at`), 1h antes da janela de 24h do WhatsApp Business API fechar. Só dispara se `is_purchased==False`. | Lead é avisado que foi "sorteada" com bônus + recebe link de pagamento/promoção embutido no fluxo do CRM. | Urgência/escassez, último esforço pré-fechamento de janela | `follow_janela_24h_sent`; usado depois para BLOQUEAR `send_payment_link()` (ver Seção 6) |

---

## 3. Detalhamento por automação

### 3.1 `pergunta_experiencia`

- **Tool:** `trigger_experiencia()`
- **Webhook (v1):** `.../ce7549d0-093f-4697-9048-54c858dd0564`
- **Docstring completa:**
  > "Trigger automation that asks if the lead knows about affiliate market or mentorship. Call this AFTER saving the lead's name (Passo 1b). Replaces the old text-based qualification question."
- **Trecho do system prompt que rege o disparo (Passo 1b):**
  > "PASSO 1b — Ao receber o nome do lead: Salve com set_lead_info(name=...). IMEDIATAMENTE após salvar o nome → chame trigger_experiencia(). Essa automação envia um áudio perguntando se o lead conhece mercado de afiliado ou já fez mentoria. ⚠️ NÃO faça perguntas de qualificação por texto. A automação substitui essa etapa. ⚠️ Após trigger_experiencia(), AGUARDE a resposta do lead."
- **Conteúdo enviado:** áudio perguntando se o lead já conhece mercado de afiliado ou já fez mentoria/curso. Não há transcrição literal capturada nos arquivos de dados; o conteúdo real está apenas no flow do CRM.
- **Condições/guards:** bloqueia reenvio se `ctx.experiencia_sent`, `fus.get_flag(...,"experiencia_sent")` OU `fus.get_flag(...,"follow_1_1_sent")` já True (isto é, também é bloqueado se o SCHEDULER já disparou o equivalente `bf_labs_audio_inicial`). Ao disparar com sucesso, seta `follow_1_2_sent=True` (pula o passo 2 do follow-up, pois o agente já fez a pergunta de qualificação).
- **Observações de planos/erros:** o alias `bf_labs_audio_inicial` reaproveita este mesmo webhook (confirmado em `follow-up-implementação2.md`).

### 3.2 `ja_fez_mentoria`

- **Tool:** `trigger_mentoria()`
- **Webhook (v1):** `.../feb915f7-81e7-4217-9326-09dc141a7e34`
- **Docstring completa:**
  > "Trigger automation for leads who already did mentorship/course. Call this when the lead mentions they already did a mentorship or course. After the audio finishes, call ask_motivation() to ask about their motivation."
- **Trecho do system prompt (Passo 1c):**
  > "Se o lead disser que JÁ FEZ mentoria ou curso → chame trigger_mentoria() PRIMEIRO, depois ask_motivation(). ⚠️ ORDEM OBRIGATÓRIA: tool de áudio PRIMEIRO, ask_motivation DEPOIS. [...] REGRA CRÍTICA — RESPOSTAS VAGAS/AMBÍGUAS: Se o lead responder de forma vaga [...] você DEVE pedir esclarecimento ANTES de tomar qualquer decisão. NUNCA assuma o perfil do lead com base em respostas ambíguas." (segue lista extensa de exemplos de respostas vagas: "sim", "mais ou menos", "um pouco", "já ouvi falar", "tenho interesse", "não sei direito").
- **Conteúdo enviado:** áudio dirigido a quem já tem experiência prévia com mentoria/curso — não há transcrição literal nos arquivos JSON analisados.
- **Comportamento de código notável:** ao disparar com sucesso, o próprio código chama automaticamente `_send_motivation_question()` (função interna) se `ctx.motivation_question_sent` ainda for False — ou seja, `trigger_mentoria()` já encadeia a pergunta de motivação, mesmo o prompt instruindo o LLM a chamar `ask_motivation()` separadamente. Isso é redundante/duplo-caminho (ver Seção 6).
- **Guard:** `mentoria_sent`.

### 3.3 `comecando_do_zero`

- **Tool:** `trigger_comecando_do_zero()`
- **Webhook (v1):** `.../3b0f309b-8071-40b9-bf85-a6425620b4ab`
- **Docstring completa:**
  > "Trigger audio: lead says they have no digital/internet experience. Automatically sends the motivation question after the audio."
- **Conteúdo enviado (transcrição completa em `objections_library.json` → chave "começando do zero"):**
  > "Isso é ótimo, tá de verdade, porque a maioria das pessoas que chegam aqui para conversar comigo estão exatamente nesse ponto, começando do zero, ou têm pouca experiência com o digital. E as formas que ensino — Mercado Livre, Shopee, TikTok Shop — foram literalmente feitas pra quem está nesse momento. [...] Dá literalmente para construir um resultado real começando do zero."
- **Guard:** `comecando_do_zero_sent`; implementado via `_trigger_objection("comecando_do_zero", "", auto_motivation=True)`, que também dispara `ask_motivation` automaticamente e seta `follow_1_2_sent=True` no follow-up.
- **Trecho do prompt:** mesmo bloco do Passo 1c ("Se o lead disser que NÃO conhece / NUNCA fez / COMEÇOU DO ZERO → chame trigger_comecando_do_zero() PRIMEIRO, depois ask_motivation().").

### 3.4 `automacao_1`

- **Tool:** `trigger_automation_1()`
- **Webhook (v1):** `.../6f66525d-9033-4a61-ad94-0c8d7a78921b`
- **Docstring completa:**
  > "Trigger automation 1 — presentation content (audios/videos). Call this AFTER saving lead profile and completing qualification questions in Passo 2. The automation ends by asking if the lead has any doubts."
- **Trecho do prompt (Passo 3):**
  > "Após a qualificação e quando o lead der abertura → chame trigger_automation_1(). Essa automação vai enviar conteúdo de apresentação ao lead. A automação JÁ TERMINA com a pergunta 'ficou alguma dúvida?' — NÃO envie essa pergunta novamente [...]. ⚠️ REGRA CRÍTICA: O lead SÓ pode avançar para automação 2 quando CONFIRMAR que viu o conteúdo." (segue lista de sinais válidos: 'não', 'não ficou', 'entendi', 'tudo claro', 'ok', 'vi tudo', 'acabei de ver', 'maravilha', 'show', 'gostei').
- **Conteúdo enviado — roteiro completo reconstruído a partir de `data/phase2_sequence.json`** (17 itens sequenciais, texto + automação embutida, com `delay_seconds: 15` entre blocos de mídia):
  1. Texto: "Entendii, {nome}"
  2. Texto: "Vamos lá"
  3. Texto de posicionamento anti-golpe/pirâmide/aposta.
  4. Texto de credibilidade (3+ anos, alunos que saíram do CLT, quitaram dívidas etc.)
  5. Texto: "Boraaaaaa lá"
  6. **`audio_batch_1`** — áudios 1, 2 e 3
  7. Texto sobre ouvir em 2x
  8. **`audio_batch_2`** — áudios 4, 5 e 6
  9. Texto anunciando vídeo de saque de quase R$50 mil
  10. **`video_1`** — vídeo do saque de ~R$50 mil
  11. Texto: "Apenas no Mercado Livre, +R$14 mil no último mês [...]"
  12. **`video_2`** — vídeo do podcast Kiwify
  13. Texto: "'Van, isso realmente funciona?' [...] fiz mais de 2 milhões [...]"
  14. **`provas_sociais`** — 1 vídeo + 3 imagens de prova social
  15. Texto de humor ("Eu falo mesmo kkkk...")
  16. Texto final: "já foi bastante coisa até aqui né kkkk [...] até aqui você tem alguma dúvida? A maioria do pessoal [...] faz entre 3 a 6 mil reais no primeiro mês [...]"
  17. Texto: "Pode me mandar áudio também se quiser [...]"

  ⚠️ Observação: `phase2_sequence.json` parece ser o roteiro de referência/planejamento (possivelmente pré-implementação ou usado como texto de apoio), não necessariamente o que o webhook único `automacao_1` executa internamente no CRM — o código VFO só dispara UM webhook (`automacao_1`), e é o flow no DataCrazy que orquestra toda essa sequência internamente. Não foi possível confirmar 1:1 que este JSON reflete exatamente o flow ativo hoje no CRM.
- **Guards e efeitos colaterais:** bloqueia reenvio (`automation_1_sent` ou `fus` flag); cooldown de 60s após qualquer `send_text_message()` (para forçar o LLM a esperar resposta do lead antes de disparar); ao suceder, seta `content_seen=True`, `automation_1_sent=True`, `follow_1_4_sent=True` (bloqueia o scheduler de reenviar via `bf_labs_automacao1`), `funnel_phase=2`, e dorme 15s (`asyncio.sleep(15)`).
- **Observações de planos:** `plano-v10.md` e `plano-v11.md` documentam um bug real corrigido — "Houve um caso real onde: o agente pulou direto para perguntar se a pessoa viu ou tem dúvida sobre o curso, sem nunca ter enviado a automação 1" — que motivou a criação da flag `automation_1_sent` e da regra "NUNCA pergunte se o lead viu o conteúdo [...] SEMPRE que automation_1_sent for False".

### 3.5 `automacao_2`

- **Tool:** `trigger_automation_2()`
- **Webhook (v1):** `.../2e4c599d-1d0c-4579-848b-f50e2a18aff1`
- **Docstring completa:**
  > "Trigger automation 2 — value-building before presenting price. The automation itself includes the price (R$299,90). Use ONLY the first time presenting price, after automation 1 was sent. Do NOT re-trigger during price negotiation/objections."
- **Trecho do prompt (bloco "AUTOMAÇÃO 2 — AGREGAR VALOR NO PREÇO"):**
  > "A automação 2 serve para AGREGAR VALOR antes de falar o preço. A automação 2 já INCLUI o valor de R$299,90 (tier 1) no conteúdo enviado. [...] Pré-requisitos para acionar: 1. Lead respondeu perguntas iniciais de qualificação 2. Automação 1 já foi enviada 3. Lead perguntou sobre preço OU demonstrou interesse 4. Automação 2 ainda NÃO foi enviada 5. Vanessa perguntou se pode enviar material de valor E O LEAD DISSE SIM."
- **Conteúdo enviado:** conteúdo de "agregar valor" (entregáveis, transformação) que **já embute o preço R$299,90** — não há transcrição literal capturada; instrução do prompt confirma isso: "NUNCA envie o template no meio da automação 2".
- **Guards:** hard gate — bloqueia com `status: blocked` se `automation_1_sent==False`; bloqueia se já enviada; cooldown de 60s pós-texto; ao suceder, seta `automation_2_sent=True`, `funnel_phase=3`, dorme 15s, e a resposta da tool instrui explicitamente o LLM: "Do NOT wait for the lead to respond [...] Call send_payment_link(tier=1) RIGHT NOW" — ou seja, o próprio design espera que `send_payment_link(tier=1)` seja chamado na MESMA rodada, o que contradiz outra regra do prompt que diz "NUNCA envie send_payment_link() automaticamente após automação 2. AGUARDE o lead aceitar o preço explicitamente" (ver Seção 6 — Lacunas/inconsistências).
- **Observações de planos:** `plano-v11.md` documenta a mudança de propósito da automação 2, de "explicar como funciona o curso" para "agregar valor no momento do preço" — reposicionamento deliberado.

### 3.6 As 11 automações de objeção por áudio (+ `comecando_do_zero` e `preciso_pagar` e `vai_ver`)

Documentadas em bloco único no prompt: **"AUTOMAÇÕES DE OBJEÇÃO POR ÁUDIO — use quando o lead mencionar uma situação específica"**, com a lista numerada de 1 a 14 (12 originais do `plano-v25.md` + `comecando_do_zero` reaproveitado + `vai_ver` adicionado depois). Regras comuns:
> "Cada automação envia um áudio da Vanessa. Após o áudio, envie UMA pergunta com CTA via send_text_message(). ⚠️ Cada automação pode ser usada APENAS 1 vez por lead. Se a mesma objeção surgir de novo, responda por texto. ⚠️ Após o CTA, AGUARDE a resposta. NÃO dispare outra automação na mesma rodada."

Todas compartilham a mesma implementação (`_trigger_objection(key, cta)`), que: verifica flag `{key}_sent`, dispara `automation.trigger_automation(key, ...)`, seta `{key}_sent=True` em `ctx` e em `fus`, dorme 10s, opcionalmente envia o `cta` (texto pós-áudio) e atualiza cooldown.

| Automação | Webhook (v1, sufixo) | Docstring | Transcrição (fonte) |
|---|---|---|---|
| `precisa_computador` | `084e4d12-...` | "Trigger audio: lead asks if they need a COMPUTER or CELLPHONE to work. ⚠️ NÃO use para perguntas sobre investimento [...]" | `objections_library.json` → "precisa de computador": *"Não, você não precisa de computador [...] até hoje uso mais o celular [...]"* |
| `tempo_resultados` | `57a7248c-...` | "Trigger audio: lead asks how long to get results." | `objections_library.json` → "tempo de resultados": *"[...] tem alunos tendo resultados antes de 24 horas [...] tive meu primeiro resultado com 13 dias e com 1 mês fiz R$3.200 [...]"* |
| `tempo_livre` | `a68e414a-...` | "Trigger audio: lead says they have little free time." | `objections_library.json` → "tempo livre": *"Se você tiver 30 minutinhos livres [...]"* |
| `experiencias_ruins` | `120a4997-...` | "Trigger audio: lead had bad experiences with courses before." | `objections_library.json` → "experiencias ruins": *"Olha, eu realmente sinto muito [...]"* |
| `tem_medo` | `63e23841-...` | "Trigger audio: lead says they are afraid or insecure." | `objections_library.json` → "tenho medo": *"Eu te entendo de verdade [...] medo não paga boleto!"* |
| `tem_profissao` | `7948a57b-...` | "Trigger audio: lead mentions they already have a profession." | `objections_library.json` → "e profissional": *"Que legal! Tenho várias alunas dessa área [...]"* |
| `outro_pais` | `93fd27a5-...` | "Trigger audio: lead says they live outside Brazil." | `objections_library.json` → "outro pais": *"Que bacana! Tenho várias alunas de outros países [...]"* |
| `e_mae` | `412829fe-...` | "Trigger audio: lead says they are a mother." | `objections_library.json` → "e mae": *"Nossa, que bacana que você é mãe! [...]"* |
| `faz_faculdade` | `922d5316-...` | "Trigger audio: lead says they are in college." | `objections_library.json` → "faz faculdade": *"Que bacana! Tenho várias alunas acadêmicas [...]"* |
| `e_crista` | `68c285d8-...` | "Trigger audio: lead says they are Christian." | `objections_library.json` → "e crista": *"Que bom que você também é cristã! [...]"* |
| `como_sei_seguro` | `75301320-...` | "Trigger audio: lead asks if it's safe or trustworthy." | `objections_library.json` → "seguro": *"Eu tinha muito esse medo também. [...] Instagram [...] podcast [...]"* |
| `preciso_pagar` | `3366ea11-...` | "Trigger audio: lead asks if they need to INVEST MONEY in tools, ads, or products. Use when lead says 'investir', 'pagar para começar', 'gastar dinheiro', 'preciso de dinheiro'. ⚠️ NÃO use para perguntas sobre computador/celular [...]" | `objections_library.json` → "preciso pagar": *"As estratégias que eu ensino [...] são gratuitas [...] O único investimento [...] é no seu conhecimento [...]"* |
| `vai_ver` | `952b08e7-...` | "Trigger audio: lead says they haven't seen the content yet but will see it." | `objections_library.json` → "vai ver": *"Tranquilo, {nome}! Mas olha, o conteúdo é bem curtinho [...]"* |

Notas específicas:
- `trigger_precisa_computador` e `trigger_preciso_pagar` têm um aviso explícito de anti-confusão nos dois lugares (docstring e prompt), porque tratam de coisas semanticamente próximas ("computador" vs "dinheiro/investimento") e historicamente eram fáceis de confundir.
- `trigger_vai_ver()` é a ÚNICA automação de objeção que **não recebe parâmetro `cta`** — a docstring registra que "a automação já envia o áudio e o CTA automaticamente" (comportamento distinto das outras 12, que dependem do LLM escrever o `cta`).
- O `plano-v25.md` é o documento de design original dessas 11 (+ comecando_do_zero + preciso_pagar) automações, com tabela de gatilho→webhook e o detalhamento das transcrições, servindo de base para o que hoje está implementado em código e prompt.

### 3.7 `pos_pagamento`

- **Não é uma tool própria** — é disparada dentro do corpo de `send_payment_link(tier)` e `send_challenge_link()`, logo após o texto do link de pagamento ser enviado.
- **Webhook (v1):** `.../63ce8a6f-1153-4f32-8a22-5f53349e66b3`
- **Comentário no código:** `# Trigger pós-pagamento automation (upsells, acesso vitalício, etc.)`.
- **Não há flag de controle** — é sempre disparada quando um link (payment ou challenge) é enviado, mesmo antes de o lead efetivamente pagar. É best-effort (falha logada como warning, não propaga erro).
- **Conteúdo enviado:** não documentado em nenhum JSON ou plano — apenas a menção genérica "upsells, acesso vitalício, etc." no comentário do código.

### 3.8 Automações exclusivas do `follow_up_scheduler.py` (`bf_labs_*`)

Estas 9 chaves não são acionáveis pelo LLM em conversa — são disparadas apenas pelo loop de background `follow_up_scheduler_loop()`, controlado pelos templates em `data/follow_up_templates.json` (produção) — havia também um `follow_up_templates_v1.json` mais simples (4 steps, sem separação em fluxos, aparentemente uma versão anterior/legada). Fluxo determinado por `_determine_flow(state)`:

```
automation_2_sent == True  → Fluxo 3 (pós-preço)
automation_1_sent == True  → Fluxo 2 (pós-apresentação, pré-preço)
caso contrário              → Fluxo 1 (pré-qualificação)
```

**Fluxo 1** (pré-automação 1) — intervalos de produção: 30min / 1h / 2h / 5h:
| Step | Automação | Texto próprio | Observação |
|---|---|---|---|
| 1 | `bf_labs_audio_inicial` | — | Só dispara se `automation_1_sent`/`experiencia_sent`/`follow_1_1_sent` ainda False |
| 2 | (nenhuma — só texto) | "Fiquei na dúvida se você tá começando do zero ou já tem uma noção..." | — |
| 3 | `bf_labs_follow3_pt1` | — | — |
| 4 | `bf_labs_automacao1` | "Como estou livre agora, Vou te explicando aqui [...]" | Só dispara automação se `automation_1_sent==False` (código zera o campo `automation` do template se já enviada — linha 244-246 do scheduler) |

**Fluxo 2** (pós-automação 1, pré-automação 2) — intervalos: 30min / 2h / 4h:
| Step | Automação | Texto próprio |
|---|---|---|
| 1 | — | "Oieee, Tô quase mandando mensagem pra mim mesma [...]" |
| 2 | `bf_labs_follow2_pt2` | — |
| 3 | `bf_labs_follow3_pt2` | — |

**Fluxo 3** (pós-automação 2) — intervalos: 20min / 2h / 3h:
| Step | Automação | Observação |
|---|---|---|
| 1 | `bf_labs_follow1_pt3` | — |
| 2 | `bf_labs_follow2_pt3` | — |
| 3 | `bf_labs_follow3_pt3` | `handle_response: true, response_price: 299.9` — nota no JSON: "Se lead responder com interesse após este follow, enviar link de pagamento R$299,90" (não há código explícito que implemente esse handler; parece ser instrução operacional, não automação de código) |

**Janela 24h** (especial, fora dos 3 fluxos): `bf_labs_follow_janela_24h` — dispara entre 82.800s e 86.400s (23h–24h) após `lead_first_contact_at`, condicionado a `is_purchased==False`. Nota no JSON: *"Follow-up de janela 24h — enviado 23h após primeiro contato, 1h antes de fechar a janela do WhatsApp Business API. Lead é informada que foi sorteada com bônus + link de pagamento."*

**`_INTERVALS_TEST`** (código morto/dormente): existe um segundo dicionário de intervalos em segundos muito mais curtos (5-11min) para testes, mas `_ACTIVE_INTERVALS = _INTERVALS` está fixado em produção — o modo de teste não está ativo, só disponível trocando a atribuição manualmente no código.

---

## 4. Máquina de estados do funil

```
[Qualificação]
   send_intro() → nome salvo (set_lead_info) → trigger_experiencia() (pergunta_experiencia)
        ↓
   lead responde:
     "já fez mentoria/curso"   → trigger_mentoria() (ja_fez_mentoria) ─┐
     "começando do zero"        → trigger_comecando_do_zero()          ├→ ask_motivation()
     resposta vaga               → re-perguntar (sem disparar automação)┘
        ↓ (lead responde motivação)
   "posso te mandar áudios e vídeos?" → lead diz sim
        ↓
[Apresentação]
   trigger_automation_1() (automacao_1) → "ficou alguma dúvida?"
        ↓ (lead confirma que viu / sem dúvidas)
[Preço — 1ª vez]
   "posso te mandar material que mostra tudo incluso?" → lead diz sim
        ↓
   trigger_automation_2() (automacao_2) → já mostra preço R$299,90 (tier 1)
        ↓
   lead aceita ─────────────────────────→ send_payment_link(tier=1) → pos_pagamento (auto)
   lead acha caro → valida dor → pergunta budget → present_price(tier 2/3/4)
        ↓                                                  ↓
   lead aceita tier → send_payment_link(tier)          budget < R$179 → oferece Desafio R$47
        ↓                                                  ↓
        └──────────────→ send_payment_link/send_challenge_link → pos_pagamento (auto)
        ↓
[Pós-compra]
   mensagem fixa de parabéns + link de suporte humano (hardcoded no prompt, não é automação DataCrazy)

[Caso especial]
   Lead já comprou "Your Boss" → send_cakto_link() (link estático, sem trigger_automation)

[Objeções — podem interromper em qualquer ponto do funil, 1x cada]
   precisa_computador / tempo_resultados / tempo_livre / experiencias_ruins / tem_medo /
   tem_profissao / outro_pais / e_mae / faz_faculdade / e_crista / como_sei_seguro /
   preciso_pagar / vai_ver → áudio + CTA (exceto vai_ver, que já inclui CTA)

[Reengajamento assíncrono — follow_up_scheduler, roda em paralelo à conversa]
   Fluxo 1 (pré-aut.1) → Fluxo 2 (pós-aut.1) → Fluxo 3 (pós-aut.2) → expira
   + Janela 24h (independente dos fluxos, ~23h após primeiro contato)
```

A `funnel_phase` no `SessionContext` é um contador auxiliar (0→1→2→3→4→6) atualizado em pontos-chave (`set_lead_info` com nome → fase 1; `trigger_automation_1` → fase 2; `trigger_automation_2` → fase 3; `present_price` → fase 4; `send_payment_link`/`send_challenge_link` → fase 6 — não há fase 5 explícita em nenhum lugar lido, possível lacuna de numeração).

O `plano-v10.md`/`plano-v11.md` documentam a introdução deliberada da flag `content_seen` e da regra "preço só depois de `automation_1_sent==True`" para corrigir um bug real de pular etapas do funil.

---

## 5. Histórico de mudanças relevante

O repositório anterior só tinha **2 commits** no histórico Git (`71454aaaa chore: initial commit — full VPS workspace snapshot` e `690ee8744 chore: clean VPS snapshot`), ambos de importação de snapshot — não há histórico granular de commits por feature. A evolução real do sistema de automações precisa ser reconstruída a partir dos documentos de planejamento em `plano-melhorias/`, que parecem ter servido como "specs" antes da implementação:

1. **`implementação-follow-up.md`** — proposta original do sistema de follow-up (estratégia "1d4x": 4 mensagens em 24h). Definia intervalos de teste (10-40s) e produção (15min-4h) — os intervalos de produção reais implementados hoje (`_INTERVALS` em `follow_up_scheduler.py`) são mais longos e diferenciados por fluxo (30min-5h), então o desenho evoluiu além da proposta original de "4 toques únicos" para "3 fluxos com contagens distintas".
2. **`plano-v10.md`** — identifica bug: prompt forçava 3 perguntas de qualificação textuais antes de acionar automação; e um caso real de a IA pular direto para "tem dúvida sobre o curso" sem nunca ter enviado a automação 1. Motivou a flag `content_seen` e a regra de bloqueio de preço antecipado.
3. **`plano-v11.md`** — evolução do v10: introduz `automation_1_sent` (rastreamento definitivo, code snippet incluído), regra de posicionamento "capacitação" vs "curso", redefine o PROPÓSITO da automação 2 (de "explicar como funciona" para "agregar valor no momento do preço") e introduz `automation_2_sent` com hard-gate. Essas mudanças estão hoje refletidas fielmente em `context.py`, `tools/vanessa.py` e `prompts/vanessa.py`.
4. **`plano-v25.md`** — desenho original das 11 automações de objeção por áudio (mais `comecando_do_zero` e `preciso_pagar`), com tabela gatilho→webhook e transcrições completas. Hoje implementado quase 1:1 (as mesmas 13 automações mais `vai_ver`, que não aparece no v25 mas está no código e no prompt — adição posterior não documentada em plano específico encontrado).
5. **`plano-tracking-pagamento.md`** — desenho do rastreamento de pagamento (tabela `payment_links`, links dinâmicos com UTM+src, webhooks Kiwify/Cakto). Todos os itens marcados como concluídos (`[x]`). Nota: este plano referencia links **Kiwify** com 5 tiers (R$399/299/249/199/179) mas o código atual (`tools/vanessa.py`) usa **Applyfy** (`_APPLYFY_BASE`) com 4 tiers (R$299,90/249,90/199,90/179,90) — indica migração de checkout que não foi documentada em um plano dedicado encontrado neste levantamento (ver Seção 6).
6. **`implementação-follow-up2.md`** (30KB, o mais extenso) — desenho detalhado do sistema de 3 fluxos + janela 24h que está implementado hoje; documenta explicitamente que `bf_labs_audio_inicial` e `bf_labs_automacao1` são aliases reaproveitando webhooks existentes; e traz uma tabela de riscos conhecidos, incluindo "Aut.1 duplicada (follow + agente) → Lead recebe conteúdo repetido — mitigado por anti-duplicação checando `automation_1_sent`" e "Webhook DataCrazy falha → Follow não entregue — mitigado por log de erro + retry no próximo poll (5s)" (nota: não há retry real implementado no código lido — o "retry" é apenas o próximo ciclo do loop de 5s tentar novamente do zero, não um retry com backoff dedicado).
7. **`report_datacrazy_errors_05062026.md`** — bug documentado e reportado à DataCrazy (05/06/2026): erro `Invalid character in header content ["message"]` em mensagens contendo emojis, reticências tipográficas, asteriscos ou quebras de linha, causado (segundo a hipótese do relatório) por o CRM colocar o conteúdo da mensagem em um header HTTP em vez do body, nas **automações internas disparadas via webhook** (não na API REST usada por `send_text_message`). Este relatório é provavelmente a origem direta do bloco de regras "ENCODING E CARACTERES ESPECIAIS" no final do `prompts/vanessa.py` (proibindo aspas tipográficas, travessão, reticências tipográficas, emojis fora de ✨😊🚀) e da função `_sanitize_text()` em `datacrazy_automation.py` que tenta corrigir mojibake antes de enviar.

---

## 6. Lacunas / observações

1. **Contradição entre automação 2 e regra de espera do lead.** A tool `trigger_automation_2()` retorna explicitamente `"Do NOT wait for the lead to respond. [...] Call send_payment_link(tier=1) RIGHT NOW"`, mas o bloco de prompt "REGRA DE ESPERAR RESPOSTA" e o bloco "AUTOMAÇÃO 2" dizem "NUNCA envie send_payment_link() automaticamente após automação 2. AGUARDE o lead aceitar o preço explicitamente" / "send_payment_link() SÓ é chamado quando o lead EXPLICITAMENTE ACEITA o preço". Há uma instrução de nível de tool dizendo para agir imediatamente e uma instrução de nível de prompt dizendo para esperar — comportamento ambíguo que pode causar tanto envio prematuro do link quanto travamento indevido, dependendo de qual instrução o LLM prioriza.

2. **Divergência entre `tools/vanessa.py` e `plano-tracking-pagamento.md` sobre checkout/tiers.** O plano documenta links Kiwify com 5 tiers (R$399→179). O código implementado usa Applyfy com 4 tiers (R$299,90→179,90) mais o Desafio via Cakto (R$47). Não há um plano dedicado documentando essa migração — pode ser uma decisão tomada fora dos `plano-melhorias/` lidos, ou o plano está desatualizado em relação ao código.

3. **`preciso_pagar` vs nomenclatura de flag.** No dicionário de automações e na tool, a chave é `preciso_pagar`; a flag de sessão associada em `context.py`/`agent_factory.py` é `preciso_pagar_sent` (consistente). Já a entrada equivalente em `objections_library.json` usa a chave textual "preciso pagar" (com espaço) — apenas uma questão de nomenclatura entre arquivos, sem impacto funcional, mas pode confundir quem for dar manutenção nesse mapeamento.

4. **`pos_pagamento` sem transcrição/documentação de conteúdo.** Diferente das demais automações, não há nenhum JSON, plano ou comentário que descreva o que de fato é enviado nessa automação pós-venda — apenas "upsells, acesso vitalício, etc." Recomenda-se auditar diretamente no painel do DataCrazy.

5. **`bf_labs_follow3_pt1`, `bf_labs_follow2_pt2`, `bf_labs_follow3_pt2`, `bf_labs_follow1_pt3`, `bf_labs_follow2_pt3`, `bf_labs_follow3_pt3`** — nenhuma dessas 6 automações do scheduler tem conteúdo documentado em nenhum arquivo do repositório (nem transcrição, nem descrição além do nome). Só existem como chaves de webhook + posição no fluxo. Marcado explicitamente como "não encontrado no código/dados" — para saber o que enviam, é preciso consultar o CRM DataCrazy diretamente.

6. **`follow_up_templates_v1.json` é código morto (ou legado)?** Existe um arquivo de templates mais simples (4 steps lineares, sem separação em 3 fluxos, automações chamadas `follow_up_video_prova_social` e `follow_up_foto_historia` que **não aparecem** no dicionário `AUTOMATION_WEBHOOKS` atual). O `follow_up_scheduler.py` carrega apenas `follow_up_templates.json` (produção atual) — o `_v1.json` parece ser a versão anterior mantida apenas como histórico/backup, mas isso não é comentado explicitamente em lugar nenhum do código.

7. **`_INTERVALS_TEST` no scheduler é código morto em produção** — existe mas não está ativo (`_ACTIVE_INTERVALS = _INTERVALS`). Se alguém trocar manualmente para testes e esquecer de reverter, o comportamento de produção mudaria silenciosamente para intervalos de minutos em vez de horas.

8. **`funnel_phase` pula a fase 5.** As fases usadas no código são 0,1,2,3,4,6 — não há um "5" em nenhum lugar. Pode ser resquício de uma versão anterior do funil (talvez removida ao consolidar `present_price` + `send_payment_link`) ou apenas um placeholder não utilizado — não há dano funcional aparente, mas é uma inconsistência de nomenclatura.

9. **`step 3` do Fluxo 3 do scheduler tem `handle_response: true` e `response_price: 299.9`, mas não há código que implemente esse "handle_response".** O JSON documenta a intenção ("se lead responder com interesse [...] enviar link de pagamento R$299,90"), mas essa lógica não está implementada em `follow_up_scheduler.py` nem em `tools/vanessa.py` — a resposta do lead a esse follow-up cai no fluxo normal da conversa (o Agno agent processa a mensagem recebida como qualquer outra, sem tratamento especial ligado a esse campo). Trata-se de uma intenção de design documentada mas não codificada — gap real entre spec e implementação.

10. **Retry declarado no plano de follow-up, mas não implementado como retry dedicado.** O plano `implementação-follow-up2.md` menciona "retry no próximo poll (5s)" como mitigação a falha de webhook — na prática, o código não tem lógica de retry: se o `trigger_automation()` falhar, a exceção é apenas logada (`logger.warning`) e a automação NÃO é re-tentada automaticamente no próximo ciclo, porque a flag de "já tentado" não existe separada da flag de "sucesso" — ou seja, se o flag correspondente não foi setado (porque falhou), o próximo ciclo do scheduler VAI tentar de novo (isso sim ocorre, pela lógica de "flag ainda False → elegível"), então o comportamento real cumpre a intenção, mas não é um "retry com backoff" — é apenas reavaliação do próximo poll do loop principal, que roda a cada 5s independentemente de sucesso/erro anterior.

11. **`report_datacrazy_errors_05062026.md` não confirma se o bug foi corrigido.** O relatório termina com uma solicitação para a DataCrazy investigar; não há um documento de acompanhamento no repositório confirmando resolução. As regras de encoding no prompt (`ENCODING E CARACTERES ESPECIAIS`) e a função `_sanitize_text()` no código parecem ser MITIGAÇÕES do lado VFO (evitar caracteres problemáticos na origem), não uma confirmação de correção no lado DataCrazy — o problema pode persistir se automações internas do CRM (não controladas pelo VFO) ainda gerarem texto com esses caracteres.

12. **Nenhuma automação no CRM foi detectada como "órfã"** (webhook definido no código mas nunca referenciado por nenhuma tool nem pelo scheduler) — todas as 27 chaves do dicionário `AUTOMATION_WEBHOOKS` têm pelo menos um ponto de disparo identificado no código (tool do LLM, template do scheduler, ou disparo automático pós-pagamento). Não foi possível, por outro lado, confirmar a via inversa (se existem automações configuradas no CRM DataCrazy que NÃO têm webhook mapeado no código) — isso exigiria acesso direto ao painel do DataCrazy, fora do escopo desta pesquisa de código.
