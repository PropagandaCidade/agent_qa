# agent_qa.py - VERSÃO 1.9 - ALCINDO LIGHTWEIGHT (NO DEPENDENCIES)
# LOCAL: Railway
# DESCRIÇÃO: Removido pydub para compatibilidade total com Python 3.11/3.13

import os
import time
import requests
import mysql.connector
from flask import Flask, request, jsonify
import logging
import httpx
from openai import OpenAI
import io

# Configurações de Proxy Fix para Nuvem
os.environ['HTTP_PROXY'] = ""
os.environ['HTTPS_PROXY'] = ""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Preços Oficiais GPT-4o (por 1k tokens)
PRICE_INPUT_1K = 0.00250  
PRICE_OUTPUT_1K = 0.01000 

def get_hub_settings(cursor):
    """Busca status e cotação do dólar no banco"""
    cursor.execute("SELECT setting_key, setting_value FROM hub_settings")
    rows = cursor.fetchall()
    settings = {row['setting_key']: row['setting_value'] for row in rows}
    return settings

@app.route('/')
def home():
    return "Alcindo HQ Online - Modo Lightweight Ativo."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    start_time = time.perf_counter()
    data = request.get_json()
    if not data: return jsonify({"error": "No data"}), 400
    
    report_id = data.get('report_id')

    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 20
    }

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. VERIFICA STATUS
        settings = get_hub_settings(cursor)
        if settings.get('alcindo_status') == '0':
            return jsonify({"success": False, "error": "Alcindo Offline"}), 200

        usd_rate = float(settings.get('alcindo_usd_rate', 5.0))

        # 2. BUSCA REPORTE
        query = "SELECT r.*, m.filename, m.text_content, m.origin_interface FROM audio_error_reports r JOIN media_vault m ON r.media_id = m.id WHERE r.id = %s"
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        # 3. DOWNLOAD DO ÁUDIO
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        audio_res = requests.get(audio_url)
        audio_file_obj = io.BytesIO(audio_res.content)
        audio_file_obj.name = "audio.mp3" # Nome virtual para a OpenAI

        # 4. TRANSCRIÇÃO (Whisper Cloud)
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file_obj, language="pt")
        text_heard = transcription.text

        # 5. DIAGNÓSTICO (GPT-4o)
        prompt = f"""
        Você é o Alcindo, auditor técnico do Voice Hub.
        ESPERADO: "{report['text_content']}"
        OUVIDO: "{text_heard}"
        RECLAMAÇÃO: "{report['user_comment']}"

        Responda EXATAMENTE neste formato JSON:
        {{
            "categoria": "FONETICA ou NEGOCIO ou PONTUACAO ou FALSO_POSITIVO",
            "confianca": 0-100,
            "diagnostico": "texto curto",
            "sugestao": "regra de skill ou ajuste"
        }}
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Auditor de áudio JSON."}, {"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        
        # 6. MÉTRICAS
        usage = completion.usage
        cost_usd = ((usage.prompt_tokens / 1000) * PRICE_INPUT_1K) + ((usage.completion_tokens / 1000) * PRICE_OUTPUT_1K)
        cost_brl = cost_usd * usd_rate
        processing_time = time.perf_counter() - start_time
        
        import json
        alcindo_res = json.loads(completion.choices[0].message.content)

        # 7. UPDATE NO BANCO (audio_duration fica 0 pois pydub foi removido)
        update_sql = """
            UPDATE audio_error_reports SET 
            agent_transcription = %s, agent_diagnosis = %s, suggested_fix = %s,
            status = 'completed', prompt_tokens = %s, completion_tokens = %s, 
            total_tokens = %s, cost_usd = %s, cost_brl = %s, confidence_score = %s, 
            error_category = %s, processing_time = %s, audio_duration = 0.00
            WHERE id = %s
        """
        cursor.execute(update_sql, (
            text_heard, alcindo_res['diagnostico'], alcindo_res['sugestao'],
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            cost_usd, cost_brl, alcindo_res['confianca'], alcindo_res['categoria'],
            processing_time, report_id
        ))
        conn.commit()

        return jsonify({"success": True, "alcindo": "Audit completed"})

    except Exception as e:
        logger.error(f"Erro Crítico Alcindo: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))