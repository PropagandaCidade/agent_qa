# agent_qa.py - VERSÃO 1.0 - AGENTE DE AUDITORIA FONÉTICA
# LOCAL: Railway (Python Agent)
# DESCRIÇÃO: Ouve o áudio, compara com o texto original e sugere melhorias nas Skills.

import os
import requests
import mysql.connector
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# 1. CONFIGURAÇÕES
# Recomenda-se preencher via Variáveis de Ambiente no Railway
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        database=os.environ.get("DB_NAME")
    )

@app.route('/analyze', methods=['POST'])
def analyze_report():
    data = request.get_json()
    report_id = data.get('report_id')

    if not report_id:
        return jsonify({"error": "Report ID ausente"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 2. BUSCA DADOS DO REPORTE E DO ÁUDIO
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

        # Atualiza status para 'analyzing'
        cursor.execute("UPDATE audio_error_reports SET status = 'analyzing' WHERE id = %s", (report_id,))
        conn.commit()

        # 3. BAIXA O ÁUDIO DA HOSTINGER
        # Ajuste a URL para o caminho público do seu áudio
        folder = 'history' if report['origin_interface'] != 'studio' else 'audio_editor'
        audio_url = f"https://seusite.com.br/assets/audio/{folder}/{report['filename']}"
        audio_path = f"/tmp/{report['filename']}"
        
        response = requests.get(audio_url)
        with open(audio_path, 'wb') as f:
            f.write(response.content)

        # 4. TRANSCRIÇÃO (Whisper) - O Agente "Ouve"
        audio_file = open(audio_path, "rb")
        transcription = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            language="pt"
        )
        text_heard = transcription.text

        # 5. DIAGNÓSTICO (GPT-4o Audio) - O Agente "Compara e Pensa"
        # Comparamos o que foi ouvido com o texto que a Skill gerou
        prompt_analise = f"""
        Você é um auditor de fonética de IA. 
        Texto original enviado: "{report['text_content']}"
        O que a IA falou (transcrição): "{text_heard}"
        Comentário do usuário: "{report['user_comment']}"

        Analise se a IA errou a pronúncia, se ignorou alguma regra de preço (ex: falou 'reais' quando devia omitir) 
        ou se a pontuação está ruim. 
        Retorne um diagnóstico curto e uma sugestão de regra para o arquivo de Skills (Regex ou Dicionário).
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Seja um técnico em fonética e publicidade."},
                      {"role": "user", "content": prompt_analise}]
        )
        
        diagnosis = completion.choices[0].message.content

        # 6. ATUALIZA O BANCO NA HOSTINGER
        update_query = """
            UPDATE audio_error_reports 
            SET agent_transcription = %s, agent_diagnosis = %s, status = 'completed'
            WHERE id = %s
        """
        cursor.execute(update_query, (text_heard, diagnosis, report_id))
        conn.commit()

        # Limpeza
        os.remove(audio_path)

        return jsonify({"success": True, "diagnosis": diagnosis})

    except Exception as e:
        cursor.execute("UPDATE audio_error_reports SET status = 'pending' WHERE id = %s", (report_id,))
        conn.commit()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))