import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime

# IDs dos canais
CANAL_COMPROVANTE = 1375153214994780240
CANAL_PAGARAM = 1375148841967292486
CANAL_NAO_PAGARAM = 1375152892851523654
CANAL_RESUMO = 1375153817569595452

# Caminho para o arquivo de dados
DATA_FILE = "meta_data.json"

# Carregar dados
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        dados = json.load(f)
else:
    dados = {"meta_semanal": 350, "membros": [], "valor_total": 0}

# Função para salvar
def salvar_dados():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

# Intents obrigatórios
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Reset automático toda segunda-feira às 00h
@tasks.loop(minutes=60)
async def reset_semanal():
    now = datetime.utcnow()
    if now.weekday() == 0 and now.hour == 0:  # Segunda-feira 00h UTC
        # Resetar valores pagos e status
        for membro in dados["membros"]:
            membro["valor_pago"] = 0
            membro["pagou"] = False
        dados["valor_total"] = 0
        salvar_dados()

        canal_pagaram = bot.get_channel(CANAL_PAGARAM)
        canal_nao_pagaram = bot.get_channel(CANAL_NAO_PAGARAM)
        canal_resumo = bot.get_channel(CANAL_RESUMO)

        # Limpar mensagens antigas
        for canal in [canal_pagaram, canal_nao_pagaram, canal_resumo]:
            if canal:
                await canal.purge(limit=100)

        # Atualizar canal de quem não pagou (lista completa zerada)
        if canal_nao_pagaram:
            for membro in dados["membros"]:
                user = await bot.fetch_user(membro["id"])
                await canal_nao_pagaram.send(f"❌ {user.mention} ainda não pagou a meta.")

        # Atualizar resumo (zerado)
        if canal_resumo:
            total_membros = len(dados["membros"])
            total_pagaram = 0
            total_faltam = total_membros
            ranking_texto = "Nenhum pagamento registrado ainda."

            await canal_resumo.send(
                f"📊 **Resumo da Semana**\n\n"
                f"👥 Total de membros: {total_membros}\n"
                f"💰 Pagaram: {total_pagaram}\n"
                f"⏳ Faltam: {total_faltam}\n"
                f"🧾 Total arrecadado: 0 folhas\n\n"
                f"🏆 **Top 3 - Quem mais pagou:**\n{ranking_texto}"
            )

# Comando para adicionar membros à lista (sem apagar os existentes)
@bot.command()
async def registrar_membros(ctx, *args: discord.Member):
    ids_existentes = [m["id"] for m in dados["membros"]]
    for membro in args:
        if membro.id not in ids_existentes:
            dados["membros"].append({"id": membro.id, "nome": membro.display_name, "pagou": False, "valor_pago": 0})
    salvar_dados()

    canal_nao_pagaram = bot.get_channel(CANAL_NAO_PAGARAM)
    if canal_nao_pagaram:
        await canal_nao_pagaram.purge(limit=100)
        for membro in dados["membros"]:
            if not membro["pagou"]:
                user = await ctx.guild.fetch_member(membro["id"])
                await canal_nao_pagaram.send(f"❌ {user.mention} ainda não pagou a meta.")

    await ctx.send("✅ Membros adicionados e listados no canal de não pagaram.")

# Listener para mensagens no canal de comprovante
@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.channel.id != CANAL_COMPROVANTE:
        return

    if not message.attachments or not message.mentions:
        return

    # Detecta valor da meta na mensagem (ex: "meta: 450")
    valor_meta = dados.get("meta_semanal", 350)
    palavras = message.content.lower().split()
    for palavra in palavras:
        if palavra.startswith("meta:"):
            try:
                valor_meta = int(palavra.replace("meta:", ""))
            except ValueError:
                pass

    for mencionado in message.mentions:
        for membro in dados["membros"]:
            if membro["id"] == mencionado.id:
                if membro["pagou"]:
                    membro["valor_pago"] += valor_meta
                else:
                    membro["pagou"] = True
                    membro["valor_pago"] = valor_meta
                dados["valor_total"] += valor_meta

                canal_pagaram = bot.get_channel(CANAL_PAGARAM)
                canal_nao_pagaram = bot.get_channel(CANAL_NAO_PAGARAM)
                canal_resumo = bot.get_channel(CANAL_RESUMO)

                await canal_pagaram.send(f"✅ {mencionado.mention} pagou {valor_meta} folhas!")

                async for msg in canal_nao_pagaram.history(limit=100):
                    if mencionado.mention in msg.content:
                        await msg.delete()

                async for msg in canal_resumo.history(limit=5):
                    if msg.author == bot.user:
                        await msg.delete()

                total_membros = len(dados["membros"])
                total_pagaram = sum(1 for m in dados["membros"] if m["pagou"])
                total_faltam = total_membros - total_pagaram

                ranking = sorted(dados["membros"], key=lambda x: x.get("valor_pago", 0), reverse=True)[:3]
                ranking_texto = "\n".join(
                    [f"#{i+1} {await bot.fetch_user(m['id'])} - {m.get('valor_pago', 0)} folhas" for i, m in enumerate(ranking)]
                )

                await canal_resumo.send(
                    f"📊 **Resumo da Semana**\n\n"
                    f"👥 Total de membros: {total_membros}\n"
                    f"💰 Pagaram: {total_pagaram}\n"
                    f"⏳ Faltam: {total_faltam}\n"
                    f"🧾 Total arrecadado: {dados['valor_total']} folhas\n\n"
                    f"🏆 **Top 3 - Quem mais pagou:**\n{ranking_texto}"
                )

                try:
                    await mencionado.send(f"✅ Obrigado! Seu pagamento de {valor_meta} folhas foi confirmado.")
                except:
                    pass

                salvar_dados()
                return

# Tarefa para lembrar membros via DM
@tasks.loop(hours=12)
async def lembrar_nao_pagaram():
    for membro in dados["membros"]:
        if not membro["pagou"]:
            user = await bot.fetch_user(membro["id"])
            try:
                await user.send("🚨 Lembrete: você ainda não pagou a meta semanal. Por favor envie o comprovante no canal apropriado!")
            except:
                pass

@bot.event
async def on_ready():
    reset_semanal.start()
    lembrar_nao_pagaram.start()
    print(f"Bot conectado como {bot.user}")

bot.run("")
#python meta_bot.py