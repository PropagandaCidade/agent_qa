# agent_qa.py - VERSÃO 2.0 - ALCINDO RAG (RETRIEVAL-AUGMENTED GENERATION)
# LOCAL: Railway
# DESCRIÇÃO: Alcindo agora consulta o "Cérebro" na Hostinger antes de auditar.

import os
import time
import requests
import mysql.connector
from flask import Flask, request, jsonify
import logging
import httpx
from openai import OpenAI
import io
import json

# Configurações de Blindagem
os.environ['HTTP_PROXY'] = ""
os.environ['HTTPS_PROXY'] = ""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configurações do Squad
BRAIN_TOKEN = "HUB_SQUAD_SECRET_2024"
BRAIN_URL = "https://propagandacidadeaudio.com.br/voice-hub/squad/brain/knowledge_bridge.php"

def get_hub_context():
    """Busca o Cérebro (Regras e Memórias) na Hostinger via RAG"""
    try:
        url = f"{BRAIN_URL}?token={BRAIN_TOKEN}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Falha ao acessar o Cérebro RAG: {e}")
    return None

@app.route('/')
def home():
    return "Alcindo RAG v2.0 - Conectado ao Squad."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    start_time = time.perf_counter()
    data = request.get_json()
    report_id = data.get('report_id')

    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 20
    }

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. CONSULTA O CÉREBRO (RAG)
        brain_data = get_hub_context()
        context_str = json.dumps(brain_data, indent=2, ensure_ascii=False) if brain_data else "Manual local ativo."

        # 2. BUSCA DADOS DO REPORTE
        query = "SELECT r.*, m.filename, m.text_content, m.origin_interface FROM audio_error_reports r JOIN media_vault m ON r.media_id = m.id WHERE r.id = %s"
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        # 3. DOWNLOAD E TRANSCRIÇÃO (Whisper)
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        audio_res = requests.get(audio_url)
        audio_file_obj = io.BytesIO(audio_res.content)
        audio_file_obj.name = "audio.mp3"

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file_obj, language="pt")
        text_heard = transcription.text

        # 4. PROMPT ENRIQUECIDO COM RAG (O pulo do gato)
        system_prompt = f"""
        Você é o ALCINDO, Auditor de Skills do Voice Hub. 
        Você deve usar o CONHECIMENTO abaixo como sua única fonte de verdade.
        
        CONHECIMENTO ATUAL DO HUB (RAG):
        {context_str}
        """

        user_prompt = f"""
        Analise o seguinte erro reportado:
        - TEXTO ENVIADO: "{report['text_content']}"
        - O QUE A IA FALOU (OUVIDO): "{text_heard}"
        - RECLAMAÇÃO DO USUÁRIO: "{report['user_comment']}"

        Com base nas 'guidelines' e 'recent_memories' fornecidas no sistema, responda em JSON:
        {{
            "categoria": "FONETICA ou NEGOCIO ou PONTUACAO ou FALSO_POSITIVO",
            "confianca": 0-100,
            "diagnostico": "Explicação técnica curta",
            "sugestao": "Regra sugerida para o arquivo PHP (Regex ou Dicionário)"
        }}
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={ "type": "json_object" }
        )
        
        # 5. PROCESSAMENTO DE RESULTADOS
        usage = completion.usage
        alcindo_res = json.loads(completion.choices[0].message.content)
        
        # Cálculo de custo (GPT-4o)
        usd_rate = 5.40 # Fallback se não vier do banco
        cost_usd = ((usage.prompt_tokens / 1000) * 0.0025) + ((usage.completion_tokens / 1000) * 0.010)
        cost_brl = cost_usd * usd_rate
        processing_time = time.perf_counter() - start_time

        # 6. UPDATE NO BANCO
        update_sql = """
            UPDATE audio_error_reports SET 
            agent_transcription = %s, agent_diagnosis = %s, suggested_fix = %s,
            status = 'completed', prompt_tokens = %s, completion_tokens = %s, 
            total_tokens = %s, cost_usd = %s, cost_brl = %s, confidence_score = %s, 
            error_category = %s, processing_time = %s
            WHERE id = %s
        """
        cursor.execute(update_sql, (
            text_heard, alcindo_res['diagnostico'], alcindo_res['sugestao'],
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            cost_usd, cost_brl, alcindo_res['confianca'], alcindo_res['categoria'],
            processing_time, report_id
        ))
        conn.commit()

        return jsonify({"success": True, "alcindo_mode": "RAG_ACTIVE"})

    except Exception as e:
        logger.error(f"Erro Crítico Alcindo RAG: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))