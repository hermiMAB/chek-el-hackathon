# add_user.py
import os
import bcrypt
from azure.cosmos import CosmosClient
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv('C:\\Users\\Hermela\\Desktop\\chek-el-hackathon\\chek-el-hackathon\\.env')

# Initialize Cosmos DB client
COSMOS_URI = os.getenv('COSMOS_URI')
COSMOS_KEY = os.getenv('COSMOS_KEY')
if not COSMOS_URI or not COSMOS_KEY:
    raise ValueError("Missing COSMOS_URI or COSMOS_KEY in environment variables.")

cosmos_client = CosmosClient(COSMOS_URI, COSMOS_KEY)
database = cosmos_client.get_database_client('CheckElDB')
users_container = database.get_container_client('Users')

# Add a test user with hashed password
password = "testpass"
hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
user = {
    "id": str(uuid.uuid4()),
    "username": "testuser",
    "password": hashed_password
}
users_container.upsert_item(user)
print("User added:", user)