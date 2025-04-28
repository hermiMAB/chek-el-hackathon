import os
import uuid
import json
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, send_from_directory, redirect
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

# Environment variables
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
    logger.error("Missing COSMOS_URI or COSMOS_KEY")
    raise ValueError("Missing COSMOS_URI or COSMOS_KEY")

if not all([AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_MODEL]):
    logger.error("Missing AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, or AZURE_OPENAI_MODEL")
    raise ValueError("Missing AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, or AZURE_OPENAI_MODEL")

# Initialize Flask app
app = Flask(__name__, static_folder='public')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
logger.info("Flask app and SocketIO initialized with gevent")

# Serve static files
@app.route('/css/<path:filename>')
def serve_css(filename):
    logger.debug(f"Serving CSS: public/css/{filename}")
    return send_from_directory('public/css', filename)

@app.route('/js/<path:filename>')
def serve_js(filename):
    logger.debug(f"Serving JS: public/js/{filename}")
    return send_from_directory('public/js', filename)

# Initialize Cosmos DB
try:
    cosmos_client = CosmosClient(COSMOS_URI, COSMOS_KEY)
    database = cosmos_client.get_database_client('CheckElDB')
    logger.info("Cosmos DB client initialized")
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
        logger.info(f"{container_id} container created or exists")
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
    logger.info("Azure OpenAI client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Azure OpenAI client: {e}")
    raise

# Valid note styles
VALID_NOTE_STYLES = ['narrative', 'analogy', 'bullet_points', 'step_by_step']

# Check question similarity
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

# Generate learning plan schedule
def generate_schedule(topic, end_date, complexity):
    try:
        end = datetime.strptime(end_date, '%Y-%m-%d')
        today = datetime.utcnow()
        days = (end - today).days
        if days < 1:
            return []
        prompt = f"Create a learning schedule for {topic} at {complexity} level, covering {days} days. Return a JSON array of objects with 'subtopic' (string) and 'date' (YYYY-MM-DD)."
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        schedule = json.loads(response.choices[0].message.content)
        return schedule if isinstance(schedule, list) else []
    except Exception as e:
        logger.error(f"Error generating schedule: {e}")
        return []

# Register user
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400
        existing_user = users_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": username}],
            enable_cross_partition_query=True
        )
        if next(existing_user, None):
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
        logger.error(f"Error in register: {e}")
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500

# Login
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        logger.debug(f"Login attempt: {username}")
        user = users_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": username}],
            enable_cross_partition_query=True
        )
        user = next(user, None)
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session.permanent = True
            logger.info(f"Login successful: {username}")
            return jsonify({"status": "success"})
        logger.warning("Login failed: Invalid credentials")
        return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        logger.error(f"Error in login: {e}")
        return jsonify({"error": f"Login failed: {str(e)}"}), 500

# Logout
@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        session.pop('user_id', None)
        session.pop('username', None)
        logger.info("User logged out")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error in logout: {e}")
        return jsonify({"error": f"Logout failed: {str(e)}"}), 500

# Check authentication
@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    try:
        if 'user_id' in session:
            return jsonify({"authenticated": True, "username": session['username']})
        return jsonify({"authenticated": False})
    except Exception as e:
        logger.error(f"Error in check-auth: {e}")
        return jsonify({"error": f"Auth check failed: {str(e)}"}), 500

# Get username
@app.route('/api/get-username', methods=['GET'])
def get_username():
    try:
        if 'username' in session:
            return jsonify({"username": session['username']})
        return jsonify({"error": "Not logged in"}), 401
    except Exception as e:
        logger.error(f"Error in get-username: {e}")
        return jsonify({"error": f"Failed to get username: {str(e)}"}), 500

# Community chat messages
@app.route('/api/community-chat', methods=['GET'])
def get_chat_messages():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to community-chat")
            return jsonify({"error": "Not logged in"}), 401
        messages = list(chatmessages_container.query_items(
            query="SELECT * FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT 50",
            enable_cross_partition_query=True
        ))
        logger.info(f"Fetched {len(messages)} chat messages")
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Error in community-chat: {e}")
        return jsonify({"error": f"Failed to load messages: {str(e)}"}), 500

# Summarize chat
@app.route('/api/summarize-chat', methods=['POST'])
def summarize_chat():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to summarize-chat")
            return jsonify({"error": "Not logged in"}), 401
        messages = list(chatmessages_container.query_items(
            query="SELECT * FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT 50",
            enable_cross_partition_query=True
        ))
        if not messages:
            return jsonify({"summary": "No messages to summarize"})
        chat_text = "\n".join([f"{msg['username']}: {msg['message']}" for msg in messages])
        prompt = f"Summarize the following community chat in 50-100 words, capturing main topics and themes:\n{chat_text}"
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        summary = response.choices[0].message.content
        logger.info("Chat summarized successfully")
        return jsonify({"summary": summary})
    except Exception as e:
        logger.error(f"Error in summarize-chat: {e}")
        return jsonify({"error": f"Failed to summarize chat: {str(e)}"}), 500

# Serve static pages
@app.route('/')
@app.route('/welcome')
def serve_welcome():
    if 'user_id' not in session:
        return send_from_directory('public', 'login.html')
    return send_from_directory('public', 'welcome.html')

@app.route('/login')
def serve_login():
    return send_from_directory('public', 'login.html')

@app.route('/ask-ai')
def serve_ask_ai():
    if 'user_id' not in session:
        return redirect('/login')
    return send_from_directory('public', 'ask-ai.html')

@app.route('/quiz')
def serve_quiz():
    if 'user_id' not in session:
        return redirect('/login')
    return send_from_directory('public', 'quiz.html')

@app.route('/community')
def serve_community():
    if 'user_id' not in session:
        return redirect('/login')
    return send_from_directory('public', 'community.html')

@app.route('/feedback')
def serve_feedback():
    if 'user_id' not in session:
        return redirect('/login')
    return send_from_directory('public', 'feedback.html')

@app.route('/learning-planner')
def serve_learning_planner():
    if 'user_id' not in session:
        return redirect('/login')
    return send_from_directory('public', 'learning-planner.html')

@app.route('/notes')
def serve_notes():
    if 'user_id' not in session:
        return redirect('/login')
    return send_from_directory('public', 'notes.html')

# Chat endpoint
@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to chat")
            return jsonify({"error": "Not logged in"}), 401
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
            'user_id': session['user_id'],
            'query': message,
            'response': reply
        })
        logger.info(f"Chat response generated for: {message[:50]}...")
        return jsonify({"response": reply})
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        return jsonify({"error": f"Failed to process chat: {str(e)}"}), 500

# Quiz endpoint
@app.route('/api/quiz', methods=['POST'])
def quiz():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to quiz")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        topic = data.get('topic')
        if not topic:
            return jsonify({"error": "Topic required"}), 400
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
            Generate a multiple-choice quiz question on {topic}, focusing on {aspects[i]}. Ensure uniqueness from: {json.dumps([q['question'] for q in questions])}.
            Return JSON: {{"question": "", "options": ["", "", "", ""], "correct_answer": ""}}
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
                try:
                    question_data = json.loads(raw_content)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{.*?\}', raw_content, re.DOTALL)
                    if json_match:
                        question_data = json.loads(json_match.group(0))
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
                logger.error(f"Failed to generate question for {aspects[i]}")
                return jsonify({"error": f"Failed to generate question for {aspects[i]}"}), 500
        logger.info(f"Generated {len(questions)} quiz questions for: {topic}")
        return jsonify({"questions": questions})
    except Exception as e:
        logger.error(f"Error in quiz: {e}")
        return jsonify({"error": f"Failed to generate quiz: {str(e)}"}), 500

# Submit quiz answers
@app.route('/api/submit-quiz', methods=['POST'])
def submit_quiz():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to submit-quiz")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        answers = data.get('answers')
        if not answers or not isinstance(answers, list):
            return jsonify({"error": "Answers must be a non-empty array"}), 400
        results = []
        total_score = 0
        for answer in answers:
            question_id = answer.get('question_id')
            user_answer = answer.get('answer')
            correct_answer = answer.get('correct_answer')
            if not all([question_id, user_answer, correct_answer]):
                return jsonify({"error": "Each answer needs question_id, answer, correct_answer"}), 400
            is_correct = user_answer == correct_answer
            score = 1 if is_correct else 0
            total_score += score
            prompt = f"Explain why '{correct_answer}' is correct for: '{answer.get('question')}' (50-100 words, for {data.get('topic')} learners)."
            explanation_response = client.chat.completions.create(
                model=AZURE_OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150
            )
            explanation = explanation_response.choices[0].message.content
            scores_container.upsert_item({
                'id': str(uuid.uuid4()),
                'user_id': session['user_id'],
                'question_id': question_id,
                'question': answer.get('question'),
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'score': score,
                'explanation': explanation,
                'timestamp': datetime.utcnow().isoformat()
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
        logger.info(f"Quiz submitted, score: {total_score}")
        return jsonify({"status": "saved", "total_score": total_score, "results": results})
    except Exception as e:
        logger.error(f"Error in submit-quiz: {e}")
        return jsonify({"error": f"Failed to process quiz: {str(e)}"}), 500

# Save note
@app.route('/api/save-note', methods=['POST'])
def save_note():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to save-note")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        note = data.get('note')
        note_style = data.get('note_style')
        if not note:
            logger.warning("Note content missing")
            return jsonify({"error": "Note content required"}), 400
        if note_style and note_style not in VALID_NOTE_STYLES:
            logger.warning(f"Invalid note style: {note_style}")
            return jsonify({"error": f"Invalid note style. Use: {', '.join(VALID_NOTE_STYLES)}"}), 400
        note_item = {
            'id': str(uuid.uuid4()),
            'user_id': session['user_id'],
            'note': note,
            'timestamp': datetime.utcnow().isoformat()
        }
        if note_style:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": f"Rewrite the note in {note_style} style: {note}"},
                    {"role": "user", "content": note}
                ],
                max_tokens=500
            )
            note_item['note_style'] = note_style
            note_item['rewritten_note'] = response.choices[0].message.content
        notes_container.upsert_item(note_item)
        logger.info(f"Note saved for user: {session['user_id']}")
        return jsonify({"status": "saved", "note_id": note_item['id'], "rewritten_note": note_item.get('rewritten_note')})
    except CosmosHttpResponseError as e:
        logger.error(f"Cosmos DB error in save-note: {e}")
        return jsonify({"error": f"Failed to save note: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error in save-note: {e}")
        return jsonify({"error": f"Failed to save note: {str(e)}"}), 500

# Get notes
@app.route('/api/get-notes', methods=['GET'])
def get_notes():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to get-notes")
            return jsonify({"error": "Not logged in"}), 401
        notes = list(notes_container.query_items(
            query="SELECT * FROM c WHERE c.user_id = @user_id ORDER BY c.timestamp DESC",
            parameters=[{"name": "@user_id", "value": session['user_id']}],
            enable_cross_partition_query=False
        ))
        logger.info(f"Fetched {len(notes)} notes for user: {session['user_id']}")
        return jsonify({"notes": notes})
    except CosmosHttpResponseError as e:
        logger.error(f"Cosmos DB error in get-notes: {e}")
        return jsonify({"error": f"Failed to load notes: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error in get-notes: {e}")
        return jsonify({"error": f"Failed to load notes: {str(e)}"}), 500

# Rewrite note
@app.route('/api/rewrite_note', methods=['POST'])
def rewrite_note():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to rewrite_note")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        note = data.get('note')
        note_style = data.get('note_style')
        if not note or not note_style:
            logger.warning("Missing note or note_style")
            return jsonify({"error": "Note and style required"}), 400
        if note_style not in VALID_NOTE_STYLES:
            logger.warning(f"Invalid note style: {note_style}")
            return jsonify({"error": f"Invalid note style. Use: {', '.join(VALID_NOTE_STYLES)}"}), 400
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": f"Rewrite the note in {note_style} style: {note}"},
                {"role": "user", "content": note}
            ],
            max_tokens=500
        )
        logger.info(f"Note rewritten in {note_style} style for user: {session['user_id']}")
        return jsonify({"rewritten_note": response.choices[0].message.content})
    except Exception as e:
        logger.error(f"Error in rewrite_note: {e}")
        return jsonify({"error": f"Failed to rewrite note: {str(e)}"}), 500

# Save feedback
@app.route('/api/save-feedback', methods=['POST'])
def save_feedback():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to save-feedback")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        feedback = data.get('feedback')
        feedback_container.upsert_item({
            'id': str(uuid.uuid4()),
            'user_id': session['user_id'],
            'feedback': feedback,
            'timestamp': datetime.utcnow().isoformat()
        })
        logger.info("Feedback saved successfully")
        return jsonify({"status": "saved"})
    except Exception as e:
        logger.error(f"Error in save-feedback: {e}")
        return jsonify({"error": f"Failed to save feedback: {str(e)}"}), 500

# Learning Planner: Create plan
@app.route('/api/create-learning-plan', methods=['POST'])
def create_learning_plan():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to create-learning-plan")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        topic = data.get('topic')
        end_date = data.get('end_date')
        complexity = data.get('complexity')
        if not all([topic, end_date, complexity]):
            logger.warning("Missing fields in create-learning-plan")
            return jsonify({"error": "Topic, end date, and complexity required"}), 400
        try:
            datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            logger.warning("Invalid end_date format")
            return jsonify({"error": "End date must be YYYY-MM-DD"}), 400
        plan = {
            'id': str(uuid.uuid4()),
            'user_id': session['user_id'],
            'username': session['username'],
            'topic': topic,
            'end_date': end_date,
            'complexity': complexity,
            'created_at': datetime.utcnow().isoformat(),
            'schedule': generate_schedule(topic, end_date, complexity)
        }
        learningplans_container.upsert_item(plan)
        logger.info(f"Learning plan created: {topic} for user: {session['user_id']}")
        return jsonify({"status": "saved", "plan_id": plan['id']})
    except CosmosHttpResponseError as e:
        logger.error(f"Cosmos DB error in create-learning-plan: {e}")
        return jsonify({"error": f"Failed to save plan: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error in create-learning-plan: {e}")
        return jsonify({"error": f"Failed to save plan: {str(e)}"}), 500

# Learning Planner: Get plans
@app.route('/api/get-learning-plans', methods=['GET'])
def get_learning_plans():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to get-learning-plans")
            return jsonify({"error": "Not logged in"}), 401
        query = "SELECT * FROM c WHERE c.user_id = @user_id ORDER BY c.created_at DESC"
        params = [{'name': '@user_id', 'value': session['user_id']}]
        plans = list(learningplans_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=False
        ))
        logger.info(f"Fetched {len(plans)} learning plans for user: {session['user_id']}")
        return jsonify(plans)
    except CosmosHttpResponseError as e:
        logger.error(f"Cosmos DB error in get-learning-plans: {e}")
        return jsonify({"error": f"Failed to load plans: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error in get-learning-plans: {e}")
        return jsonify({"error": f"Failed to load plans: {str(e)}"}), 500

# Learning Planner: Get today's plan
@app.route('/api/get-todays-plan', methods=['GET'])
def get_todays_plan():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to get-todays-plan")
            return jsonify({"error": "Not logged in"}), 401
        today = datetime.utcnow().strftime('%Y-%m-%d')
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.end_date >= @today"
        params = [
            {'name': '@user_id', 'value': session['user_id']},
            {'name': '@today', 'value': today}
        ]
        plans = list(learningplans_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=False
        ))
        if plans:
            logger.info(f"Found today's plan: {plans[0]['topic']}")
            return jsonify(plans[0])
        logger.info("No plan found for today")
        return jsonify({})
    except CosmosHttpResponseError as e:
        logger.error(f"Cosmos DB error in get-todays-plan: {e}")
        return jsonify({"error": f"Failed to load plan: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error in get-todays-plan: {e}")
        return jsonify({"error": f"Failed to load plan: {str(e)}"}), 500

# Learning Planner: Learn subtopic
@app.route('/api/learn-subtopic', methods=['POST'])
def learn_subtopic():
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized access to learn-subtopic")
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json()
        subtopic = data.get('subtopic')
        complexity = data.get('complexity')
        if not subtopic or not complexity:
            return jsonify({"error": "Subtopic and complexity required"}), 400
        prompt = f"Provide a detailed explanation of '{subtopic}' for a {complexity} level learner."
        response = client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        explanation = response.choices[0].message.content
        logger.info(f"Generated explanation for subtopic: {subtopic}")
        return jsonify({"explanation": explanation})
    except Exception as e:
        logger.error(f"Error in learn-subtopic: {e}")
        return jsonify({"error": f"Failed to generate explanation: {str(e)}"}), 500

# SocketIO: Chat messages
@socketio.on('message')
def handle_message(data):
    try:
        if 'user_id' not in session:
            logger.warning("Unauthorized SocketIO message")
            emit('error', {"message": "Not logged in"})
            return
        chat_message = {
            'id': str(uuid.uuid4()),
            'user_id': session['user_id'],
            'username': data.get('username', session['username']),
            'message': data.get('message'),
            'timestamp': datetime.utcnow().isoformat()
        }
        chatmessages_container.upsert_item(chat_message)
        emit('response', chat_message, broadcast=True)
        logger.info(f"Chat message broadcast: {data.get('message')[:50]}...")
    except Exception as e:
        logger.error(f"Error in SocketIO message: {e}")
        emit('error', {"message": f"Failed to send message: {str(e)}"})

if __name__ == '__main__':
    try:
        logger.info("Starting Flask server...")
        socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=True)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise

