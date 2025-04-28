import os
import uuid
import json
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from openai import AzureOpenAI
from dotenv import load_dotenv
import bcrypt
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
try:
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except Exception as e:
    logger.error(f"Failed to load .env file: {e}")
    raise

# Debug environment variables
COSMOS_URI = os.getenv('COSMOS_URI')
COSMOS_KEY = os.getenv('COSMOS_KEY')
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_MODEL", "gpt-4o")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")

logger.debug(f"Loaded COSMOS_URI: {COSMOS_URI}")
logger.debug(f"Loaded COSMOS_KEY: {COSMOS_KEY}")
logger.debug(f"Loaded AZURE_OPENAI_ENDPOINT: {AZURE_OPENAI_ENDPOINT}")
logger.debug(f"Loaded AZURE_OPENAI_API_KEY: {AZURE_OPENAI_API_KEY}")
logger.debug(f"Loaded AZURE_OPENAI_MODEL: {AZURE_OPENAI_MODEL}")
logger.debug(f"Loaded SECRET_KEY: {SECRET_KEY}")

if not all([COSMOS_URI, COSMOS_KEY]):
    logger.error("Missing COSMOS_URI or COSMOS_KEY in environment variables.")
    raise ValueError("Missing COSMOS_URI or COSMOS_KEY in environment variables. Please check your .env file.")

if not all([AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_MODEL]):
    logger.error("Missing AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, or AZURE_OPENAI_MODEL in environment variables.")
    raise ValueError("Missing AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, or AZURE_OPENAI_MODEL in environment variables. Please check your .env file.")

# Initialize Flask app
app = Flask(__name__, static_folder='public')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
logger.info("Flask app and SocketIO initialized.")

# Debug static file serving
@app.route('/css/<path:filename>')
def serve_css(filename):
    logger.debug(f"Serving CSS: public/css/{filename}")
    return send_from_directory('public/css', filename)

@app.route('/js/<path:filename>')
def serve_js(filename):
    logger.debug(f"Serving JS: public/js/{filename}")
    return send_from_directory('public/js', filename)

# Initialize Azure Cosmos DB
try:
    cosmos_client = CosmosClient(COSMOS_URI, COSMOS_KEY)
    database = cosmos_client.get_database_client('CheckElDB')
    logger.info("Cosmos DB client initialized.")
except Exception as e:
    logger.error(f"Failed to initialize Cosmos DB client: {e}")
    raise

# Initialize containers
containers = [
    ('Users', {"paths": ["/id"], "kind": "Hash"}),
    ('Notes', {"paths": ["/user_id"], "kind": "Hash"}),
    ('Scores', {"paths": ["/user_id"], "kind": "Hash"}),
    ('Searches', {"paths": ["/user_id"], "kind": "Hash"}),
    ('Feedback', {"paths": ["/user_id"], "kind": "Hash"}),
    ('LearningPlans', {"paths": ["/user_id"], "kind": "Hash"}),
    ('ChatMessages', {"paths": ["/user_id"], "kind": "Hash"}),
]

for container_id, partition_key in containers:
    try:
        container = database.create_container_if_not_exists(
            id=container_id,
            partition_key=partition_key,
            offer_throughput=400
        )
        logger.info(f"{container_id} container created or already exists.")
        globals()[f"{container_id.lower()}_container"] = container
    except Exception as e:
        logger.error(f"Error creating {container_id} container: {e}")
        raise

# Initialize Azure OpenAI
try:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version="2023-05-15",
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    logger.info("Azure OpenAI client initialized.")
except Exception as e:
    logger.error(f"Failed to initialize Azure OpenAI client: {e}")
    raise

# Simple function to check question similarity (basic string comparison)
def is_question_similar(new_question, existing_questions):
    new_text = new_question['question'].lower().strip()
    for existing in existing_questions:
        existing_text = existing['question'].lower().strip()
        new_words = set(new_text.split())
        existing_words = set(existing_text.split())
        common_words = len(new_words.intersection(existing_words))
        if common_words / max(len(new_words), len(existing_words)) > 0.7:
            return True
    return False

# Register a new user
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400
        existing_user = users_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": username}],
            enable_cross_partition_query=True
        )
        existing_user = next(existing_user, None)
        if existing_user:
            return jsonify({"error": "User already exists"}), 400
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user = {
            "id": str(uuid.uuid4()),
            "username": username,
            "password": hashed_password
        }
        users_container.upsert_item(user)
        logger.info(f"Registered user: {username}")
        return jsonify({"status": "User registered"})
    except Exception as e:
        logger.error(f"Error in register endpoint: {e}")
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500

# User login
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        logger.debug(f"Login attempt - Username: {username}")
        user = users_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": username}],
            enable_cross_partition_query=True
        )
        user = next(user, None)
        logger.debug(f"User found: {user}")
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            logger.info("Login successful")
            session['user_id'] = user['id']
            session['username'] = user['username']
            return jsonify({"status": "success"})
        logger.warning("Login failed - Invalid credentials")
        return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        logger.error(f"Error in login endpoint: {e}")
        return jsonify({"error": f"Login failed: {str(e)}"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        session.pop('user_id', None)
        session.pop('username', None)
        logger.info("User logged out")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error in logout endpoint: {e}")
        return jsonify({"error": f"Logout failed: {str(e)}"}), 500

# Check authentication status
@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    try:
        if 'user_id' in session:
            logger.debug("User is authenticated")
            return jsonify({"authenticated": True})
        logger.debug("User is not authenticated")
        return jsonify({"authenticated": False})
    except Exception as e:
        logger.error(f"Error in check-auth endpoint: {e}")
        return jsonify({"error": f"Auth check failed: {str(e)}"}), 500

# Get username
@app.route('/api/get-username', methods=['GET'])
def get_username():
    try:
        if 'username' in session:
            logger.debug(f"Returning username: {session['username']}")
            return jsonify({"username": session['username']})
        logger.warning("No username in session")
        return jsonify({"error": "Not logged in"}), 401
    except Exception as e:
        logger.error(f"Error in get-username endpoint: {e}")
        return jsonify({"error": f"Failed to get username: {str(e)}"}), 500

# Community chat messages
@app.route('/api/community-chat', methods=['GET'])
def get_chat_messages():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for community-chat")
        return jsonify({"error": "Not logged in"}), 401
    try:
        messages = list(chatmessages_container.query_items(
            query="SELECT * FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT 50",
            enable_cross_partition_query=True
        ))
        logger.debug(f"Fetched {len(messages)} chat messages")
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Error fetching chat messages: {e}")
        return jsonify({"error": f"Failed to load messages: {str(e)}"}), 500

# Summarize chat
@app.route('/api/summarize-chat', methods=['POST'])
def summarize_chat():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for summarize-chat")
        return jsonify({"error": "Not logged in"}), 401
    try:
        messages = list(chatmessages_container.query_items(
            query="SELECT * FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT 50",
            enable_cross_partition_query=True
        ))
        if not messages:
            logger.debug("No messages to summarize")
            return jsonify({"summary": "No messages to summarize"})
        chat_text = "\n".join([f"{msg['username']}: {msg['message']}" for msg in messages])
        prompt = f"""
        Summarize the following community chat conversation in 50-100 words, capturing the main topics, themes, or questions discussed. Ensure the summary is concise, clear, and suitable for users learning about the conversation:
        {chat_text}
        """
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        summary = response.choices[0].message.content
        logger.debug("Chat summarized successfully")
        return jsonify({"summary": summary})
    except Exception as e:
        logger.error(f"Error summarizing chat: {e}")
        return jsonify({"error": f"Failed to summarize chat: {str(e)}"}), 500

# Serve static files
@app.route('/')
def serve_index():
    logger.debug("Serving welcome.html")
    return send_from_directory('public', 'welcome.html')

@app.route('/welcome')
def serve_welcome():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving welcome.html")
    return send_from_directory('public', 'welcome.html')

@app.route('/login')
def serve_login():
    logger.debug("Serving login.html")
    return send_from_directory('public', 'login.html')

@app.route('/ask-ai')
def serve_ask_ai():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving ask-ai.html")
    return send_from_directory('public', 'ask-ai.html')

@app.route('/quiz')
def serve_quiz():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving quiz.html")
    return send_from_directory('public', 'quiz.html')

@app.route('/community')
def serve_community():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving community.html")
    return send_from_directory('public', 'community.html')

@app.route('/feedback')
def serve_feedback():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving feedback.html")
    return send_from_directory('public', 'feedback.html')

@app.route('/learning-planner')
def serve_learning_planner():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving learning-planner.html")
    return send_from_directory('public', 'learning-planner.html')

@app.route('/notes')
def serve_notes():
    if 'user_id' not in session:
        logger.debug("Not logged in, serving login.html")
        return send_from_directory('public', 'login.html')
    logger.debug("Serving notes.html")
    return send_from_directory('public', 'notes.html')

# Chat endpoint
@app.route('/api/chat', methods=['POST'])
def chat():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for chat")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        message = data.get('message')
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": message}],
            max_tokens=500
        )
        reply = response.choices[0].message.content
        searches_container.upsert_item({
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'query': message,
            'response': reply
        })
        logger.debug(f"Chat response generated for message: {message}")
        return jsonify({"response": reply})
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Quiz endpoint - Generate 5 diverse questions
@app.route('/api/quiz', methods=['POST'])
def quiz():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for quiz")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        topic = data.get('topic')
        if not topic:
            logger.warning("Topic not provided for quiz")
            return jsonify({"error": "Topic is required"}), 400
        questions = []
        aspects = [
            "causes or triggers of the event",
            "major battles or conflicts",
            "key figures or leaders",
            "significant treaties or agreements",
            "consequences or outcomes"
        ]
        for i in range(5):
            prompt = f"""
            Generate a multiple-choice quiz question on {topic}, focusing specifically on {aspects[i]}. Ensure the question is unique and does not repeat concepts from the following questions: {json.dumps([q['question'] for q in questions])}. Return the response as a valid JSON object with the following fields:
            - "question": a string containing the quiz question
            - "options": an array of exactly 4 strings, each an answer option
            - "correct_answer": a string, one of the options
            The response must be valid JSON, enclosed in curly braces {{}}. Do not include any text outside the JSON object. Example:
            {{
                "question": "What was a major cause of {topic}?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_answer": "Option A"
            }}
            """
            attempts = 0
            max_attempts = 3
            while attempts < max_attempts:
                response = client.chat.completions.create(
                    model=AZURE_OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300
                )
                raw_content = response.choices[0].message.content
                logger.debug(f"Raw OpenAI response for topic '{topic}', aspect '{aspects[i]}': {raw_content}")
                if not raw_content or raw_content.strip() == "":
                    attempts += 1
                    continue
                try:
                    question_data = json.loads(raw_content)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing error: {str(e)}")
                    json_match = re.search(r'\{.*?\}', raw_content, re.DOTALL)
                    if json_match:
                        try:
                            question_data = json.loads(json_match.group(0))
                        except json.JSONDecodeError:
                            lines = raw_content.split('\n')
                            question = ""
                            options = []
                            correct_answer = ""
                            for line in lines:
                                line = line.strip()
                                if line.startswith("Question:") or line.startswith("Q:"):
                                    question = line.split(":", 1)[1].strip()
                                elif line.startswith("- ") or line.startswith("* ") or line.startswith("Option"):
                                    option = line.split(":", 1)[1].strip() if ":" in line else line[2:].strip()
                                    if option:
                                        options.append(option)
                                elif "Correct Answer:" in line or "Answer:" in line:
                                    correct_answer = line.split(":", 1)[1].strip()
                            if question and len(options) >= 4 and correct_answer:
                                question_data = {
                                    "question": question,
                                    "options": options[:4],
                                    "correct_answer": correct_answer
                                }
                            else:
                                attempts += 1
                                continue
                    else:
                        attempts += 1
                        continue
                if not all(key in question_data for key in ['question', 'options', 'correct_answer']):
                    attempts += 1
                    continue
                if len(question_data['options']) != 4 or question_data['correct_answer'] not in question_data['options']:
                    attempts += 1
                    continue
                if is_question_similar(question_data, questions):
                    attempts += 1
                    continue
                questions.append({
                    "question": question_data['question'],
                    "options": question_data['options'],
                    "correct_answer": question_data['correct_answer'],
                    "question_id": str(uuid.uuid4())
                })
                break
            if attempts >= max_attempts:
                logger.error(f"Failed to generate a unique question for aspect '{aspects[i]}' after {max_attempts} attempts")
                return jsonify({"error": f"Failed to generate a unique question for aspect '{aspects[i]}' after {max_attempts} attempts"}), 500
        logger.debug(f"Generated {len(questions)} quiz questions for topic: {topic}")
        return jsonify({"questions": questions})
    except Exception as e:
        logger.error(f"Error generating quiz questions for topic '{topic}': {str(e)}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Submit quiz answers
@app.route('/api/submit-quiz', methods=['POST'])
def submit_quiz():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for submit-quiz")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        answers = data.get('answers')
        if not answers or not isinstance(answers, list):
            logger.warning("Invalid answers format for submit-quiz")
            return jsonify({"error": "Answers must be a non-empty array"}), 400
        results = []
        total_score = 0
        for answer in answers:
            question_id = answer.get('question_id')
            user_answer = answer.get('answer')
            correct_answer = answer.get('correct_answer')
            if not question_id or not user_answer or not correct_answer:
                logger.warning("Incomplete answer data in submit-quiz")
                return jsonify({"error": "Each answer must include question_id, answer, and correct_answer"}), 400
            is_correct = user_answer == correct_answer
            score = 1 if is_correct else 0
            total_score += score
            prompt = f"""
            Explain why '{correct_answer}' is the correct answer for the question: '{answer.get('question')}'.
            Provide a concise explanation (50-100 words) suitable for a student learning about {data.get('topic')}.
            """
            explanation_response = client.chat.completions.create(
                model=AZURE_OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150
            )
            explanation = explanation_response.choices[0].message.content
            scores_container.upsert_item({
                'id': str(uuid.uuid4()),
                'user_id': user_id,
                'question_id': question_id,
                'question': answer.get('question'),
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'score': score,
                'explanation': explanation,
                'timestamp': datetime.now().isoformat()
            })
            results.append({
                "question_id": question_id,
                "question": answer.get('question'),
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct,
                "score": score,
                "explanation": explanation
            })
        logger.debug(f"Quiz submitted with total score: {total_score}")
        return jsonify({
            "status": "saved",
            "total_score": total_score,
            "results": results
        })
    except Exception as e:
        logger.error(f"Error processing quiz submission: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Save note
@app.route('/api/save-note', methods=['POST'])
def save_note():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for save-note")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        note = data.get('note')
        note_style = data.get('note_style')  # Optional: narrative, analogy, bullet_points, step_by_step
        if not note:
            logger.warning("Note content is required")
            return jsonify({"error": "Note content is required"}), 400
        note_item = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'note': note,
            'timestamp': datetime.now().isoformat()
        }
        if note_style:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": f"Rewrite the following note in a {note_style} style: {note}"},
                    {"role": "user", "content": note}
                ],
                max_tokens=500
            )
            rewritten_note = response.choices[0].message.content
            note_item['note_style'] = note_style
            note_item['rewritten_note'] = rewritten_note
        notes_container.upsert_item(note_item)
        logger.debug("Note saved successfully")
        return jsonify({"status": "saved", "note_id": note_item['id'], "rewritten_note": note_item.get('rewritten_note')})
    except Exception as e:
        logger.error(f"Error saving note: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Get user's notes
@app.route('/api/get-notes', methods=['GET'])
def get_notes():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for get-notes")
        return jsonify({"error": "Not logged in"}), 401
    try:
        notes = list(notes_container.query_items(
            query="SELECT * FROM c WHERE c.user_id = @user_id ORDER BY c.timestamp DESC",
            parameters=[{"name": "@user_id", "value": user_id}],
            enable_cross_partition_query=False
        ))
        logger.debug(f"Fetched {len(notes)} notes for user: {user_id}")
        return jsonify({"notes": notes})
    except Exception as e:
        logger.error(f"Error fetching notes: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Rewrite note
@app.route('/api/rewrite_note', methods=['POST'])
def rewrite_note():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for rewrite_note")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        note = data.get('note')
        note_style = data.get('note_style')
        if not note or not note_style:
            logger.warning("Missing note or note_style")
            return jsonify({"error": "Missing note or note_style"}), 400
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": f"Rewrite the following note in a {note_style} style: {note}"},
                {"role": "user", "content": note}
            ],
            max_tokens=500
        )
        rewritten_note = response.choices[0].message.content
        logger.debug("Note rewritten successfully")
        return jsonify({"rewritten_note": rewritten_note})
    except Exception as e:
        logger.error(f"Error rewriting note: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Save feedback
@app.route('/api/save-feedback', methods=['POST'])
def save_feedback():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for save-feedback")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        feedback = data.get('feedback')
        feedback_container.upsert_item({
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'feedback': feedback,
            'timestamp': datetime.now().isoformat()
        })
        logger.debug("Feedback saved successfully")
        return jsonify({"status": "saved"})
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# SocketIO event for broadcasting chat messages
@socketio.on('message')
def handle_message(data):
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for SocketIO message")
        return
    try:
        chat_message = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'username': data.get('username'),
            'message': data.get('message'),
            'timestamp': datetime.now().isoformat()
        }
        chatmessages_container.upsert_item(chat_message)
        emit('response', chat_message, broadcast=True)
        logger.debug(f"Chat message broadcast: {data['message']}")
    except Exception as e:
        logger.error(f"Error saving chat message: {e}")

# Learning Planner Endpoints
@app.route('/api/create-learning-plan', methods=['POST'])
def create_learning_plan():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for create-learning-plan")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        topic = data.get('topic')
        end_date = data.get('end_date')
        complexity = data.get('complexity')
        if not topic or not end_date or not complexity:
            logger.warning("Missing required fields in create-learning-plan")
            return jsonify({"error": "Topic, end date, and complexity required"}), 400
        plan = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'topic': topic,
            'end_date': end_date,
            'complexity': complexity,
            'created_at': datetime.utcnow().isoformat()
        }
        learningplans_container.upsert_item(plan)
        logger.info(f"Learning plan saved for topic: {topic}")
        return jsonify({'status': 'saved', 'plan_id': plan['id']})
    except Exception as e:
        logger.error(f"Error saving learning plan: {e}")
        return jsonify({'error': f"Failed to save plan: {str(e)}"}), 500

@app.route('/api/get-learning-plans', methods=['GET'])
def get_learning_plans():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for get-learning-plans")
        return jsonify({"error": "Not logged in"}), 401
    try:
        query = "SELECT * FROM c WHERE c.user_id = @user_id ORDER BY c.created_at DESC"
        params = [{'name': '@user_id', 'value': user_id}]
        items = list(learningplans_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        logger.debug(f"Fetched {len(items)} learning plans for user: {user_id}")
        return jsonify(items)
    except Exception as e:
        logger.error(f"Error fetching learning plans: {e}")
        return jsonify({"error": f"Failed to load plans: {str(e)}"}), 500

@app.route('/api/get-todays-plan', methods=['GET'])
def get_todays_plan():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for get-todays-plan")
        return jsonify({"error": "Not logged in"}), 401
    try:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.end_date = @today"
        params = [
            {'name': '@user_id', 'value': user_id},
            {'name': '@today', 'value': today}
        ]
        items = list(learningplans_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        if items:
            logger.debug(f"Found today's plan: {items[0]['topic']}")
            return jsonify({'topic': items[0]['topic'], 'end_date': items[0]['end_date'], 'complexity': items[0]['complexity']})
        logger.debug("No plan found for today")
        return jsonify({})
    except Exception as e:
        logger.error(f"Error fetching today's plan: {e}")
        return jsonify({"error": f"Failed to load plan: {str(e)}"}), 500

@app.route('/api/learn-subtopic', methods=['POST'])
def learn_subtopic():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("Not logged in for learn-subtopic")
        return jsonify({"error": "Not logged in"}), 401
    try:
        data = request.get_json()
        subtopic = data.get('subtopic')
        complexity = data.get('complexity')
        if not subtopic or not complexity:
            logger.warning("Missing subtopic or complexity")
            return jsonify({"error": "Missing subtopic or complexity"}), 400
        prompt = f"Provide a detailed explanation of '{subtopic}' for a {complexity} level learner."
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        explanation = response.choices[0].message.content
        logger.debug(f"Generated explanation for subtopic: {subtopic}")
        return jsonify({"explanation": explanation})
    except Exception as e:
        logger.error(f"Error generating subtopic explanation: {e}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    try:
        logger.info("Starting Flask server...")
        # For local development, use Flask-SocketIO
        socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=True)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise