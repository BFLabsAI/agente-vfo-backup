# Relatório de atendimentos — VFO / Vanessa

Levantado em 29/07/2026. Fonte: os três bancos SQLite do agente. carreg
Horários em America/Fortaleza (UTC−3).

---

## 1. Onde os dados estão

O VFO **não tem nada no Postgres**. Varri as 28 bases do servidor: nenhuma tem
tabela `vfo`/`vanessa`, nenhuma tem sessão com esse `agent_id`. Diferente do
outros agentes do portfólio, que foram migrados, o VFO segue 100% em SQLite.

São três arquivos, e um deles guarda a fase em que havia um número só:

| Banco | Fase | Sessões | Primeiro atendimento | Último atendimento |
|---|---|---:|---|---|
| `tmp/vanessa.db` | número único, antes do split | 162 | 07/05/2026 17:50 | 10/06/2026 19:23 |
| `instances/vanessa-1/data/vanessa.db` | Vanessa #1 | 104 | 10/06/2026 19:45 | 16/07/2026 14:11 |
| `instances/vanessa-2/data/vanessa.db` | Vanessa #2 | 37 | 10/06/2026 22:56 | 18/07/2026 14:17 |

### Consolidado

| | |
|---|---|
| **Pessoas atendidas (únicas, dedup por telefone)** | **295** |
| Soma bruta das três bases | 303 |
| Telefones que aparecem em mais de uma fase | 9 |
| **Primeiro atendimento** | **07/05/2026 17:50** |
| **Último atendimento** | **18/07/2026 14:17** |
| Janela de operação | 71 dias |


### Como ler esta tabela

**O corte entre as fases é limpo.** O banco de número único termina em 10/06 às
19:23 e o `vanessa-1` começa às 19:45 do mesmo dia — 22 minutos depois. É o
momento exato do split. Não há período de sobreposição em que os dois estivessem
gravando ao mesmo tempo, então somar as três bases não conta ninguém duas vezes
por erro de recorte.

**295 é gente, não conversa.** O `session_id` tem o formato
`vanessa-wa-{telefone}`, ou seja, um registro por número de WhatsApp. Os 8 de
diferença entre a soma bruta (303) e o total único (295) são pessoas que voltaram
a falar depois do split e ganharam sessão nova no banco da instância — mesma
pessoa, dois registros. A dedup é por telefone.

**Não existe formato antigo de `session_id`.** As três bases usam o mesmo padrão.
O que mudou na migração foi o arquivo, não o esquema: antes era um SQLite só,
depois virou um por instância. Os outros dois `.db` do repositório
(`data/sessions.db` e `data/vfo_sessions.db`) estão com 0 byte.



---

## 2. Atendimentos dia a dia — julho/2026

| Dia | Semana | Leads novos | Pessoas ativas | Interações |
|---:|---|---:|---:|---:|
| 01/07 | qua | 0 | 1 | 5 |
| 02/07 | qui | — | — | — |
| 03/07 | sex | 3 | 3 | 9 |
| 04/07 | **sáb** | — | — | — |
| 05/07 | **dom** | — | — | — |
| 06/07 | seg | 2 | 3 | 3 |
| 07/07 | ter | — | — | — |
| 08/07 | qua | 1 | 1 | 39 |
| 09/07 | qui | 2 | 4 | 16 |
| 10/07 | sex | 3 | 4 | 11 |
| 11/07 | **sáb** | 2 | 2 | 2 |
| 12/07 | **dom** | — | — | — |
| 13/07 | seg | 1 | 3 | 3 |
| 14/07 | ter | 1 | 3 | 11 |
| 15/07 | qua | 1 | 4 | 5 |
| 16/07 | qui | 1 | 3 | 5 |
| 17/07 | sex | 1 | 1 | 2 |
| 18/07 | **sáb** | 0 | 1 | 1 |
| 19/07 | **dom** | — | — | — |
| 20/07 a 31/07 | seg a sex | — | — | — |
| **Total** | | **18** | **19 únicas** | **112** |

**Colunas:** *leads novos* = sessão criada no dia, pessoa nova. *pessoas ativas* =
telefones distintos que trocaram mensagem no dia, incluindo conversa começada
antes. *interações* = chamadas ao modelo (`llm_usage_log`).

### O efeito fim de semana é real

Separando os dias até 18/07 — o período em que houve operação:

| | Dias | Com movimento | Zerados | Taxa |
|---|---:|---:|---:|---|
| Dias úteis | 13 | 11 | 2 | **85%** |
| Fim de semana | 5 | 2 | 3 | **40%** |

Sábado e domingo respondem por 3 dos 5 dias zerados do período. Nenhum domingo do
mês teve um único lead novo ou mensagem. Sábado tem comportamento misto: 11/07
trouxe 2 leads novos, 18/07 teve só uma interação de conversa antiga, e 04/07 foi
zero.

Mas o fim de semana **não explica tudo**: sobram dois dias úteis zerados, 02/07
(quinta) e 07/07 (terça). Então há intermitência de tráfego além do padrão
semanal.

### O que mais chama atenção

**Volume baixo.** 18 leads novos no mês inteiro, contra 295 no acumulado de 71
dias. Julho concentra 6% de tudo que o agente já atendeu.

**Parada seca a partir de 19/07.** Onze dias corridos com zero: nenhum lead novo,
nenhuma mensagem, nenhuma chamada ao modelo. O último sinal de vida é 18/07 às
11h17, uma interação isolada de conversa já existente. Os dois serviços seguem
`active (running)` — não é queda do agente. O corte está fora dele: campanha
pausada ou webhook da DataCrazy parando de entregar.

**08/07 destoa.** Uma pessoa só, 39 interações — quase o triplo do segundo maior
dia do mês, com um único lead. Ou foi uma conversa muito longa, ou um loop de
retry. Vale abrir a sessão e conferir.

---

## Consultas usadas

```sql
-- Pessoas únicas e janela de atendimento (por banco)
SELECT COUNT(DISTINCT session_id),
       datetime(MIN(created_at),'unixepoch'),
       datetime(MAX(updated_at),'unixepoch')
FROM agno_sessions;

-- Vendas confirmadas (a fonte correta — não use is_purchased)
SELECT COUNT(*) FROM payment_links WHERE paid = 1;

-- Atividade diária real
SELECT date(ts, '-3 hours') AS dia,
       COUNT(DISTINCT session_id) AS pessoas_ativas,
       COUNT(*)                   AS interacoes
FROM llm_usage_log
GROUP BY dia ORDER BY dia;
```
