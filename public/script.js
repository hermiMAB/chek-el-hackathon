async function askAI() {
    const topic = document.getElementById('topicInput').value;
    if (!topic) {
        document.getElementById('response').innerText = 'Please enter a topic.';
        return;
    }
    document.getElementById('response').innerText = 'Loading...';
    try {
        const response = await fetch('https://chek-el-hackathon-hermela.azurewebsites.net/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: topic })
        });
        const data = await response.json();
        document.getElementById('response').innerText = data.response || 'Error: No response';
    } catch (error) {
        document.getElementById('response').innerText = 'Error: Backend not running';
    }
}

async function takeQuiz() {
    const topic = document.getElementById('topicInput').value;
    if (!topic) {
        document.getElementById('quiz').innerText = 'Please enter a topic.';
        return;
    }
    document.getElementById('quiz').innerText = 'Loading...';
    try {
        const response = await fetch('https://chek-el-hackathon-hermela.azurewebsites.net/api/quiz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic })
        });
        const data = await response.json();
        document.getElementById('quiz').innerText = data.quiz || 'Error: No quiz';
    } catch (error) {
        document.getElementById('quiz').innerText = 'Error: Backend not running';
    }
}