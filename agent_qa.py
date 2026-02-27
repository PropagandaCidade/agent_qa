# agent_qa.py - VERSÃO 2.1 - ALCINDO RAG (ADMIN RELOCATION FIX)
# LOCAL: Railway / GitHub
# DESCRIÇÃO: Auditor Alcindo com a URL do Cérebro atualizada para a pasta Admin.

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

# Configurações de Blindagem contra Proxies da Nuvem
os.environ['HTTP_PROXY'] = ""
os.environ['HTTPS_PROXY'] = ""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURAÇÃO DO SQUAD (ATUALIZADA) ---
BRAIN_TOKEN = "HUB_SQUAD_SECRET_2024"
# URL CORRIGIDA: Agora aponta para dentro da pasta /admin/
BRAIN_URL = "https://propagandacidadeaudio.com.br/voice-hub/admin/squad/brain/knowledge_bridge.php"

def get_hub_context():
    """Busca as Regras e Memórias (RAG) na nova pasta da Hostinger"""
    try:
        url = f"{BRAIN_URL}?token={BRAIN_TOKEN}"
        logger.info(f"Alcindo consultando Cérebro em: {url}")
        resp = requests.get(url, timeout=12)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.error(f"Erro ao acessar Cérebro: Status {resp.status_code}")
    except Exception as e:
        logger.error(f"Falha técnica na conexão RAG: {e}")
    return None

@app.route('/')
def home():
    return "Alcindo RAG v2.1 Online (Admin Path Active)."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    start_time = time.perf_counter()
    data = request.get_json()
    if not data: return jsonify({"error": "Payload vazio"}), 400
    
    report_id = data.get('report_id')
    if not report_id: return jsonify({"error": "Report ID ausente"}), 400

    # Configuração de Conexão (Pegando das Variáveis de Ambiente do Railway)
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

        # 1. RETRIEVING: Busca Contexto Dinâmico (RAG)
        brain_data = get_hub_context()
        context_str = json.dumps(brain_data, indent=2, ensure_ascii=False) if brain_data else "Aviso: Usando regras básicas locais."

        # 2. BUSCA DADOS DO REPORTE NO BANCO
        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface, m.voice_name 
            FROM audio_error_reports r 
            JOIN media_vault m ON r.media_id = m.id 
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({"error": "Reporte não encontrado no banco de dados."}), 404

        # 3. DOWNLOAD DO ÁUDIO PARA O ALCINDO OUVIR
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        logger.info(f"Baixando áudio para auditoria: {audio_url}")
        audio_res = requests.get(audio_url, timeout=30)
        audio_file_obj = io.BytesIO(audio_res.content)
        audio_file_obj.name = "audio.mp3"

        # 4. TRANSCRIÇÃO (WHISPER)
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), http_client=httpx.Client(trust_env=False))
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file_obj, language="pt")
        text_heard = transcription.text

        # 5. DIAGNÓSTICO ENRIQUECIDO (GPT-4o + RAG)
        system_instructions = f"""
        Você é o ALCINDO, Auditor de Skills. Sua fonte de verdade é o CONHECIMENTO RAG abaixo.
        ---
        CONHECIMENTO DO HUB:
        {context_str}
        """

        user_case = f"""
        ANALISAR REPORTE #{report_id}:
        - Locutor: {report['voice_name']}
        - Texto Enviado: "{report['text_content']}"
        - Áudio Transcrito: "{text_heard}"
        - Reclamação do Usuário: "{report['user_comment']}"

        Responda obrigatoriamente em JSON:
        {{
            "categoria": "FONETICA, NEGOCIO, PONTUACAO ou FALSO_POSITIVO",
            "confianca": 0-100,
            "diagnostico": "Explique o erro",
            "sugestao": "Regra PHP exata ou conserto"
        }}
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_case}
            ],
            response_format={ "type": "json_object" }
        )
        
        # 6. CÁLCULO DE MÉTRICAS E CUSTOS
        usage = completion.usage
        alcindo_res = json.loads(completion.choices[0].message.content)
        
        # Preços Fev/2024 GPT-4o
        cost_usd = ((usage.prompt_tokens / 1000) * 0.0025) + ((usage.completion_tokens / 1000) * 0.010)
        usd_rate = 5.40 # Fallback
        cost_brl = cost_usd * usd_rate
        proc_time = time.perf_counter() - start_time

        # 7. SALVAMENTO FINAL NO BANCO DA HOSTINGER
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
            proc_time, report_id
        ))
        conn.commit()

        return jsonify({"success": True, "agent": "Alcindo RAG 2.1"})

    except Exception as e:
        logger.error(f"ERRO ALCINDO: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)