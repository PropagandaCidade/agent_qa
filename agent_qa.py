# agent_qa.py - VERSÃO 2.8 - BLINDAGEM TOTAL DE TIPOS
# LOCAL: Railway
# DESCRIÇÃO: Auditor Alcindo com serialização forçada para evitar erros de banco.

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

BRAIN_TOKEN = "HUB_SQUAD_SECRET_2024"
BRAIN_URL = "https://propagandacidadeaudio.com.br/voice-hub/admin/squad/brain/knowledge_bridge.php"
PROFILE_URL = "https://propagandacidadeaudio.com.br/voice-hub/admin/squad/brain/alcindo_profile.json"

def get_data_from_hub(url):
    try:
        url_with_token = f"{url}?token={BRAIN_TOKEN}"
        resp = requests.get(url_with_token, timeout=15)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        return None

@app.route('/analyze', methods=['POST'])
def analyze_report():
    data = request.get_json()
    report_id = data.get('report_id')
    if not report_id: return jsonify({"error": "ID ausente"}), 400

    db_config = {
        'host': os.environ.get("DB_HOST"), 'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"), 'database': os.environ.get("DB_NAME"),
        'connect_timeout': 30
    }

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 1. BUSCA DADOS
        cursor.execute("SELECT r.*, m.filename, m.text_content, m.origin_interface, r.user_comment FROM audio_error_reports r JOIN media_vault m ON r.media_id = m.id WHERE r.id = %s", (report_id,))
        report = cursor.fetchone()

        # 2. TRANSCRIÇÃO
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{'history' if report['origin_interface'] != 'studio' else 'audio_editor'}/{report['filename']}"
        audio_res = requests.get(audio_url, timeout=40)
        audio_file = io.BytesIO(audio_res.content)
        audio_file.name = "input.mp3"
        
        text_heard = client.audio.transcriptions.create(model="whisper-1", file=audio_file, language="pt", prompt=report['text_content']).text

        # 3. DIAGNÓSTICO COM SERIALIZAÇÃO FORÇADA
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Você é o Alcindo. Retorne APENAS um JSON com estas 4 chaves: 'diagnostico' (string), 'sugestao' (string), 'confianca' (int), 'categoria' (string)."},
                {"role": "user", "content": f"Roteiro: {report['text_content']}\nOuvido: {text_heard}\nReclamação: {report['user_comment']}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        res = json.loads(completion.choices[0].message.content)
        
        # FUNÇÃO PARA GARANTIR STRING
        def ensure_str(val):
            if isinstance(val, list): return " | ".join(map(str, val))
            if isinstance(val, dict): return json.dumps(val, ensure_ascii=False)
            return str(val)

        diag = ensure_str(res.get('diagnostico', 'Sem diagnostico.'))
        sug = ensure_str(res.get('sugestao', 'Manual'))
        cat = str(res.get('categoria', 'OUTRO'))
        conf = int(res.get('confianca', 0))
        
        cursor.execute("UPDATE audio_error_reports SET agent_transcription = %s, agent_diagnosis = %s, suggested_fix = %s, status = 'completed', confidence_score = %s, error_category = %s WHERE id = %s", 
                       (text_heard, diag, sug, conf, cat, report_id))
        conn.commit()
        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Erro Crítico: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected(): cursor.close(); conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))