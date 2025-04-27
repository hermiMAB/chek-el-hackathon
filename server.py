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

# Load environment variables
load_dotenv('C:\\Users\\Hermela\\Desktop\\chek-el-hackathon\\chek-el-hackathon\\.env')

# Debug environment variables
COSMOS_URI = os.getenv('COSMOS_URI')
COSMOS_KEY = os.getenv('COSMOS_KEY')
if not COSMOS_URI or not COSMOS_KEY:
    raise ValueError("Missing COSMOS_URI or COSMOS_KEY in environment variables. Please check your .env file.")

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
if not AZURE_OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT:
    raise ValueError("Missing AZURE_OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT in environment variables. Please check your .env file.")

# Initialize Flask app
app = Flask(__name__, static_folder='public')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize Azure Cosmos DB
cosmos_client = CosmosClient(COSMOS_URI, COSMOS_KEY)
database = cosmos_client.get_database_client('CheckElDB')

# Initialize containers with partition keys
try:
    users_container = database.create_container_if_not_exists(
        id='Users',
        partition_key={"paths": ["/id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("Users container created or already exists.")
except Exception as e:
    print(f"Error creating Users container: {e}")
    raise e

try:
    notes_container = database.create_container_if_not_exists(
        id='Notes',
        partition_key={"paths": ["/user_id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("Notes container created or already exists.")
except Exception as e:
    print(f"Error creating Notes container: {e}")
    raise e

try:
    scores_container = database.create_container_if_not_exists(
        id='Scores',
        partition_key={"paths": ["/user_id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("Scores container created or already exists.")
except Exception as e:
    print(f"Error creating Scores container: {e}")
    raise e

try:
    searches_container = database.create_container_if_not_exists(
        id='Searches',
        partition_key={"paths": ["/user_id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("Searches container created or already exists.")
except Exception as e:
    print(f"Error creating Searches container: {e}")
    raise e

try:
    feedback_container = database.create_container_if_not_exists(
        id='Feedback',
        partition_key={"paths": ["/user_id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("Feedback container created or already exists.")
except Exception as e:
    print(f"Error creating Feedback container: {e}")
    raise e

try:
    learning_plans_container = database.create_container_if_not_exists(
        id='LearningPlans',
        partition_key={"paths": ["/user_id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("LearningPlans container created or already exists.")
except Exception as e:
    print(f"Error creating LearningPlans container: {e}")
    raise e

try:
    community_chat_container = database.create_container_if_not_exists(
        id='CommunityChat',
        partition_key={"paths": ["/chat_id"], "kind": "Hash"},
        offer_throughput=400
    )
    print("CommunityChat container created or already exists.")
except Exception as e:
    print(f"Error creating CommunityChat container: {e}")
    raise e

# Initialize Azure OpenAI
client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2023-05-15",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# Simple function to check question similarity (basic string comparison)
def is_question_similar(new_question, existing_questions):
    new_text = new_question['question'].lower().strip()  # Extract 'question' field
    for existing in existing_questions:
        existing_text = existing['question'].lower().strip()
        # Basic similarity check: if questions share too many words or are too short
        new_words = set(new_text.split())
        existing_words = set(existing_text.split())
        common_words = len(new_words.intersection(existing_words))
        if common_words / max(len(new_words), len(existing_words)) > 0.7:  # 70% word overlap
            return True
    return False

# Register a new user
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
    # Check if user exists
    existing_user = users_container.query_items(
        query="SELECT * FROM c WHERE c.username = @username",
        parameters=[{"name": "@username", "value": username}],
        enable_cross_partition_query=True
    )
    existing_user = next(existing_user, None)
    if existing_user:
        return jsonify({"error": "User already exists"}), 400
    # Hash password and create user
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user = {
        "id": str(uuid.uuid4()),
        "username": username,
        "password": hashed_password
    }
    users_container.upsert_item(user)
    print(f"Registered user: {username}")
    return jsonify({"status": "User registered"})

# User login
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    print(f"Login attempt - Username: {username}")
    user = users_container.query_items(
        query="SELECT * FROM c WHERE c.username = @username",
        parameters=[{"name": "@username", "value": username}],
        enable_cross_partition_query=True
    )
    user = next(user, None)
    print(f"User found: {user}")
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        print("Login successful")
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({"status": "success"})
    print("Login failed - Invalid credentials")
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return jsonify({"status": "success"})

# Check authentication status
@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        return jsonify({"authenticated": True})
    return jsonify({"authenticated": False})

# Get username for logged-in user
@app.route('/api/get-username', methods=['GET'])
def get_username():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    try:
        user = users_container.query_items(
            query="SELECT * FROM c WHERE c.id = @user_id",
            parameters=[{"name": "@user_id", "value": user_id}],
            enable_cross_partition_query=True
        )
        user = next(user, None)
        if user:
            return jsonify({"username": user['username']})
        return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Serve static files
@app.route('/')
def serve_index():
    return send_from_directory('public', 'welcome.html')

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
        return send_from_directory('public', 'login.html')
    return send_from_directory('public', 'ask-ai.html')

@app.route('/quiz')
def serve_quiz():
    if 'user_id' not in session:
        return send_from_directory('public', 'login.html')
    return send_from_directory('public', 'quiz.html')

@app.route('/community')
def serve_community():
    if 'user_id' not in session:
        return send_from_directory('public', 'login.html')
    return send_from_directory('public', 'community.html')

@app.route('/feedback')
def serve_feedback():
    if 'user_id' not in session:
        return send_from_directory('public', 'login.html')
    return send_from_directory('public', 'feedback.html')

@app.route('/learning-planner')
def serve_learning_planner():
    if 'user_id' not in session:
        return send_from_directory('public', 'login.html')
    return send_from_directory('public', 'learning-planner.html')

# Chat endpoint
@app.route('/api/chat', methods=['POST'])
def chat():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    message = data.get('message')
    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": message}],
            max_tokens=500
        )
        reply = response.choices[0].message.content
        # Save to searches
        searches_container.upsert_item({
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'query': message,
            'response': reply
        })
        return jsonify({"response": reply})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Community chat endpoint - Fetch recent messages
@app.route('/api/community-chat', methods=['GET'])
def get_community_chat():
    try:
        messages = list(community_chat_container.query_items(
            query="SELECT * FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT 50",
            enable_cross_partition_query=True
        ))
        return jsonify({"messages": messages})
    except Exception as e:
        print(f"Error fetching community chat: {str(e)}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Summarize community chat
@app.route('/api/summarize-chat', methods=['POST'])
def summarize_chat():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    try:
        # Fetch recent messages
        messages = list(community_chat_container.query_items(
            query="SELECT * FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT 50",
            enable_cross_partition_query=True
        ))
        if not messages:
            return jsonify({"summary": "No messages to summarize."})
        # Format messages for summarization
        chat_text = "\n".join([f"{msg['username']}: {msg['message']}" for msg in messages])
        prompt = f"""
        Summarize the following community chat conversation in 50-100 words, capturing the main topics, themes, or questions discussed. Ensure the summary is concise, clear, and suitable for users learning about the conversation:
        {chat_text}
        """
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        summary = response.choices[0].message.content
        return jsonify({"summary": summary})
    except Exception as e:
        print(f"Error summarizing chat: {str(e)}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Quiz endpoint - Generate 5 diverse questions
@app.route('/api/quiz', methods=['POST'])
def quiz():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    topic = data.get('topic')
    if not topic:
        return jsonify({"error": "Topic is required"}), 400
    try:
        questions = []
        aspects = [
            "causes or triggers of the event",
            "major battles or conflicts",
            "key figures or leaders",
            "significant treaties or agreements",
            "consequences or outcomes"
        ]
        for i in range(5):  # Generate 5 questions
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
                    model=os.getenv("AZURE_OPENAI_MODEL"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300
                )
                raw_content = response.choices[0].message.content
                print(f"Raw OpenAI response for topic '{topic}', aspect '{aspects[i]}': {raw_content}")  # Debug log
                if not raw_content or raw_content.strip() == "":
                    attempts += 1
                    continue
                try:
                    question_data = json.loads(raw_content)
                except json.JSONDecodeError as e:
                    print(f"JSON parsing error: {str(e)}")
                    # Fallback parsing for non-JSON response
                    json_match = re.search(r'\{.*?\}', raw_content, re.DOTALL)
                    if json_match:
                        try:
                            question_data = json.loads(json_match.group(0))
                        except json.JSONDecodeError:
                            # Manual parsing as last resort
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
                # Validate the response structure
                if not all(key in question_data for key in ['question', 'options', 'correct_answer']):
                    attempts += 1
                    continue
                if len(question_data['options']) != 4:
                    attempts += 1
                    continue
                if question_data['correct_answer'] not in question_data['options']:
                    attempts += 1
                    continue
                # Check for similarity with existing questions
                if is_question_similar(question_data, questions):
                    attempts += 1
                    continue
                # Valid question, add to list
                questions.append({
                    "question": question_data['question'],
                    "options": question_data['options'],
                    "correct_answer": question_data['correct_answer'],
                    "question_id": str(uuid.uuid4())
                })
                break
            if attempts >= max_attempts:
                return jsonify({"error": f"Failed to generate a unique question for aspect '{aspects[i]}' after {max_attempts} attempts"}), 500
        return jsonify({"questions": questions})
    except Exception as e:
        print(f"Error generating quiz questions for topic '{topic}': {str(e)}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Submit quiz answers
@app.route('/api/submit-quiz', methods=['POST'])
def submit_quiz():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    answers = data.get('answers')  # Array of {question_id, answer}
    if not answers or not isinstance(answers, list):
        return jsonify({"error": "Answers must be a non-empty array"}), 400
    try:
        results = []
        total_score = 0
        for answer in answers:
            question_id = answer.get('question_id')
            user_answer = answer.get('answer')
            correct_answer = answer.get('correct_answer')
            if not question_id or not user_answer or not correct_answer:
                return jsonify({"error": "Each answer must include question_id, answer, and correct_answer"}), 400
            # Validate answer
            is_correct = user_answer == correct_answer
            score = 1 if is_correct else 0
            total_score += score
            # Generate explanation
            prompt = f"""
            Explain why '{correct_answer}' is the correct answer for the question: '{answer.get('question')}'.
            Provide a concise explanation (50-100 words) suitable for a student learning about {data.get('topic')}.
            """
            explanation_response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_MODEL"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150
            )
            explanation = explanation_response.choices[0].message.content
            # Save score
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
        return jsonify({
            "status": "saved",
            "total_score": total_score,
            "results": results
        })
    except Exception as e:
        print(f"Error processing quiz submission: {str(e)}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Save note
@app.route('/api/save-note', methods=['POST'])
def save_note():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    note = data.get('note')
    try:
        notes_container.upsert_item({
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'note': note,
            'timestamp': datetime.now().isoformat()
        })
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# Save feedback
@app.route('/api/save-feedback', methods=['POST'])
def save_feedback():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    feedback = data.get('feedback')
    try:
        feedback_container.upsert_item({
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'feedback': feedback,
            'timestamp': datetime.now().isoformat()
        })
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# SocketIO event for community chat
@socketio.on('message')
def handle_message(data):
    user_id = session.get('user_id')
    username = data.get('username')
    message = data.get('message')
    if not user_id or not username or not message:
        return
    try:
        chat_message = {
            'id': str(uuid.uuid4()),
            'chat_id': 'global',  # Single global chat
            'user_id': user_id,
            'username': username,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        community_chat_container.upsert_item(chat_message)
        emit('response', chat_message, broadcast=True)
    except Exception as e:
        print(f"Error saving chat message: {str(e)}")

# Learning Planner Endpoints
@app.route('/api/create-learning-plan', methods=['POST'])
def create_learning_plan():
    data = request.get_json()
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    topic = data.get('topic')
    end_date = data.get('end_date')  # Format: YYYY-MM-DD
    complexity = data.get('complexity')  # beginner, intermediate, advanced
    if not topic or not end_date or not complexity:
        return jsonify({"error": "Missing topic, end date, or complexity"}), 400

    try:
        # Generate subtopics using Azure OpenAI
        prompt = f"Break down the topic '{topic}' into 5 subtopics for a {complexity} level learner."
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        subtopics = response.choices[0].message.content.split(',')
        subtopics = [subtopic.strip() for subtopic in subtopics]

        # Schedule subtopics
        start_date = datetime.now().date()
        end_date = datetime.strptime(end_date, '%Y-%m-DD').date()
        days_available = (end_date - start_date).days + 1
        if days_available < len(subtopics):
            return jsonify({"error": "Not enough days to schedule subtopics"}), 400

        schedule = []
        interval = days_available // len(subtopics)
        current_date = start_date
        for i, subtopic in enumerate(subtopics):
            schedule.append({
                'date': current_date.strftime('%Y-%m-DD'),
                'subtopic': subtopic
            })
            current_date += timedelta(days=interval)

        # Save learning plan
        plan_id = str(uuid.uuid4())
        learning_plans_container.upsert_item({
            'id': plan_id,
            'user_id': user_id,
            'topic': topic,
            'complexity': complexity,
            'schedule': schedule,
            'start_date': start_date.strftime('%Y-%m-DD'),
            'end_date': end_date.strftime('%Y-%m-DD')
        })
        return jsonify({"status": "saved", "plan_id": plan_id})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

@app.route('/api/get-todays-plan', methods=['GET'])
def get_todays_plan():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    today = datetime.now().date().strftime('%Y-%m-DD')
    try:
        plans = list(learning_plans_container.query_items(
            query="SELECT * FROM c WHERE c.user_id = @user_id",
            parameters=[{"name": "@user_id", "value": user_id}],
            enable_cross_partition_query=False
        ))
        todays_plan = None
        for plan in plans:
            for entry in plan['schedule']:
                if entry['date'] == today:
                    todays_plan = {
                        'topic': plan['topic'],
                        'subtopic': entry['subtopic'],
                        'complexity': plan['complexity']
                    }
                    break
            if todays_plan:
                break
        return jsonify({"plan": todays_plan or "No plan for today"})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

@app.route('/api/learn-subtopic', methods=['POST'])
def learn_subtopic():
    data = request.get_json()
    subtopic = data.get('subtopic')
    complexity = data.get('complexity')
    if not subtopic or not complexity:
        return jsonify({"error": "Missing subtopic or complexity"}), 400
    try:
        prompt = f"Provide a detailed explanation of '{subtopic}' for a {complexity} level learner."
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        explanation = response.choices[0].message.content
        return jsonify({"explanation": explanation})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)