# agent_qa.py - VERSÃO 2.2 - ALCINDO RAG (DEBUG MODE)
# LOCAL: Railway
# DESCRIÇÃO: Auditor Alcindo com logs ultra-detalhados para detectar travamentos.

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

# Configuração de Logs para aparecerem no painel do Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURAÇÃO DO SQUAD ---
BRAIN_TOKEN = "HUB_SQUAD_SECRET_2024"
# Verifique se este domínio está correto e acessível
BRAIN_URL = "https://propagandacidadeaudio.com.br/voice-hub/admin/squad/brain/knowledge_bridge.php"

def get_hub_context():
    """Busca as Regras e Memórias (RAG) na Hostinger"""
    try:
        url = f"{BRAIN_URL}?token={BRAIN_TOKEN}"
        logger.info(f"[RAG] Consultando Cérebro em: {url}")
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            logger.info("[RAG] Contexto recebido com sucesso.")
            return resp.json()
        else:
            logger.error(f"[RAG] Falha: Status {resp.status_code}")
    except Exception as e:
        logger.error(f"[RAG] Erro técnico de conexão: {e}")
    return None

@app.route('/')
def home():
    return "Alcindo v2.2 - Sistema de Auditoria Ativo."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    start_time = time.perf_counter()
    logger.info(">>> [ALCINDO] Nova missão recebida!")
    
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        logger.error("ERRO: Pedido sem report_id.")
        return jsonify({"error": "Report ID ausente"}), 400

    # Credenciais do Banco (Variáveis de Ambiente do Railway)
    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 30
    }

    try:
        # 1. CONEXÃO COM O BANCO
        logger.info(f"[BANCO] Conectando ao host {db_config['host']}...")
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 2. BUSCA CONTEXTO RAG
        brain_data = get_hub_context()
        context_str = json.dumps(brain_data, indent=2, ensure_ascii=False) if brain_data else "Sem contexto RAG."

        # 3. BUSCA DADOS DO REPORTE
        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface, m.voice_name 
            FROM audio_error_reports r 
            JOIN media_vault m ON r.media_id = m.id 
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            logger.error(f"[BANCO] Reporte {report_id} não encontrado.")
            return jsonify({"error": "Não localizado"}), 404

        # 4. DOWNLOAD DO ÁUDIO
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        logger.info(f"[ÁUDIO] Baixando: {audio_url}")
        audio_res = requests.get(audio_url, timeout=40)
        
        if audio_res.status_code != 200:
            raise Exception(f"Erro ao baixar áudio. Status: {audio_res.status_code}")

        audio_file_obj = io.BytesIO(audio_res.content)
        audio_file_obj.name = "input.mp3"

        # 5. INTELIGÊNCIA IA (Whisper + GPT-4o)
        logger.info("[IA] Iniciando Transcrição Whisper...")
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file_obj, language="pt")
        text_heard = transcription.text
        logger.info(f"[IA] Alcindo ouviu: {text_heard[:100]}...")

        logger.info("[IA] Solicitando diagnóstico ao GPT-4o...")
        prompt_system = f"Você é o ALCINDO, auditor do Voice Hub. Use este contexto RAG: {context_str}"
        prompt_user = f"Reporte #{report_id}. Esperado: {report['text_content']}. Ouvido: {text_heard}. Reclamação: {report['user_comment']}. Responda em JSON."

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            response_format={ "type": "json_object" }
        )
        
        alcindo_res = json.loads(completion.choices[0].message.content)
        
        # 6. CÁLCULOS E CUSTOS
        usage = completion.usage
        cost_usd = ((usage.prompt_tokens / 1000) * 0.0025) + ((usage.completion_tokens / 1000) * 0.010)
        cost_brl = cost_usd * 5.45 # Cotação manual caso o banco falhe
        proc_time = time.perf_counter() - start_time

        # 7. SALVAMENTO FINAL (PONTO CRÍTICO)
        logger.info("[BANCO] Gravando diagnóstico final...")
        update_sql = """
            UPDATE audio_error_reports SET 
            agent_transcription = %s, agent_diagnosis = %s, suggested_fix = %s,
            status = 'completed', prompt_tokens = %s, completion_tokens = %s, 
            total_tokens = %s, cost_usd = %s, cost_brl = %s, confidence_score = %s, 
            error_category = %s, processing_time = %s
            WHERE id = %s
        """
        cursor.execute(update_sql, (
            text_heard, alcindo_res.get('diagnostico'), alcindo_res.get('sugestao'),
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            cost_usd, cost_brl, alcindo_res.get('confianca', 0),
            alcindo_res.get('categoria', 'OUTRO'), proc_time, report_id
        ))
        conn.commit()

        logger.info(f"--- MISSÃO #{report_id} CONCLUÍDA EM {proc_time:.2f}s ---")
        return jsonify({"success": True, "status": "completed"})

    except Exception as e:
        logger.error(f"!!! ERRO NO ALCINDO: {str(e)}")
        # Tenta voltar o status para pendente em caso de erro para você poder tentar de novo
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)