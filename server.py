from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import logging

app = Flask(__name__)
CORS(app)
load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-02-01"  # Use stable version
)
model = os.getenv("AZURE_OPENAI_MODEL")

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    message = data.get('message')
    if not message:
        logger.error("No message provided")
        return jsonify({'error': 'No message provided'}), 400
    try:
        logger.debug(f"Sending chat request for: {message}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful study assistant."},
                {"role": "user", "content": f"Explain {message} in simple terms for a university student."}
            ],
            max_tokens=500
        )
        content = response.choices[0].message.content
        logger.debug(f"Chat response: {content}")
        return jsonify({'response': content})
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/quiz', methods=['POST'])
def quiz():
    data = request.json
    topic = data.get('topic')
    if not topic:
        logger.error("No topic provided")
        return jsonify({'error': 'No topic provided'}), 400
    try:
        logger.debug(f"Sending quiz request for: {topic}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a quiz generator."},
                {"role": "user", "content": f"Generate 3 narrative-style multiple-choice questions about {topic} for university students, formatted as: Question: [text]\nA) [option]\nB) [option]\nC) [option]\nD) [option]\nAnswer: [letter]"}
            ],
            max_tokens=1000
        )
        content = response.choices[0].message.content
        logger.debug(f"Quiz response: {content}")
        return jsonify({'quiz': content})
    except Exception as e:
        logger.error(f"Quiz error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)