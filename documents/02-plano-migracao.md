# Plano de Migração — VFO (Vanessa)
### Documento único e definitivo — do planejamento ao corte final em produção

**Gerado em:** 2026-07-14 · **Revisado (versão definitiva):** 2026-07-14
**Status:** aprovado para execução — Fase A liberada para início imediato
**Escopo:** (1) migração de banco SQLite → Postgres compartilhado; (2) migração de mensageria API DataCrazy → API oficial WhatsApp Cloud (Meta Tech Provider)
**Fora de escopo:** qualquer mudança de regra de negócio do funil de vendas além da correção pontual já identificada na auditoria (Seção 8.3); rebranding ou reposicionamento de produto; migração de outros agentes do portfólio.

**Documentos de apoio (não substituídos por este plano, apenas referenciados):**
- `01-automations-mapping.md` — as 27 automações mapeadas (gatilho, conteúdo, guardas)
- `02.1-slides-migracao-api-oficial.md` — deck já apresentado ao stakeholder (entrega de status em 16/07/2026, **já cumprida** — não é mais um bloqueador deste plano)
- `03-whatsapp-waba-multinumber-setup.md` — guia técnico oficial de webhook multi-número (Meta docs)

---

## 1. Sumário executivo

O VFO ("Vanessa") é hoje o único agente do portfólio que depende de um CRM terceiro (DataCrazy) tanto para banco de sessão (SQLite local) quanto para envio de mensagem (API do CRM, com bug de encoding documentado e sem retry real). Este plano cobre a migração completa para o mesmo padrão de infraestrutura que outros agentes do portfólio já operam em produção: **Postgres compartilhado** + **API oficial do WhatsApp (Meta Cloud API)**, mantendo os números de telefone, a conexão do DataCrazy para dados de CRM, e as 27 automações de venda exatamente como mapeadas — só muda o transporte técnico.

**Decisões fechadas nesta versão do plano** (substituem qualquer suposição de rascunhos anteriores):

| Decisão | Escolha |
|---|---|
| Ordem de execução | Fase A (banco) completa e validada → só depois Fase B (mensageria) |
| Nomenclatura do banco | 1 banco `agno_vfo`, 2 schemas (`vanessa1`, `vanessa2`) |
| Credencial Postgres | Reusa a role compartilhada `bf_database` — **sem alterar a credencial em si** |
| Arquitetura de webhook | Testar Opção A (webhook único) e Opção B (override de callback) em ambiente controlado; decidir empiricamente |
| Ambiente de teste da Fase B | Número de teste/sandbox da Meta **antes** de tocar os números de produção |
| Estratégia de corte (Fase B) | **Corte total (big bang)** — os dois números migram no mesmo instante, após validação completa em sandbox |
| Rollback | **Manual** — Bruno decide, com o caminho antigo mantido pronto e documentado até confirmação de estabilidade |
| Responsabilidade por tarefas manuais | Bruno executa o que exige acesso humano (painel DataCrazy, Meta Business Manager, aprovação de cutover); eu executo código, banco, testes e deploy |
| Prazo do stakeholder (16/07) | Já cumprido pela apresentação — **não é mais um bloqueador** deste plano; as duas fases seguem em ritmo de qualidade, sem pressa artificial |
| Prazo de cancelamento do DataCrazy | Nenhum definido ainda — prioridade alta de qualquer forma, sem deadline rígido |

---

## 2. Papéis e responsabilidades

| Tarefa | Quem executa |
|---|---|
| Escrever/adaptar código (waba_client, tools, ETL, testes) | Eu |
| Criar banco/schemas Postgres, rodar migração, rodar suite de TDD | Eu |
| Configurar systemd, deploy, restart de serviços | Eu |
| Baixar mídia (áudio/vídeo/imagem) do painel DataCrazy | **Bruno** |
| Provisionar número de teste + credenciais WABA no Meta Business Manager (Tech Provider) | **Bruno** |
| Provisionar credenciais WABA de produção (2 números) | **Bruno** |
| Decidir e executar rollback, se necessário | **Bruno** |
| Aprovar o corte final de produção (Fase B) | **Bruno** |

Cada item de checklist abaixo está marcado com **[Bruno]** ou **[Eu]** para deixar isso explícito tarefa a tarefa.

---

## 3. Inventário do estado atual

### 3.1 Bancos SQLite em produção

| Arquivo | Tamanho | Status |
|---|---|---|
| `instances/vanessa-1/data/vanessa.db` | 28.9 MB | Produção — 102 sessões ativas |
| `instances/vanessa-2/data/vanessa.db` | 9.0 MB | Produção — 35 sessões ativas |
| `data/sessions.db`, `data/vfo_sessions.db` | 0 bytes | Legado/não usado — não migrar |

### 3.2 Tabelas por banco (schema idêntico entre v1 e v2)

| Tabela | Origem | Linhas (v1/v2) | Observação |
|---|---|---|---|
| `agno_sessions` | Framework Agno (`SqliteDb`) | 102 / 35 | PK `session_id`; blobs JSON (`session_data`, `agent_data`, `runs`, `summary`, `metadata`) |
| `agno_schema_versions` | Framework Agno | 1 / 1 | Controle interno de migração do Agno |
| `follow_up_state` | `app/follow_up_state.py` | 104 / 40 | ~25 flags de sequenciamento (automation_1/2_sent, follow_1_x…3_x, is_purchased, paused, lead_name) |
| `payment_links` | `app/transaction_log.py` | 2 / 4 | Rastreamento de PIX/checkout (paid, order_id, amount) |
| `llm_usage_log` | `app/llm_usage_log.py` | 565 / 208 | Custo/latência/tokens por sessão |
| `agent_transactions` | `app/transaction_log.py` | 579 / 223 | Log completo de request/response/eventos |
| `tool_errors` | `app/error_log.py` | 0 / 0 | Vazia até hoje |

Volume pequeno (máx. ~600 linhas/tabela) — migração em lote único, sem necessidade de sync incremental.

⚠️ `log_store.py` não tem tabela própria hoje — **[Eu]** confirmar durante a implementação se deve ganhar persistência em Postgres (o equivalente em outros agentes persiste).

### 3.3 Padrão de referência (outros agentes do portfólio, já validado em produção)

- 1 connection string por agente, formato `postgresql://bf_database:<senha>@localhost/agno_<nome>`.
- Usuário compartilhado `bf_database` — role usado por 9+ serviços. **Não será alterado.**
- Schema Postgres fixado em `"public"` (Agno usa `"ai"` por padrão) — mesmo padrão será seguido, adaptado para os schemas `vanessa1`/`vanessa2`.
- Nenhum dos dois agentes persiste mídia local — mídia de entrada vem direto da URL da Meta; `PUBLIC_BASE_URL` só serve mídia gerada dinamicamente.
- Webhook único por App, roteamento por `phone_number_id` (confirmado no próprio código de produção).

### 3.4 Mídia — 100% no CRM, nada local

`find` por mp3/mp4/ogg/wav/jpg/png no repositório retornou zero arquivos. Todo o conteúdo das 27 automações vive hoje só dentro do painel DataCrazy. **Maior risco do projeto** — ver Seção 9.1.

---

## 4. Fase 0 — Preparação (antes de qualquer migração)

- [ ] **[Bruno]** Confirmar acesso ativo ao painel DataCrazy (login, permissões de export de mídia).
- [ ] **[Bruno]** Confirmar acesso à conta Meta Business Manager como Tech Provider (permissões para criar App/número de teste).
- [ ] **[Eu]** Fazer dump completo dos 2 SQLite (`sqlite3 vanessa.db .dump > backup.sql`) e guardar fora do repositório, como rede de segurança antes de qualquer alteração.
- [ ] **[Eu]** Confirmar com o time (mensagem simples, não é uma etapa longa) antes de criar o banco novo sob a credencial compartilhada `bf_database` — só criação de banco, nunca alteração da credencial.

**Critério de saída da Fase 0:** os dois acessos confirmados e o backup do SQLite feito.

---

## 5. Fase A — Migração de banco (SQLite → Postgres), com TDD

### 5.1 Criação da infraestrutura

- [ ] **[Eu]** Criar o banco `agno_vfo` no Postgres compartilhado, sob a credencial `bf_database` existente.
- [ ] **[Eu]** Criar os schemas `vanessa1` e `vanessa2` dentro dele.
- [ ] **[Eu]** Gerar `VFO_DATABASE_URL` (uma por instância, mesma role, schema diferente na connection string) e adicionar aos `.env` de cada instância — sem ainda apontar produção para lá.

### 5.2 Estrutura de tabelas

- `agno_sessions` + `agno_schema_versions`: criadas automaticamente pelo Agno ao apontar `PostgresDb(db_schema="vanessa1"/"vanessa2")` — sem DDL manual.
- 5 tabelas customizadas (`follow_up_state`, `payment_links`, `llm_usage_log`, `agent_transactions`, `tool_errors`) — **[Eu]** escrever `CREATE TABLE` manual em Postgres, espelhando o schema SQLite (tipos adaptados: booleano `INTEGER`→`BOOLEAN`, JSON texto→`JSONB` onde fizer sentido).
- Decidir e, se aplicável, criar tabela para `log_store.py` (item em aberto da Seção 3.2).

### 5.3 Script de ETL

- [ ] **[Eu]** Escrever script único de migração: lê cada tabela SQLite de origem, escreve na tabela Postgres/schema equivalente, preservando `session_id` como chave de ligação entre `agno_sessions` e `follow_up_state` — é o relacionamento mais crítico; se quebrar, o funil perde o estado de todo lead em conversa.
- [ ] **[Eu]** Rodar em modo dry-run primeiro (contagem de linhas origem vs. destino, sem gravar nada).
- [ ] **[Eu]** Rodar a migração real, uma instância por vez — vanessa-1 primeiro, validar com a suite de testes (Seção 5.4), só depois vanessa-2.

### 5.4 Suite de testes TDD (critério de aceite da Fase A)

Pytest, mesmo padrão de referência usado na migração equivalente já realizada:

1. **Paridade de contagem** — `COUNT(*)` por tabela, SQLite origem == Postgres destino.
2. **Integridade referencial** — todo `session_id` em `follow_up_state` existe em `agno_sessions` no destino, e vice-versa.
3. **Amostra de conteúdo** — N sessões aleatórias comparadas campo a campo, incluindo os JSON blobs de `session_data`, byte a byte após parse.
4. **Flags de negócio** — validar que `automation_1_sent`, `automation_2_sent`, `is_purchased`, `follow_up_expired` migraram com o valor correto (são os que, se corrompidos, quebram a régua de vendas).
5. **Leitura via Agno** — instanciar `Agent` com `PostgresDb` apontando pro schema migrado, `agent.get_session(session_id)` retorna os dados esperados para uma sessão conhecida — valida que o framework consegue *ler* o que foi migrado, não só que o dado bruto está lá.
6. **Cold start** — criar sessão nova (lead novo) em Postgres do zero, sem depender de dado pré-existente, e confirmar que funciona igual ao SQLite.

- [ ] **[Eu]** Escrever e rodar os 6 grupos de teste acima para vanessa-1.
- [ ] **[Eu]** Escrever e rodar os 6 grupos de teste acima para vanessa-2.
- [ ] **[Eu]** Suite 100% verde nas duas instâncias antes de prosseguir.

### 5.5 Corte de produção (Fase A)

- [ ] **[Eu]** Trocar `.env` de produção de `SESSION_DB_PATH` (SQLite) para `VFO_DATABASE_URL` (Postgres), uma instância por vez.
- [ ] **[Eu]** Reiniciar `vfo-agent.service`, validar logs (mesma contagem de sessões ativas — 102 — e follow_up_scheduler rodando normalmente).
- [ ] **[Eu]** Repetir para `vfo-agent-2.service` (35 sessões).
- [ ] **[Eu]** Observar em produção por pelo menos 24h sem erro antes de considerar a Fase A encerrada.

### 5.6 Critério de conclusão da Fase A

- [ ] Suite de TDD 100% verde para as duas instâncias.
- [ ] 24h de produção estável em Postgres, sessões ativas condizentes com o volume anterior.
- [ ] Backup do SQLite preservado por no mínimo 7 dias de operação estável (não apagar antes disso).

---

## 6. Fase B — Migração de mensageria (API DataCrazy → API oficial Meta)

Só inicia depois da Fase A concluída (Seção 5.6).

### 6.1 Bloqueadores a resolver antes de escrever qualquer código de integração

- [ ] **[Bruno]** Baixar do painel DataCrazy o conteúdo (áudio/vídeo/imagem) das 27 automações mapeadas em `01-automations-mapping.md` — prioridade máxima nas **6 automações do scheduler sem conteúdo documentado em lugar nenhum** (`bf_labs_follow3_pt1`, `bf_labs_follow2_pt2`, `bf_labs_follow3_pt2`, `bf_labs_follow1_pt3`, `bf_labs_follow2_pt3`, `bf_labs_follow3_pt3`) e no `pos_pagamento` (conteúdo pós-venda sem transcrição).
- [ ] **[Bruno]** Organizar os arquivos baixados em estrutura previsível (`media/<automation_key>/audio.ogg`, `.../video.mp4` etc.) para eu consumir no upload via API.
- [ ] **[Eu]** Validar cada arquivo recebido contra a transcrição já capturada em `objections_library.json`/`phase2_sequence.json`, onde existir, para conferir que é o áudio certo.
- [ ] **[Bruno]** Provisionar **número de teste/sandbox** da Meta (grátis, via App Dashboard) para toda a validação inicial.
- [ ] **[Bruno]** Provisionar credenciais WABA de teste: `WABA_PHONE_NUMBER_ID`, `WABA_ACCESS_TOKEN`, `WABA_APP_SECRET`, `WABA_BUSINESS_ACCOUNT_ID` (o `WABA_WEBHOOK_VERIFY_TOKEN` eu gero, é uma string arbitrária).

### 6.2 Validação em sandbox — arquitetura de webhook (Opção A vs. B)

Correção definitiva em relação a suposições anteriores: a Meta não permite múltiplos webhooks arbitrários por App — existe **uma Callback URL padrão por App** (Opção A), e um mecanismo específico de **override** por WABA ou por número para isolamento físico (Opção B). Ver `03-whatsapp-waba-multinumber-setup.md` para a referência completa.

| | **Opção A — webhook único** | **Opção B — override de callback** |
|---|---|---|
| Setup | 1 Callback URL no App Dashboard, ambos números inscritos, roteamento interno por `phone_number_id` | Chamada extra de API (`POST /<WABA_ID ou PHONE_NUMBER_ID>/subscribed_apps` com `override_callback_uri`) por número/WABA |
| Isolamento de blast-radius | Só na camada de processamento (2 serviços/portas separados por dentro) | Também na ingestão — cada número bate fisicamente numa URL diferente |
| Recomendação da doc oficial | Padrão recomendado para "1 App, 1 cliente, N números" | Só quando há razão operacional concreta |

**Testes no número de sandbox (ambos os caminhos, antes de decidir):**

- [ ] **[Eu]** Implementar Opção A: 1 Callback URL, dispatch interno por `phone_number_id` (`ROUTING_MAP`), validar E2E — mensagem em cada número processada pela instância certa, sem cruzamento de sessão.
- [ ] **[Eu]** Implementar Opção B: override de callback no nível de número (B2, mais granular), apontando cada número para a porta/processo já existente (8004/8005), validar o mesmo E2E.
- [ ] **[Eu]** Teste de carga simulada: rajada concentrada num número só, medir se o outro sofre degradação de latência/enfileiramento em cada abordagem — critério direto para o cenário de pico do cliente de 160k seguidores.
- [ ] **[Eu]** Teste de retentativa/duplicata: forçar não-200 uma vez, confirmar idempotência por `wamid` nas duas abordagens (a Meta reenvia por até 7 dias se não receber 200).
- [ ] **[Eu]** Decidir: Opção A por padrão, migrar para B só se o teste de carga mostrar degradação cruzada real.

### 6.3 Implementação (após decisão da Seção 6.2)

- [ ] **[Eu]** Construir `app/waba_client.py` para VFO, reaproveitando a estrutura de clientes WABA já existentes (`send_text`, `send_audio`, `send_video`, `send_image`, `upload_media`).
- [ ] **[Eu]** Adaptar `tools/vanessa.py` — cada `trigger_*()` passa a chamar `waba_client.send_audio/video/image(...)` em vez de `DataCrazyAutomationClient.trigger_automation(...)`, mantendo gatilho, conteúdo e guarda de repetição idênticos ao mapeamento em `01-automations-mapping.md`.
- [ ] **[Eu]** Corrigir, na mesma leva, a contradição identificada na auditoria: `trigger_automation_2()` hoje instrui enviar `send_payment_link` automaticamente, contrariando a regra do prompt de aguardar aceite explícito (`01-automations-mapping.md`, Seção 6, item 1) — unificar para só disparar após aceite explícito.
- [ ] **[Eu]** Implementar endpoint `GET/POST /webhooks/waba` com verificação HMAC (`X-Hub-Signature-256`, `hmac.compare_digest`), já na arquitetura escolhida na Seção 6.2.
- [ ] **[Eu]** Implementar atualização do lead no DataCrazy via chamada de API nossa (inverte a direção atual — antes o CRM nos avisava, agora nós avisamos o CRM).
- [ ] **[Eu]** Rodar toda a suíte de 27 automações no número de sandbox, comparando manualmente com o comportamento atual em produção (mesma ordem de mídia, mesmos gatilhos, mesmas guardas).

### 6.4 Corte de produção (Fase B) — big bang, com rollback manual

- [ ] **[Bruno]** Provisionar credenciais WABA de produção para os 2 números reais (mesmos 5 campos da Seção 6.1, agora para vanessa-1 e vanessa-2).
- [ ] **[Eu]** Configurar a arquitetura de webhook escolhida (6.2) para os 2 números reais.
- [ ] **[Eu]** Deploy do código validado em sandbox para as duas instâncias de produção, com o webhook antigo do DataCrazy **ainda ativo, mas não usado para envio** — só o suficiente para rollback rápido se necessário.
- [ ] **[Bruno]** Aprovação final do corte (checkpoint humano obrigatório antes do próximo passo).
- [ ] **[Eu]** Corte total: as duas instâncias passam a enviar via API oficial no mesmo instante.
- [ ] **[Eu]** Monitorar de perto (logs, taxa de erro, follow_up_scheduler) na primeira hora pós-corte.
- [ ] **[Bruno]** Decide, a qualquer momento, se aciona rollback manual (reverter `.env`/código para o caminho DataCrazy, que fica pronto e documentado até a estabilidade ser confirmada).
- [ ] **[Eu]** Após confirmação de estabilidade (critério: Bruno define o período de observação, sem gatilho automático), desligar de vez o webhook antigo do DataCrazy e remover `DATACRAZY_API_TOKEN`/`DATACRAZY_BASE_URL`/`DATACRAZY_INSTANCE_ID` dos `.env`.

### 6.5 Critério de conclusão da Fase B

- [ ] 27 automações validadas em sandbox com paridade de comportamento em relação à produção atual.
- [ ] Corte de produção executado e aprovado por Bruno.
- [ ] Caminho antigo desligado e envs de DataCrazy removidos, só após confirmação explícita de estabilidade.

---

## 7. Checklist consolidado de credenciais/envs

| Variável | Status hoje | Ação |
|---|---|---|
| `WABA_PHONE_NUMBER_ID` (teste + x2 produção) | ❌ não existe | **[Bruno]** provisionar |
| `WABA_ACCESS_TOKEN` (teste + x2) | ❌ não existe | **[Bruno]** provisionar |
| `WABA_WEBHOOK_VERIFY_TOKEN` (teste + x2) | ❌ não existe | **[Eu]** gerar |
| `WABA_APP_SECRET` (teste + x2) | ❌ não existe | **[Bruno]** provisionar |
| `WABA_BUSINESS_ACCOUNT_ID` (teste + x2) | ❌ não existe | **[Bruno]** provisionar |
| `VFO_DATABASE_URL` (x2, schemas diferentes) | ❌ não existe | **[Eu]** criar na Fase A |
| `DATACRAZY_API_TOKEN`, `DATACRAZY_BASE_URL`, `DATACRAZY_INSTANCE_ID` | ✅ existe | Remover só após 6.4 concluído |
| `SESSION_DB_PATH` | ✅ existe (SQLite) | Remover após Fase A concluída |
| `OMNIROUTE_*` | ✅ existe | Sem alteração |
| `PAYMENT_LINK`, `NURTURE_CONTENT_LINK`, `PAYMENT_WEBHOOK_SECRET`, `PORT` | ✅ existe | Sem alteração |

---

## 8. Artefatos a preservar

- [ ] **[Eu]** Dump completo dos 2 SQLite antes de qualquer migração (Fase 0).
- [ ] **[Eu]** Confirmar integridade de `objections_library.json`, `phase2_sequence.json`, `follow_up_templates.json` pós-migração de pasta (já validado na migração de infra anterior).
- [ ] **[Bruno]** Export/screenshot da configuração de cada flow no painel DataCrazy, como documentação de fallback, antes de perder acesso (se o contrato vier a ser encerrado).

### 8.3 Correção de bug aproveitando a migração

A tool `trigger_automation_2()` hoje manda enviar `send_payment_link` automaticamente, contrariando a regra do prompt de esperar aceite explícito do lead. Corrigido durante a Seção 6.3 — é a única mudança de comportamento de negócio permitida neste plano, por já estar documentada como bug real na auditoria.

---

## 9. Riscos e mitigações

### 9.1 Perda de mídia (risco mais alto do projeto)
Se o acesso ao painel DataCrazy for perdido antes da coleta completa, o conteúdo de até 6 automações do scheduler (hoje sem transcrição documentada em lugar nenhum) fica irrecuperável.
**Mitigação:** Seção 6.1 é bloqueador explícito antes de qualquer código de Fase B; sem prazo de cancelamento definido ainda, mas tratado como prioridade máxima assim que a Fase A libera capacidade.

### 9.2 Corrupção de estado de funil na migração de banco
Leads em conversa ativa (137 sessões somadas hoje) não podem perder flags como `automation_1_sent`.
**Mitigação:** Seção 5.4, item 4 (teste dedicado a flags de negócio); migração em lote único e pequeno volume reduz superfície de erro.

### 9.3 Uso da credencial compartilhada `bf_database`
Afeta 9+ serviços se alterada incorretamente.
**Mitigação:** este plano só propõe criar um banco novo sob a credencial existente — nunca modificá-la ou trocar senha.

### 9.4 Corte big bang concentra risco num único momento (Fase B)
Escolha deliberada do time (simplicidade > mitigação gradual).
**Mitigação:** validação exaustiva em sandbox (Seção 6.2 e 6.3) antes do corte real; caminho antigo mantido ativo (não usado, mas pronto) até confirmação de estabilidade; rollback manual sob decisão de Bruno, sem gatilho automático que possa reverter incorretamente por falso positivo.

### 9.5 Migrar banco e mensageria ao mesmo tempo
**Mitigação:** fases sequenciais (A antes de B), nunca simultâneas.

---

## 10. Marcos (sem prazo rígido — ordem, não data)

| Marco | Situação |
|---|---|
| Apresentação de status ao stakeholder | ✅ Concluída (16/07/2026) |
| Fase 0 — Preparação | Próximo passo |
| Fase A — Banco (Postgres + TDD) | Após Fase 0 |
| Fase B — Mensageria (API oficial) | Após Fase A validada 24h em produção |
| Decomissionamento total do DataCrazy (mensageria) | Após 6.4 concluído e estabilidade confirmada por Bruno |

---

## 11. Definição de pronto (Definition of Done) do plano inteiro

- [ ] Fase A: TDD 100% verde, produção estável 24h+ em Postgres, backup preservado.
- [ ] Fase B: 27 automações com conteúdo migrado e validado em sandbox, arquitetura de webhook decidida por teste (não suposição), corte aprovado por Bruno, DataCrazy desligado da mensageria com confirmação de estabilidade.
- [ ] Nenhuma regra de negócio do funil alterada além da correção documentada na Seção 8.3.
- [ ] Número de telefone e conexão de dados com o DataCrazy preservados em ambas as fases (conforme já comunicado ao stakeholder).
