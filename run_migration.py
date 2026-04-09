import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

load_dotenv()
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_PATH')

if not firebase_admin._apps:
    # Check if it's a template value or doesn't exist
    if not FIREBASE_SERVICE_ACCOUNT_KEY_PATH or 'path/to/' in FIREBASE_SERVICE_ACCOUNT_KEY_PATH or 'path\\to\\' in FIREBASE_SERVICE_ACCOUNT_KEY_PATH:
        print('Using default Firebase credentials from environment')
        firebase_admin.initialize_app()
    elif FIREBASE_SERVICE_ACCOUNT_KEY_PATH.strip().startswith('{'):
        print('Using Firebase credentials from JSON in environment variable')
        import json
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT_KEY_PATH))
        firebase_admin.initialize_app(cred)
    else:
        print(f'Using Firebase credentials from file: {FIREBASE_SERVICE_ACCOUNT_KEY_PATH}')
        cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred)

db = firestore.client()
teams = db.collection('global_teams').get()
count = 0

print('Checking global_teams for year field...\n')

for doc in teams:
    data = doc.to_dict()
    if 'year' not in data:
        db.collection('global_teams').document(doc.id).update({'year': '2025'})
        print(f'✓ Updated: {data.get("name", "Unknown")} (ID: {doc.id})')
        count += 1
    else:
        print(f'  Skipped: {data.get("name", "Unknown")} - already has year: {data.get("year")}')

print(f'\n{"="*60}')
if count == 0:
    print('✓ No teams needed updating - all teams already have year field')
else:
    print(f'✓ Success! Updated {count} teams with year: "2025"')
print(f'{"="*60}')
