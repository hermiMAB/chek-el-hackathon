# Chek El: AI-Powered Study Platform
Built for the GenAI Hackathon to support personalized learning using Azure OpenAI and App Service.
# Chek El Notes App - Hackathon Project

## Overview
The Chek El Notes app, developed during the [Hackathon Name] in April 2025, allows users to create, rewrite, and manage notes in various learning styles (e.g., Narrative, Bullet Points) to enhance their learning experience. Built with Flask (Python), HTML, CSS, and Bootstrap, the app features a modern UI with glassmorphism, dark mode, and responsive design.

## Features
- User authentication with login/logout functionality.
- Note creation and storage with a "Save Note" button.
- Rewrite notes in different learning styles using the "Change Learning Style" feature.
- Toggle visibility of saved notes with a "Show Notes" button; delete individual notes.
- Modern UI with glassmorphism, dark mode, toast notifications, and responsive design.

## Tech Stack
- Backend: Flask (Python), in-memory database (planned for Cosmos DB).
- Frontend: HTML, CSS, JavaScript, Bootstrap.
- Deployment: Azure Web App.

## Setup
1. Clone the repository: `git clone https://github.com/hermiMAB/chek-el-hackathon.git`
2. Install dependencies: `pip install -r requirements.txt`
3. Run the server: `gunicorn --worker-class gevent -w 1 server:app`
4. Open `http://localhost:8000/notes` in your browser.

## Screenshots
[Add screenshots here or link to a folder]

## Demo
[Link to video demo on YouTube/Google Drive]

## Acknowledgments
Developed with assistance from Grok (xAI), April 2025.
