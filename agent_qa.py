# agent_qa.py - VERSÃO 1.4 - TOTAL PROXY BYPASS
# LOCAL: Railway

import os
import requests
import mysql.connector
from flask import Flask, request, jsonify
import logging

# Bibliotecas para o novo cliente blindado
import httpx
from openai import OpenAI

# Configuração de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Agente QA Online - Versão 1.4 (Blindada)"

@app.route('/analyze', methods=['POST'])
def analyze_report():
    logger.info(">>> Recebendo solicitação de análise (POST /analyze)")
    
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        return jsonify({"error": "Report ID ausente"}), 400

    api_key = os.environ.get("OPENAI_API_KEY")
    
    # 1. INICIALIZAÇÃO BLINDADA DA OPENAI
    # Criamos um cliente HTTP que ignora explicitamente qualquer proxy do sistema
    http_client = httpx.Client(proxies={}) 
    client = OpenAI(api_key=api_key, http_client=http_client)

    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 20
    }

    try:
        # 2. CONEXÃO COM O BANCO
        logger.info(f"Conectando ao banco na Hostinger: {db_config['host']}")
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 3. BUSCA DADOS DO REPORTE
        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface 
            FROM audio_error_reports r
            JOIN media_vault m ON r.media_id = m.id
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({"error": "Reporte não encontrado"}), 404

        # 4. DOWNLOAD DO ÁUDIO
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        logger.info(f"Baixando áudio: {audio_url}")
        audio_res = requests.get(audio_url, timeout=30)
        
        if audio_res.status_code != 200:
            raise Exception(f"Falha ao baixar áudio. Status: {audio_res.status_code}")

        audio_path = f"/tmp/{report['filename']}"
        with open(audio_path, 'wb') as f:
            f.write(audio_res.content)

        # 5. TRANSCRIÇÃO (WHISPER)
        logger.info("Iniciando transcrição Whisper...")
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file, 
                language="pt"
            )
        
        text_heard = transcription.text
        logger.info(f"Ouvido: {text_heard}")

        # 6. DIAGNÓSTICO (GPT-4o)
        logger.info("Solicitando diagnóstico ao GPT-4o...")
        prompt_analise = f"""
        Você é um especialista em fonética.
        Texto Original: {report['text_content']}
        O que a voz falou: {text_heard}
        Comentário do usuário: {report['user_comment']}

        Compare e identifique erros de pronúncia ou siglas (como SP lido errado).
        Retorne um diagnóstico técnico curto e uma sugestão de correção.
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Auditor técnico fonético."},
                      {"role": "user", "content": prompt_analise}]
        )
        diagnosis = completion.choices[0].message.content

        # 7. SALVA NO BANCO
        update_sql = "UPDATE audio_error_reports SET agent_transcription = %s, agent_diagnosis = %s, status = 'completed' WHERE id = %s"
        cursor.execute(update_sql, (text_heard, diagnosis, report_id))
        conn.commit()

        logger.info(f"Sucesso! Reporte {report_id} finalizado.")
        
        if os.path.exists(audio_path):
            os.remove(audio_path)

        return jsonify({"success": True, "diagnosis": diagnosis})

    except Exception as e:
        logger.error(f"ERRO CRÍTICO: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)