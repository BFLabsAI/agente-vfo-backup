# Agente VFO — "Vanessa"

Agente de atendimento e vendas por WhatsApp. Recebe as mensagens dos leads, conversa usando
inteligência artificial, envia conteúdos e links de pagamento, e faz o acompanhamento automático
de quem não responde.

Construído pela [BF Labs](https://bflabs.com.br) para o cliente VFO.

**Stack:** Python 3.11 · [Agno](https://github.com/agno-agi/agno) · FastAPI · SQLite ·
DataCrazy (gateway de WhatsApp) · provedor de LLM compatível com a API da OpenAI.

---

## Arquitetura

```
Lead no WhatsApp
      │
      ▼
  DataCrazy  (gateway)
      │  webhook
      ▼
┌──────────────────────────────────────────────┐
│  FastAPI · app/whatsapp_api.py               │
│    ├── message_buffer   agrupa mensagens     │
│    │                    picadas do lead      │
│    ├── media_handler    áudio e imagem       │
│    ├── agent_factory ──► Agno Agent          │
│    │                      ├── prompts/       │
│    │                      └── tools/         │
│    ├── follow_up_scheduler   reengajamento   │
│    └── SQLite  instances/<nome>/data/        │
└──────────────────────────────────────────────┘
      │
      ▼
  Provedor de LLM (endpoint OpenAI-compatível)
```

O sistema roda em **instâncias independentes** — `vanessa-1` e `vanessa-2` no ambiente original.
Todas compartilham o mesmo código, com configuração e banco separados por instância, funcionando
como atendentes distintos.

### Endpoints

Cada instância expõe, sob seu próprio prefixo (`/vfo`, `/vfo-2`, …):

| Método | Rota | Função |
|---|---|---|
| `GET` | `/health` | Verificação de saúde |
| `POST` | `/webhooks/datacrazy` | Recebimento de mensagens do WhatsApp |
| `POST` | `/webhooks/pause-lead` | Pausa o agente num lead (handoff humano) |
| `POST` | `/webhooks/payment` | Confirmação de pagamento |

---

## Estrutura

| Caminho | O que é |
|---|---|
| `app/` | Aplicação — recebimento de mensagens, orquestração do agente, agendador de follow-up |
| `prompts/vanessa.py` | Instruções que definem personalidade e roteiro do agente |
| `tools/vanessa.py` | Ferramentas disponíveis ao agente (link de pagamento, envio de conteúdo etc.) |
| `instances/<nome>/` | Configuração e banco de cada instância |
| `migrations/` | Schema do banco em SQL versionado |
| `migrate.py` | Aplicador de migrations |
| `deploy/` | Units systemd de exemplo |
| `documents/` | Documentação do projeto |
| `plano-melhorias/` | Planos de evolução |
| `data/` | Bibliotecas de conteúdo: objeções, templates de follow-up, sequências |

Principais módulos de `app/`:

| Arquivo | Função |
|---|---|
| `whatsapp_api.py` | Rotas HTTP e ciclo de vida da aplicação |
| `agent_factory.py` | Montagem do agente Agno |
| `llm_factory.py` | Conexão com o provedor de LLM |
| `context.py` | Construção do contexto da conversa |
| `follow_up_scheduler.py` · `follow_up_state.py` | Cadência de reengajamento e seu estado |
| `media_handler.py` | Transcrição de áudio e leitura de imagem |
| `message_buffer.py` | Agrupamento de mensagens fragmentadas |
| `datacrazy_automation.py` · `whatsapp_bridge.py` | Integração com o gateway |
| `llm_usage_log.py` · `transaction_log.py` · `error_log.py` | Telemetria e registros |

---

## Como rodar

### 1. Dependências

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Configuração

Copie o exemplo e preencha:

```bash
cp instances/.env.example instances/vanessa-1/.env
```

| Variável | Descrição |
|---|---|
| `DATACRAZY_API_TOKEN` · `DATACRAZY_BASE_URL` · `DATACRAZY_INSTANCE_ID` | Acesso ao gateway de WhatsApp |
| `OMNIROUTE_API_KEY` · `OMNIROUTE_BASE_URL` | Chave e endpoint do provedor de LLM |
| `OMNIROUTE_MODEL_ID` | Modelo de texto |
| `OMNIROUTE_MEDIA_MODEL_ID` · `OMNIROUTE_VISION_FALLBACK_MODEL` | Modelos de visão |
| `OMNIROUTE_AUDIO_MODEL_ID` | Modelo de transcrição de áudio |
| `SESSION_DB_PATH` | Caminho do banco SQLite da instância |
| `PAYMENT_LINK` · `NURTURE_CONTENT_LINK` | Links comerciais |
| `PAYMENT_WEBHOOK_SECRET` | Segredo do webhook de pagamento |
| `PORT` | Porta HTTP da instância |

> **Provedor de LLM.** As variáveis com prefixo `OMNIROUTE_` apontam para um endpoint
> **compatível com a API da OpenAI** — no ambiente original, o roteador interno da BF Labs.
> Funcionam com qualquer serviço compatível: OpenAI, Azure OpenAI, OpenRouter, vLLM ou um
> endpoint próprio. Basta informar `OMNIROUTE_BASE_URL` e `OMNIROUTE_API_KEY`; nenhuma alteração
> de código é necessária.

### 3. Webhooks de automação do CRM

As URLs de gatilho dos fluxos do CRM são específicas da conta e não são versionadas. Copie o
exemplo e preencha:

```bash
cp config/datacrazy_webhooks.example.json config/datacrazy_webhooks.json
```

O arquivo mapeia cada `instance_id` do gateway para o seu conjunto de webhooks, com as 28 chaves
de automação usadas pelo agente. Sem ele, o sistema sobe normalmente e registra um aviso — apenas
os disparos por webhook ficam inativos.

### 4. Banco de dados

```bash
.venv/bin/python migrate.py --db instances/vanessa-1/data/vanessa.db
```

Seguro sobre bancos com dados: cria apenas o que falta e nunca apaga registros. Cada migration é
aplicada uma única vez, com controle na tabela `schema_migrations`. Para conferir sem alterar:
`--check`.

### 5. Subir

```bash
.venv/bin/uvicorn app.whatsapp_api:app --host 0.0.0.0 --port 8004
```

Em produção, use os units de `deploy/` como base. Aponte o webhook do gateway para
`https://<seu-dominio>/vfo/webhooks/datacrazy`.

---

## Modelo de dados

SQLite, um arquivo por instância.

| Tabela | Conteúdo |
|---|---|
| `agno_sessions` | Sessões do Agno — histórico de conversa em JSON |
| `agent_transactions` | Um registro por turno: mensagem do lead, resposta do agente, eventos |
| `follow_up_state` | Estado da cadência de reengajamento por lead |
| `payment_links` | Links gerados, com UTM, situação de pagamento e valor |
| `llm_usage_log` | Tokens, custo e latência por chamada |
| `tool_errors` | Falhas de ferramenta com traceback e contexto |
| `agno_schema_versions` | Versão de schema do Agno (2.5.6) |
| `schema_migrations` | Controle das migrations aplicadas |

---

## Documentação

Em `documents/`:

| Arquivo | Assunto |
|---|---|
| `01-automations-mapping.md` | Mapeamento completo das 27 automações de venda do agente |
| `02-plano-migracao.md` | Plano de migração para a API oficial do WhatsApp (Meta Cloud API) e para banco compartilhado — escopo, fases, riscos e critérios de teste |
| `03-whatsapp-waba-multinumber-setup.md` | Configuração de múltiplos números sob um mesmo WABA, com roteamento por `phone_number_id` |
| `04-relatorio-atendimentos-vfo.md` | Relatório de atendimentos |

Em `plano-melhorias/` estão os planos de evolução que serviram de especificação antes da
implementação — incluindo o rastreamento de pagamento.

Em `data/`, além das bibliotecas de conteúdo do agente (objeções, templates de follow-up,
sequências), há dois relatórios técnicos sobre a integração com o gateway DataCrazy
(`report_datacrazy_errors_05062026.md` e `report_datacrazy_errors_complete_29072026.md`), que
documentam falhas de entrega, bugs de encoding e ausência de retry na API do fornecedor, com
horários e sequência de eventos.

> Os relatórios foram anonimizados para publicação: nomes de contatos viraram rótulos
> (`Lead 01`, `Lead 02`…) e telefones tiveram os dígitos centrais mascarados, de forma
> consistente ao longo dos documentos. Nenhum dado pessoal identificável é publicado aqui.

---

## Segurança

Este repositório é público e **não contém credenciais nem dados de leads**. O `.gitignore`
bloqueia `.env`, bancos (`*.db`), CSVs, logs e chaves.

Ao trabalhar sobre este código, mantenha essa separação: credenciais sempre em variáveis de
ambiente, nunca no código. Os bancos guardam conversas reais — nome, telefone e teor das
mensagens — e são dados pessoais sujeitos à LGPD.

---

## Licença

Sem licença aberta. Todos os direitos reservados à BF Labs e ao cliente VFO. O código é
publicado para consulta e continuidade do projeto pelo cliente; qualquer outro uso depende de
autorização.
