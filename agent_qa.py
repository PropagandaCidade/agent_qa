# agent_qa.py - VERSÃO 2.7 - TYPE SAFE JSON CONVERTER
# LOCAL: Railway
# DESCRIÇÃO: Auditor Alcindo com conversão forçada de tipos para evitar erro de banco.

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
        logger.error(f"[HUB] Erro: {e}")
        return None

@app.route('/analyze', methods=['POST'])
def analyze_report():
    start_time = time.perf_counter()
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id: return jsonify({"error": "ID ausente"}), 400

    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 30
    }

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        brain_data = get_data_from_hub(BRAIN_URL)
        profile_data = get_data_from_hub(PROFILE_URL)
        
        query = "SELECT r.*, m.filename, m.text_content, m.origin_interface, r.user_comment FROM audio_error_reports r JOIN media_vault m ON r.media_id = m.id WHERE r.id = %s"
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        # 3. TRANSCRIÇÃO WHISPER
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{'history' if report['origin_interface'] != 'studio' else 'audio_editor'}/{report['filename']}"
        audio_res = requests.get(audio_url, timeout=40)
        audio_file_obj = io.BytesIO(audio_res.content)
        audio_file_obj.name = "input.mp3"
        
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file_obj, language="pt", prompt=report['text_content'])
        text_heard = transcription.text

        # 4. DIAGNÓSTICO
        system_prompt = f"Você é o Alcindo. Perfil: {json.dumps(profile_data)}. Analise a reclamação do usuário comparando com o roteiro e o que foi ouvido. Retorne APENAS um JSON com chaves: 'diagnostico' (string), 'sugestao' (string), 'confianca' (int), 'categoria' (string)."
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Roteiro: {report['text_content']}\n\nOuvido: {text_heard}\n\nQueixa: {report['user_comment']}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        alcindo_res = json.loads(completion.choices[0].message.content)
        
        # FORÇA CONVERSÃO PARA STRING PARA EVITAR ERRO DE TIPO NO BANCO
        diag_str = str(alcindo_res.get('diagnostico', 'Sem diagnostico.'))
        sug_str = str(alcindo_res.get('sugestao', 'Manual'))
        cat_str = str(alcindo_res.get('categoria', 'OUTRO'))
        conf_int = int(alcindo_res.get('confianca', 0))
        
        update_sql = "UPDATE audio_error_reports SET agent_transcription = %s, agent_diagnosis = %s, suggested_fix = %s, status = 'completed', confidence_score = %s, error_category = %s WHERE id = %s"
        cursor.execute(update_sql, (text_heard, diag_str, sug_str, conf_int, cat_str, report_id))
        conn.commit()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Erro: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected(): cursor.close(); conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))