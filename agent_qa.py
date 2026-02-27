# agent_qa.py - VERSÃO 1.1 - AGENTE DE AUDITORIA (RESILIENTE)
# LOCAL: Railway

import os
import requests
import mysql.connector
from flask import Flask, request, jsonify
from openai import OpenAI
import logging

# Configuração de logs para você ver o erro no Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Função segura para pegar o banco
def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.environ.get("DB_HOST"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASS"),
            database=os.environ.get("DB_NAME"),
            connect_timeout=10 # Não deixa o app travar se o banco demorar
        )
    except Exception as e:
        logger.error(f"Falha na conexão com o Banco de Dados: {e}")
        return None

@app.route('/')
def home():
    return "Agente QA está online e aguardando chamadas do PHP."

@app.route('/analyze', methods=['POST'])
def analyze_report():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return jsonify({"error": "OPENAI_API_KEY não configurada no Railway"}), 500

    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        return jsonify({"error": "Report ID ausente"}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Não foi possível conectar ao banco da Hostinger. Verifique o IP Remoto."}), 500
    
    cursor = conn.cursor(dictionary=True)

    try:
        # Busca dados do reporte
        query = """
            SELECT r.*, m.filename, m.text_content, m.origin_interface 
            FROM audio_error_reports r
            JOIN media_vault m ON r.media_id = m.id
            WHERE r.id = %s
        """
        cursor.execute(query, (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({"error": "Reporte não encontrado no banco"}), 404

        # Inicia Auditoria
        client = OpenAI(api_key=api_key)
        
        # Pasta correta do áudio
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://propagandacidadeaudio.com.br/voice-hub/assets/audio/{folder}/{report['filename']}"
        
        logger.info(f"Analisando áudio: {audio_url}")

        # Download do áudio
        audio_res = requests.get(audio_url)
        if audio_res.status_code != 200:
            raise Exception(f"Não consegui baixar o áudio da Hostinger. Status: {audio_res.status_code}")

        audio_path = f"/tmp/{report['filename']}"
        with open(audio_path, 'wb') as f:
            f.write(audio_res.content)

        # Whisper (Ouvir)
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                language="pt"
            )
        
        text_heard = transcription.text

        # GPT-4o (Diagnosticar)
        prompt_analise = f"""
        Você é um auditor de fonética.
        Texto esperado: "{report['text_content']}"
        O que a voz falou: "{text_heard}"
        Erro relatado pelo usuário: "{report['user_comment']}"
        
        Compare e diga por que houve o erro e como ajustar a Skill fonética (Ex: sugerir pronúncia correta).
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Analista de áudio publicitário."},
                      {"role": "user", "content": prompt_analise}]
        )
        
        diagnosis = completion.choices[0].message.content

        # Salva resultado
        update_sql = "UPDATE audio_error_reports SET agent_transcription = %s, agent_diagnosis = %s, status = 'completed' WHERE id = %s"
        cursor.execute(update_sql, (text_heard, diagnosis, report_id))
        conn.commit()

        os.remove(audio_path)
        return jsonify({"success": True, "diagnosis": diagnosis})

    except Exception as e:
        logger.error(f"Erro no processamento: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    # O Railway fornece a porta via variável de ambiente
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)