# agent_qa.py - VERSÃO 1.3 - OPENAI PROXY FIX
# LOCAL: Railway

import os
import requests
import mysql.connector
from flask import Flask, request, jsonify
from openai import OpenAI
import logging

# IMPORTANTE: Desabilita proxies do sistema que causam erro na biblioteca OpenAI v1.0+
os.environ['HTTP_PROXY'] = ""
os.environ['HTTPS_PROXY'] = ""
os.environ['http_proxy'] = ""
os.environ['https_proxy'] = ""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Agente QA Online e pronto para analisar."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    logger.info(">>> Recebendo solicitação de análise (POST /analyze)")
    
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        return jsonify({"error": "Report ID ausente"}), 400

    api_key = os.environ.get("OPENAI_API_KEY")
    
    db_config = {
        'host': os.environ.get("DB_HOST"),
        'user': os.environ.get("DB_USER"),
        'password': os.environ.get("DB_PASS"),
        'database': os.environ.get("DB_NAME"),
        'connect_timeout': 20
    }

    try:
        # 1. TESTA CONEXÃO COM O BANCO
        logger.info(f"Conectando ao banco na Hostinger: {db_config['host']}")
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 2. BUSCA DADOS DO REPORTE
        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface 
            FROM audio_error_reports r
            JOIN media_vault m ON r.media_id = m.id
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            logger.error(f"Reporte {report_id} não encontrado.")
            return jsonify({"error": "Reporte não encontrado"}), 404

        # 3. INICIALIZA OPENAI (Sem proxies para evitar o erro de 'proxies' argument)
        client = OpenAI(api_key=api_key)
        
        # 4. DOWNLOAD DO ÁUDIO
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        logger.info(f"Baixando áudio para transcrição: {audio_url}")
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
        logger.info(f"Ouvido pelo Agente: {text_heard}")

        # 6. DIAGNÓSTICO (GPT-4o)
        logger.info("Solicitando diagnóstico ao GPT-4o...")
        prompt_analise = f"""
        Você é um especialista em fonética e locução publicitária.
        Texto Original: {report['text_content']}
        Transcrição do Áudio: {text_heard}
        Reclamação do Usuário: {report['user_comment']}

        Compare o texto original com o áudio. 
        1. Identifique palavras faladas de forma errada.
        2. Verifique se siglas (como SP, RJ) foram lidas corretamente.
        3. Dê uma sugestão de como ajustar o texto ou a Skill (Ex: 'Escreva São Paulo em vez de SP').
        Retorne um diagnóstico técnico e direto.
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Auditor de voz neutro e técnico."},
                      {"role": "user", "content": prompt_analise}]
        )
        diagnosis = completion.choices[0].message.content

        # 7. SALVA NO BANCO
        update_sql = "UPDATE audio_error_reports SET agent_transcription = %s, agent_diagnosis = %s, status = 'completed' WHERE id = %s"
        cursor.execute(update_sql, (text_heard, diagnosis, report_id))
        conn.commit()

        logger.info(f"Sucesso! Reporte {report_id} auditado.")
        
        if os.path.exists(audio_path):
            os.remove(audio_path)

        return jsonify({"success": True, "diagnosis": diagnosis})

    except Exception as e:
        logger.error(f"FALHA NO PROCESSO: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)