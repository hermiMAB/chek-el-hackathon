let isVoiceEnabled = false;
let points = 0;
let quizCount = 0;
const userId = 'user-' + Math.random().toString(36).substr(2, 9);

// Ask AI Page
const askButton = document.getElementById('askButton');
const topicInput = document.getElementById('topicInput');
const responseDiv = document.getElementById('response');
const saveNoteButton = document.getElementById('saveNote');
const notesList = document.getElementById('notesList');
const voiceToggle = document.getElementById('voiceToggle');
const recordButton = document.getElementById('recordButton');
const pointsSpan = document.getElementById('points');
const progressBar = document.getElementById('progressBar');
const badgesSpan = document.getElementById('badges');

if (askButton) {
    askButton.addEventListener('click', askAI);
    topicInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') askAI();
    });
    saveNoteButton.addEventListener('click', saveNote);
    voiceToggle.addEventListener('click', () => {
        isVoiceEnabled = !isVoiceEnabled;
        voiceToggle.innerText = isVoiceEnabled ? 'Disable Voice' : 'Enable Voice';
        recordButton.style.display = isVoiceEnabled ? 'block' : 'none';
        document.getElementById('audioOutput').style.display = isVoiceEnabled ? 'block' : 'none';
    });
    recordButton.addEventListener('click', async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream);
            let chunks = [];
            mediaRecorder.ondataavailable = e => chunks.push(e.data);
            mediaRecorder.onstop = async () => {
                const blob = new Blob(chunks, { type: 'audio/wav' });
                const formData = new FormData();
                formData.append('audio', blob);
                const response = await fetch('/api/speech-to-text', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (data.text) {
                    topicInput.value = data.text;
                    askAI();
                } else {
                    responseDiv.innerHTML = '<p class="text-danger">No speech detected.</p>';
                }
            };
            mediaRecorder.start();
            setTimeout(() => mediaRecorder.stop(), 5000);
        } catch (e) {
            responseDiv.innerHTML = '<p class="text-danger">Error accessing microphone.</p>';
        }
    });
    fetchNotes();
}

async function askAI() {
    const topic = topicInput.value.trim();
    if (!topic) {
        responseDiv.innerHTML = '<p class="text-danger">Please enter a topic.</p>';
        return;
    }
    responseDiv.innerHTML = '<p>Loading...</p>';
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: topic })
        });
        const data = await response.json();
        responseDiv.innerHTML = `<p>${data.response}</p>`;
        saveNoteButton.style.display = 'block';
        if (isVoiceEnabled) {
            const audioResponse = await fetch('/api/text-to-speech', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: data.response })
            });
            const audioData = await audioResponse.json();
            const audio = document.getElementById('audioOutput');
            audio.src = `data:audio/wav;base64,${audioData.audio}`;
            audio.play();
        }
    } catch (e) {
        responseDiv.innerHTML = '<p class="text-danger">Error fetching response.</p>';
    }
}

async function saveNote() {
    const note = responseDiv.innerText;
    const topic = topicInput.value.trim();
    try {
        const response = await fetch('/api/save-note', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note, topic })
        });
        const data = await response.json();
        if (data.status === 'saved') {
            fetchNotes();
        }
    } catch (e) {
        responseDiv.innerHTML = '<p class="text-danger">Error saving note.</p>';
    }
}

async function fetchNotes() {
    try {
        const response = await fetch('/api/get-notes');
        const notes = await response.json();
        notesList.innerHTML = '';
        notes.forEach(note => {
            const li = document.createElement('li');
            li.className = 'list-group-item';
            li.innerHTML = `<strong>${note.topic}</strong>: ${note.note} <br>Tags: ${note.tags.join(', ')}`;
            notesList.appendChild(li);
        });
    } catch (e) {
        notesList.innerHTML = '<li class="list-group-item text-danger">Error fetching notes.</li>';
    }
}

// Quiz Page
const startQuizButton = document.getElementById('startQuiz');
const quizTopicInput = document.getElementById('quizTopic');
const quizDiv = document.getElementById('quiz');

if (startQuizButton) {
    startQuizButton.addEventListener('click', startQuiz);
    quizTopicInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') startQuiz();
    });
}

async function startQuiz() {
    const topic = quizTopicInput.value.trim();
    if (!topic) {
        quizDiv.innerHTML = '<p class="text-danger">Please enter a topic.</p>';
        return;
    }
    quizDiv.innerHTML = '<p>Loading...</p>';
    try {
        const response = await fetch('/api/quiz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic })
        });
        const data = await response.json();
        quizDiv.innerHTML = `<p>${data.quiz}</p><button id="submitQuiz" class="btn btn-primary">Submit Quiz</button>`;
        document.getElementById('submitQuiz').addEventListener('click', () => {
            points += 30;
            quizCount += 1;
            updateGamification();
            saveScore();
            quizDiv.innerHTML += '<p class="text-success">Quiz completed! +30 points</p>';
        });
    } catch (e) {
        quizDiv.innerHTML = '<p class="text-danger">Error fetching quiz.</p>';
    }
}

function updateGamification() {
    pointsSpan.innerText = points;
    const progress = Math.min((points / 100) * 100, 100);
    progressBar.style.width = `${progress}%`;
    let badges = '';
    if (points >= 30) badges += '<span class="badge bg-primary">Quiz Novice</span> ';
    if (points >= 90) badges += '<span class="badge bg-success">Quiz Master</span>';
    badgesSpan.innerHTML = badges;
}

async function saveScore() {
    try {
        await fetch('/api/save-score', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, points, quiz_count: quizCount })
        });
    } catch (e) {
        console.error('Error saving score');
    }
}

// Initialize gamification
if (pointsSpan) updateGamification();