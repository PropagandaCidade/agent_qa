# agent_qa.py - VERSÃO 2.3 - ALCINDO CIRÚRGICO (STRICT PROMPTING)
# LOCAL: Railway
# DESCRIÇÃO: Auditor Alcindo com prompt otimizado para auditoria de fonética e varejo.

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

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURAÇÃO ---
BRAIN_TOKEN = "HUB_SQUAD_SECRET_2024"
BRAIN_URL = "https://propagandacidadeaudio.com.br/voice-hub/admin/squad/brain/knowledge_bridge.php"

def get_hub_context():
    """Busca Regras e Memórias (RAG)"""
    try:
        url = f"{BRAIN_URL}?token={BRAIN_TOKEN}"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"[RAG] Erro: {e}")
    return None

@app.route('/analyze', methods=['POST'])
def analyze_report():
    start_time = time.perf_counter()
    logger.info(">>> [ALCINDO] Nova missão recebida!")
    
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        return jsonify({"error": "Report ID ausente"}), 400

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
        
        # 1. BUSCA CONTEXTO E DADOS
        brain_data = get_hub_context()
        context_str = json.dumps(brain_data, ensure_ascii=False) if brain_data else "Sem contexto RAG."

        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface, m.voice_name, r.user_comment 
            FROM audio_error_reports r 
            JOIN media_vault m ON r.media_id = m.id 
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({"error": "Não localizado"}), 404

        # 2. DOWNLOAD ÁUDIO
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        audio_res = requests.get(audio_url, timeout=40)
        
        audio_file_obj = io.BytesIO(audio_res.content)
        audio_file_obj.name = "input.mp3"

        # 3. TRANSCRIÇÃO WHISPER
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file_obj, language="pt")
        text_heard = transcription.text

        # 4. DIAGNÓSTICO GPT-4o (PROMPT CIRÚRGICO)
        system_prompt = f"""
        Você é o Alcindo, auditor sênior de fonética e conformidade de varejo.
        Sua missão é comparar o ROTEIRO ORIGINAL com o que foi OUVIDO pelo Whisper e validar a RECLAMAÇÃO do usuário.
        
        Contexto Técnico/Dicionário: {context_str}
        
        REGRAS DE ANÁLISE:
        1. Compare o Roteiro com o Texto Ouvido.
        2. Valide se a queixa do usuário tem fundamento técnico.
        3. Se houver erro, classifique em: FONETICA, NEGOCIO, PONTUACAO ou OUTRO. Se o áudio estiver correto, classifique como FALSO_POSITIVO.
        4. Retorne APENAS um JSON estrito com estas chaves: "diagnostico", "sugestao", "confianca" (0-100), "categoria".
        """

        user_prompt = f"""
        AUDITORIA #{report_id}:
        - Roteiro Original: "{report['text_content']}"
        - O que o Alcindo ouviu: "{text_heard}"
        - Reclamação do Usuário: "{report['user_comment']}"
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={ "type": "json_object" }
        )
        
        alcindo_res = json.loads(completion.choices[0].message.content)
        
        # 5. SALVAMENTO
        usage = completion.usage
        cost_usd = ((usage.prompt_tokens / 1000) * 0.0025) + ((usage.completion_tokens / 1000) * 0.010)
        cost_brl = cost_usd * 5.45
        proc_time = time.perf_counter() - start_time

        update_sql = """
            UPDATE audio_error_reports SET 
            agent_transcription = %s, agent_diagnosis = %s, suggested_fix = %s,
            status = 'completed', cost_usd = %s, cost_brl = %s, confidence_score = %s, 
            error_category = %s, processing_time = %s
            WHERE id = %s
        """
        cursor.execute(update_sql, (
            text_heard, alcindo_res.get('diagnostico'), alcindo_res.get('sugestao'),
            cost_usd, cost_brl, alcindo_res.get('confianca', 0),
            alcindo_res.get('categoria', 'OUTRO'), proc_time, report_id
        ))
        conn.commit()

        logger.info(f"--- MISSÃO #{report_id} CONCLUÍDA EM {proc_time:.2f}s ---")
        return jsonify({"success": True, "status": "completed"})

    except Exception as e:
        logger.error(f"!!! ERRO NO ALCINDO: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)