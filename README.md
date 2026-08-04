# Agente VFO — Backup

Agente de atendimento e vendas por WhatsApp. Recebe as mensagens dos leads, conversa usando
inteligência artificial, envia conteúdos e links de pagamento, e faz o acompanhamento automático
de quem não responde.

Backup do agente construído pela [BF Labs](https://bflabs.com.br) para o cliente VFO. Este repositório
reúne o código de produção completo, incluindo o necessário para rodar as duas instâncias que
operavam em paralelo.

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
| `instances/<nome>/` | Configuração e banco de cada instância (duas no ambiente original) |
| `config/` | Mapa de webhooks de automação do CRM (exemplo versionado) |
| `migrations/` | Schema do banco em SQL versionado |
| `migrate.py` | Aplicador de migrations |
| `deploy/` | Arquivos de serviço systemd das duas instâncias |
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

Parte das mensagens não sai pelo agente de IA: são **fluxos prontos, montados no painel do
DataCrazy** (áudio de abertura, respostas a objeções recorrentes, sequência de follow-up,
mensagem de pós-pagamento). O agente decide *quando* disparar cada um e chama o fluxo por
webhook — o conteúdo em si vive no CRM, não no código.

Cada fluxo tem uma URL de gatilho própria, específica da sua conta. **Essas URLs não são
versionadas** (quem tem a URL consegue disparar a automação), então você precisa gerá-las e
preenchê-las:

```bash
cp config/datacrazy_webhooks.example.json config/datacrazy_webhooks.json
```

Depois, para cada uma das **28 automações**, abra o fluxo correspondente no painel do DataCrazy,
gere a URL de gatilho por webhook e cole na chave. O arquivo já vem com todas as chaves listadas
e um `_leia_me` com o passo a passo.

Estrutura — um bloco por instância, indexado pelo `DATACRAZY_INSTANCE_ID`:

```json
{
  "instancias": {
    "68a1b2c3d4e5f6a7b8c9d0e1": {
      "automacao_1": "https://api.datacrazy.io/v1/crm/api/crm/flow/…",
      "pergunta_experiencia": "",
      "pos_pagamento": "https://api.datacrazy.io/v1/crm/api/crm/flow/…"
    }
  }
}
```

As 28 chaves se dividem em três grupos: **abertura** (`automacao_1`, `automacao_2`,
`pergunta_experiencia`), **objeções** (`ja_fez_mentoria`, `precisa_computador`, `tem_medo`,
`comecando_do_zero`, `como_sei_seguro` e outras) e **follow-up e pós-venda**
(`bf_labs_follow1_pt3`, `bf_labs_follow_janela_24h`, `pos_pagamento` etc.).

Ao disparar, o agente envia `lead_id`, `conversation_id`, `contactId` e `phone` — o fluxo do CRM
usa esses campos para localizar o contato e enviar a mensagem.

**Comportamento sem configuração:** o sistema sobe normalmente e registra um aviso; só os
disparos por webhook ficam inativos. Se uma chave estiver vazia, o agente tenta a URL equivalente
na primeira instância configurada; não achando, registra erro e segue operando. Toda a conversa
com IA, o agendamento de follow-up e a geração de link de pagamento funcionam independentemente
deste arquivo.

### 4. Banco de dados

```bash
.venv/bin/python migrate.py --db instances/vanessa-1/data/vanessa.db
```

Seguro sobre bancos com dados: cria apenas o que falta e nunca apaga registros. Cada migration é
aplicada uma única vez, com controle na tabela `schema_migrations`. Para conferir sem alterar:
`--check`.

### 5. Subir as instâncias

O agente rodava com **dois números de WhatsApp em paralelo** — dois processos do mesmo código,
cada um com seu `.env`, seu banco e sua porta:

```bash
# instância 1 — número principal
.venv/bin/uvicorn app.whatsapp_api:app --host 0.0.0.0 --port 8004

# instância 2 — segundo número (outro terminal)
.venv/bin/uvicorn app.whatsapp_api:app --host 0.0.0.0 --port 8005
```

Cada processo lê o `.env` da sua instância, que define `PORT`, `SESSION_DB_PATH` e o
`DATACRAZY_INSTANCE_ID` do número correspondente. Os bancos são separados: uma conversa da
instância 1 não enxerga a da instância 2.

Para rodar **apenas um número**, suba só a primeira e ignore `instances/vanessa-2/`.

Em produção, `deploy/` traz os dois arquivos de serviço systemd usados originalmente
(`vfo-agent.service` e `vfo-agent-2.service`), com reinício automático em caso de queda:

```bash
sudo cp deploy/vfo-agent*.service /etc/systemd/system/   # ajuste os caminhos antes
sudo systemctl daemon-reload
sudo systemctl enable --now vfo-agent vfo-agent-2
```

Por fim, aponte o webhook de cada número no painel do DataCrazy para o endereço público
correspondente: `https://<seu-dominio>/vfo/webhooks/datacrazy` para a instância 1 e
`https://<seu-dominio>/vfo-2/webhooks/datacrazy` para a instância 2.

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
