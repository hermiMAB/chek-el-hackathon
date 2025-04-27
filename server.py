print("Starting server.py...")
import os
import uuid
import base64
from dotenv import load_dotenv
try:
    print("Loading environment variables...")
    load_dotenv()
    print("Environment variables loaded:", {
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_KEY": "SET" if os.getenv("AZURE_OPENAI_KEY") else "NOT SET",
        "COSMOS_URL": os.getenv("COSMOS_URL"),
        "SEARCH_ENDPOINT": os.getenv("SEARCH_ENDPOINT")
    })
except Exception as e:
    print(f"Error loading .env: {e}")

try:
    print("Importing Flask and dependencies...")
    from flask import Flask, request, jsonify, send_from_directory
    from flask_cors import CORS
    from flask_socketio import SocketIO, emit
except Exception as e:
    print(f"Error importing Flask dependencies: {e}")

try:
    print("Importing Azure dependencies...")
    from openai import AzureOpenAI
    from azure.cosmos import CosmosClient
    from azure.search.documents import SearchClient
    from azure.core.credentials import AzureKeyCredential
    import azure.cognitiveservices.speech as speechsdk
except Exception as e:
    print(f"Error importing Azure dependencies: {e}")

print("Initializing Flask app...")
app = Flask(__name__, static_folder='public', static_url_path='')
app.config['SECRET_KEY'] = 'secret!'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', transports=['polling'])

# Azure OpenAI Client
try:
    print("Initializing Azure OpenAI client...")
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_KEY"),
        api_version="2024-02-01"
    )
except Exception as e:
    print(f"Error initializing Azure OpenAI client: {e}")

# Azure Cosmos DB Client
try:
    print("Initializing Cosmos DB client...")
    cosmos_client = CosmosClient(os.getenv("COSMOS_URL"), os.getenv("COSMOS_KEY"))
    
    # Create or get database
    database_name = "CheckElDB"
    try:
        database = cosmos_client.create_database_if_not_exists(id=database_name)
        print(f"Database '{database_name}' created or already exists.")
    except Exception as e:
        print(f"Error creating database: {e}")
        raise e

    # Create or get Scores container
    scores_container_name = "Scores"
    try:
        scores_container = database.create_container_if_not_exists(
            id=scores_container_name,
            partition_key={"paths": ["/id"], "kind": "Hash"},
            offer_throughput=400
        )
        print(f"Container '{scores_container_name}' created or already exists.")
    except Exception as e:
        print(f"Error creating Scores container: {e}")
        raise e

    # Create or get Notes container
    notes_container_name = "Notes"
    try:
        notes_container = database.create_container_if_not_exists(
            id=notes_container_name,
            partition_key={"paths": ["/id"], "kind": "Hash"},
            offer_throughput=400
        )
        print(f"Container '{notes_container_name}' created or already exists.")
    except Exception as e:
        print(f"Error creating Notes container: {e}")
        raise e

except Exception as e:
    print(f"Error initializing Cosmos DB client: {e}")

# Azure AI Search Client
try:
    print("Initializing Azure AI Search client...")
    search_client = SearchClient(os.getenv("SEARCH_ENDPOINT"), "notes-index", AzureKeyCredential(os.getenv("SEARCH_KEY")))
except Exception as e:
    print(f"Error initializing Azure AI Search client: {e}")

# Serve multiple pages
@app.route('/')
@app.route('/welcome')
def serve_welcome():
    return send_from_directory('public', 'welcome.html')

@app.route('/ask-ai')
def serve_ask_ai():
    return send_from_directory('public', 'ask-ai.html')

@app.route('/quiz')
def serve_quiz():
    return send_from_directory('public', 'quiz.html')

@app.route('/<path:path>')
def serve_static(path):
    try:
        return send_from_directory('public', path)
    except FileNotFoundError:
        return send_from_directory('public', 'welcome.html')

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('gamification_update', {'message': 'Welcome to Chek El!'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# API Endpoints
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

@app.route('/api/save-score', methods=['POST'])
def save_score():
    data = request.get_json()
    user_id = data.get('user_id', str(uuid.uuid4()))
    points = data.get('points')
    quiz_count = data.get('quiz_count')
    try:
        print(f"Attempting to save score for user_id: {user_id}, points: {points}, quiz_count: {quiz_count}")
        scores_container.upsert_item({
            'id': user_id,
            'points': points,
            'quiz_count': quiz_count
        })
        print("Score saved successfully")
        badges = []
        if points >= 30:
            badges.append("Quiz Novice")
        if points >= 90:
            badges.append("Quiz Master")
        # Emit to all connected clients using namespace
        socketio.emit('gamification_update', {
            'user_id': user_id,
            'points': points,
            'badges': badges,
            'message': f"User {user_id[:8]} earned {points} points and {', '.join(badges) or 'no badges'}!"
        }, namespace='/')
        return jsonify({"status": "saved", "badges": badges})
    except Exception as e:
        print(f"Cosmos DB error in save_score: {str(e)}")
        return jsonify({"status": f"Error: {str(e)}"}), 500

# Text-to-Speech
@app.route('/api/text-to-speech', methods=['POST'])
def text_to_speech():
    try:
        data = request.get_json()
        text = data.get('text')
        if not text:
            return jsonify({"error": "No text provided"}), 400

        speech_config = speechsdk.SpeechConfig(
            subscription=os.getenv("SPEECH_KEY"),
            region=os.getenv("SPEECH_REGION")
        )
        speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            return jsonify({"audio": audio_base64})
        else:
            return jsonify({"error": "Text-to-speech synthesis failed"}), 500
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Speech-to-Text
@app.route('/api/speech-to-text', methods=['POST'])
def speech_to_text():
    try:
        audio_file = request.files['audio']
        if not audio_file:
            return jsonify({"error": "No audio file provided"}), 400

        speech_config = speechsdk.SpeechConfig(
            subscription=os.getenv("SPEECH_KEY"),
            region=os.getenv("SPEECH_REGION")
        )
        audio_config = speechsdk.audio.AudioConfig(stream=speechsdk.audio.PushAudioInputStream())
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        stream = speechsdk.audio.PushAudioInputStream()
        audio_data = audio_file.read()
        stream.write(audio_data)
        stream.close()

        result = recognizer.recognize_once()
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return jsonify({"text": result.text})
        else:
            return jsonify({"error": "Speech-to-text failed"}), 500
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

@app.route('/api/save-note', methods=['POST'])
def save_note():
    data = request.get_json()
    note = data.get('note')
    topic = data.get('topic')
    try:
        tag_response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": f"Generate 3 tags for the topic: {topic}"}],
            max_tokens=50
        )
        tags = tag_response.choices[0].message.content.split(',')
        note_id = str(uuid.uuid4())
        notes_container.upsert_item({
            'id': note_id,
            'note': note,
            'topic': topic,
            'tags': tags
        })
        search_client.upload_documents([{
            '@search.action': 'upload',
            'id': note_id,
            'content': note,
            'topic': topic,
            'tags': tags
        }])
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"status": f"Error: {str(e)}"}), 500

@app.route('/api/get-notes', methods=['GET'])
def get_notes():
    try:
        notes = list(notes_container.read_all_items())
        return jsonify(notes)
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=False)