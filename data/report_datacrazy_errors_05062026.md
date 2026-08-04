# Relatório de Erros — DataCrazy API

> **Nota de privacidade.** Este documento é publicado em repositório aberto. Os nomes dos
> contatos foram substituídos por rótulos (`Lead 01`, `Lead 02`…) e os telefones tiveram os
> dígitos centrais mascarados. A rotulagem é consistente: o mesmo contato mantém o mesmo
> rótulo ao longo do relatório. Horários, sequência de eventos e conteúdo técnico estão
> preservados na íntegra.
**Data:** 05/06/2026
**Instância:** <instance-id-2>
**Solicitante:** Guilherme Araujo (BF Labs)

---

## Problema

Múltiplas falhas no envio de mensagens via DataCrazy entre 04/06 e 05/06/2026. Todas apresentam o mesmo erro:

```
Invalid character in header content ["message"]
```

As mensagens não são entregues ao contato. O erro indica que o conteúdo da mensagem está sendo colocado em um header HTTP, e caracteres como emojis (🥹, 😊, ❤️, 😅, 😫) ou quebras de linha causam falha na requisição.

---

## Casos Afetados

### 05/06/2026

| Horário | Contato | Telefone | Mensagem (trecho) |
|---------|---------|----------|-------------------|
| 11:08 | Lead 01 | 5547****3020 | "...vou pagar meu cartão somente dia 10 🥹🥹🥹" |
| 10:51 | Lead 02 | 5588****7432 | Informações e links do treinamento (com asterisco * como formatação) |
| 09:19 | Lead 03 | 5579****3051 | "Mudar minha realidade financeira. Concretizar sonhos…" |
| 08:43 | Lead 01 | 5547****3020 | "...já comprei algumas mentorias.. mas travo muito" |
| 02:19 | Lead 04 | 5585****1296 | Texto longo sobre independência financeira |

### 04/06/2026

| Horário | Contato | Telefone | Mensagem (trecho) |
|---------|---------|----------|-------------------|
| 22:08 | Lead 05 | 5599****6022 | "Tbm ❤️" |
| 21:40 | Lead 06 | 5521*****1812 | "Não mandei áudio 😅" |
| 21:40 | Lead 06 | 5521*****1812 | "Não teria como eu pagar depois do primeiro resultado? 😅" |
| 20:58 | Lead 07 | 5585****9435 | "Pode mandar sim ☺️" |
| 18:54 | Lead 08 | 5581****8465 | "Já tentei aqui pedir emprestado mas sem sucesso 😫" |
| 18:21 | Lead 09 | 5531****4011 | Texto sobre trabalho como diarista |

---

## Padrão Identificado

- **100% dos casos** apresentam o mesmo erro: `Invalid character in header content ["message"]`
- **Caracteres problemáticos:** emojis (🥹, 😊, ❤️, 😅, ☺️, 😫), reticências (…), asteriscos (*), quebras de linha (\n)
- **Payload afetado:** o conteúdo da mensagem está sendo inserido num header HTTP em vez de no body
- **Impacto:** mensagens não entregues ao lead, quebra do fluxo de conversa automatizado

---

## Contexto Técnico

Nossa aplicação (VFO) envia mensagens via API REST do DataCrazy:
- **Endpoint:** `POST /api/v1/conversations/{id}/messages`
- **Formato:** JSON body `{"body": "texto da mensagem"}`
- **Autenticação:** Bearer token

As mensagens que enviamos via API REST funcionam normalmente. Os erros parecem ocorrer em **automações internas do DataCrazy** que disparam mensagens via webhook, onde o conteúdo pode estar sendo colocado incorretamente num header HTTP.

---

## Solicitação

1. Verificar por que o conteúdo da mensagem está sendo colocado em header HTTP nas automações
2. Corrigir o encoding para suportar emojis e caracteres especiais UTF-8
3. Implementar fallback/retry para mensagens que falham por encoding
4. Informar se há workaround temporário do nosso lado

---

**Nota:** Este bug está causando perda de leads — mensagens de interesse e negociação não estão sendo entregues.
