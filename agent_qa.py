# agent_qa.py - VERSÃO 1.6 - PROJETO ALCINDO (AUDITOR DE SKILLS)
# LOCAL: Railway

import os
import requests
import mysql.connector
from flask import Flask, request, jsonify
import logging
import httpx
from openai import OpenAI

# Configuração de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- MANUAL DE IDENTIDADE ALCINDO (DIRETRIZES DO VOICE HUB) ---
ALCINDO_MANUAL = """
Você é o ALCINDO, o Auditor de Skills do Voice Hub. Sua missão é garantir que a IA narre textos publicitários com perfeição fonética.

DIRETRIZES DE OURO DO VOICE HUB:
1. REGRA DE VAREJO (MOEDAS): Em preços (Ex: R$ 10,90), a IA deve dizer "dez e noventa". É PROIBIDO falar "reais" ou "centavos", exceto se o texto for institucional/formal.
2. REGRA DO TELEFONE: O dígito "6" deve ser pronunciado como "meia".
3. REGRA DE ESTADOS: Siglas de estados (SP, RJ, MG, etc.) devem SEMPRE ser lidas por extenso (São Paulo, Rio de Janeiro, etc.).
4. REGRA DE PAUSAS: Palavras em MAIÚSCULO (ex: ATENÇÃO) devem ter uma pausa (vírgula) logo após. Palavras como "Confira" devem ter reticências para suspense.
5. REGRA DE UNIDADES: "kg" deve ser lido como "quilo", "m" pode ser "metros" ou "minutos" dependendo do contexto.

SUA TAREFA:
Compare o 'Texto Esperado' (o que a Skill enviou) com o 'Ouvido pelo Agente' (transcrição do áudio).
Identifique onde a IA ignorou as diretrizes acima.
"""

@app.route('/')
def home():
    return "Alcindo (Auditor de Skills) está online e vigiando."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    logger.info(">>> Alcindo iniciando auditoria...")
    
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        return jsonify({"error": "ID do reporte ausente"}), 400

    api_key = os.environ.get("OPENAI_API_KEY")
    
    # Cliente blindado contra proxies do Railway
    http_client = httpx.Client(trust_env=False)
    client = OpenAI(api_key=api_key, http_client=http_client)

    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 20
    }

    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 1. Busca dados do reporte e metadados da mídia
        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface, m.voice_name
            FROM audio_error_reports r
            JOIN media_vault m ON r.media_id = m.id
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({"error": "Reporte não localizado."}), 404

        # 2. Download do áudio para Alcindo ouvir
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        audio_res = requests.get(audio_url, timeout=30)
        audio_path = f"/tmp/{report['filename']}"
        with open(audio_path, 'wb') as f:
            f.write(audio_res.content)

        # 3. Transcrição Whisper (Ouvido do Alcindo)
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, language="pt"
            )
        text_heard = transcription.text

        # 4. Diagnóstico Alcindo (Cérebro com GPT-4o)
        prompt_final = f"""
        {ALCINDO_MANUAL}

        CASO PARA ANÁLISE:
        - Locutor Usado: {report['voice_name']}
        - Texto Enviado para IA: "{report['text_content']}"
        - O que o Alcindo ouviu no áudio: "{text_heard}"
        - O que o usuário reclamou: "{report['user_comment']}"

        FORMATO DE RESPOSTA:
        1. DIAGNÓSTICO: (Explique o que aconteceu tecnicamente)
        2. VEREDITO: (Culpado: IA ou Culpado: Skill ausente)
        3. SUGESTÃO DE SKILL: (Dê a regra de dicionário ou regex para o arquivo PHP)
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Você é o Alcindo, auditor técnico de áudio."},
                      {"role": "user", "content": prompt_final}]
        )
        diagnosis = completion.choices[0].message.content

        # 5. Salva a auditoria no banco da Hostinger
        update_sql = "UPDATE audio_error_reports SET agent_transcription = %s, agent_diagnosis = %s, status = 'completed' WHERE id = %s"
        cursor.execute(update_sql, (text_heard, diagnosis, report_id))
        conn.commit()

        logger.info(f"Auditoria #{report_id} finalizada pelo Alcindo.")
        if os.path.exists(audio_path): os.remove(audio_path)

        return jsonify({"success": True, "alcindo_vibe": "Auditoria concluída com sucesso"})

    except Exception as e:
        logger.error(f"Erro no Alcindo: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)