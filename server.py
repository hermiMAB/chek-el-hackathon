from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import AzureOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-02-01"
)

# Serve frontend
@app.route('/')
def serve_index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    try:
        return send_from_directory('public', path)
    except FileNotFoundError:
        return send_from_directory('public', 'index.html')  # For SPA routing

# Backend API routes
@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message')
    if not message:
        return jsonify({"response": "No message provided"}), 400
    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": message}],
            max_tokens=500
        )
        return jsonify({"response": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"response": f"Error: {str(e)}"}), 500

@app.route('/api/quiz', methods=['POST'])
def quiz():
    data = request.get_json()
    topic = data.get('topic')
    if not topic:
        return jsonify({"quiz": "No topic provided"}), 400
    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": f"Generate a quiz with 3 multiple-choice questions on {topic}."}],
            max_tokens=500
        )
        return jsonify({"quiz": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"quiz": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))