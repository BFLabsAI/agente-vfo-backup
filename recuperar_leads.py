#!/usr/bin/env python3
"""
recuperar_leads.py — Envia webhooks para a VFO para recuperar leads que ficaram sem resposta.
Cada lead recebe um trigger "Oi" que faz o agente criar sessão e enviar a intro.
"""
import asyncio
import aiohttp
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("recuperar")

# Leads pendentes — phone, conv_id, nome (do DataCrazy), porta da instância.
#
# Preencha com os contatos a recuperar. Os telefones vão em E.164 sem o "+"
# (ex.: 5511999999999) e o conv_id é o identificador da conversa no gateway.
#
# Nota: este arquivo é versionado em repositório público — não deixe telefones
# nem identificadores de contatos reais aqui. Para uso recorrente, carregue a
# lista de um arquivo externo (fora do versionamento) ou direto do banco.
LEADS = [
    # Instância 1 (porta 8004)
    {"phone": "55DDNNNNNNNNN", "conv_id": "<id-da-conversa>", "name": "", "port": 8004},
    # Instância 2 (porta 8005)
    {"phone": "55DDNNNNNNNNN", "conv_id": "<id-da-conversa>", "name": "", "port": 8005},
]

async def send_trigger(session: aiohttp.ClientSession, lead: dict) -> None:
    """Envia webhook Format C para a VFO."""
    url = f"http://localhost:{lead['port']}/vfo/webhooks/datacrazy"
    
    # Format C: {externalId,name,phone,conversationId,body}
    # Usando "Oi" como trigger — o agente vai criar sessão e enviar intro
    payload = f"{{\n  fake-trigger-id,\n  {lead['name']},\n  {lead['phone']},\n  {lead['conv_id']}, \n  Oi\n}}"
    
    logger.info("Enviando trigger para %s (porta %d)...", lead["phone"], lead["port"])
    
    try:
        async with session.post(url, data=payload, headers={"Content-Type": "text/plain"}) as resp:
            body = await resp.text()
            logger.info("  → %d: %s", resp.status, body[:100])
    except Exception as exc:
        logger.error("  → ERRO: %s", exc)


async def main() -> None:
    logger.info("=== RECUPERAÇÃO DE LEADS PENDENTES ===")
    logger.info("Total: %d leads", len(LEADS))
    logger.info("")
    
    async with aiohttp.ClientSession() as session:
        for i, lead in enumerate(LEADS):
            await send_trigger(session, lead)
            # Delay entre triggers para não sobrecarregar
            if i < len(LEADS) - 1:
                logger.info("Aguardando 5s...")
                await asyncio.sleep(5)
    
    logger.info("")
    logger.info("=== CONCLUÍDO ===")
    logger.info("Os agentes vão processar cada lead com delay de ~2min.")
    logger.info("Acompanhe os logs: journalctl -u vfo-agent -u vfo-agent-2 -f")


if __name__ == "__main__":
    asyncio.run(main())
