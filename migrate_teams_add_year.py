"""
Migration script to add 'year' field to existing global_teams in Firestore.
This should be run once on the staging database before deploying.

Run: python migrate_teams_add_year.py
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    # Initialize Firebase Admin SDK
    if not firebase_admin._apps:
        # Check if GOOGLE_APPLICATION_CREDENTIALS is set
        if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
            cred = credentials.ApplicationDefault()
        else:
            print("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set")
            print("Please set it to point to your service account key JSON file")
            return
        
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    
    # Get all global teams that don't have a 'year' field
    global_teams_ref = db.collection('global_teams')
    teams = global_teams_ref.get()
    
    teams_to_update = []
    for doc in teams:
        team_data = doc.to_dict()
        if 'year' not in team_data:
            teams_to_update.append(doc.id)
    
    if not teams_to_update:
        print("No teams need updating. All teams already have 'year' field.")
        return
    
    print(f"Found {len(teams_to_update)} teams without 'year' field.")
    print("\nTeams to update:")
    for team_id in teams_to_update:
        doc = global_teams_ref.document(team_id).get()
        team_data = doc.to_dict()
        print(f"  - {team_data.get('name', 'Unknown')} (ID: {team_id})")
    
    # Ask for confirmation
    year = input("\nWhat year should be assigned to these teams? (default: 2025): ").strip() or "2025"
    confirm = input(f"\nAdd year '{year}' to {len(teams_to_update)} teams? (yes/no): ").strip().lower()
    
    if confirm != 'yes':
        print("Migration cancelled.")
        return
    
    # Update teams
    print(f"\nUpdating {len(teams_to_update)} teams...")
    for team_id in teams_to_update:
        global_teams_ref.document(team_id).update({
            'year': year
        })
        print(f"  ✓ Updated team {team_id}")
    
    print(f"\n✅ Migration complete! Updated {len(teams_to_update)} teams with year '{year}'")

if __name__ == '__main__':
    main()
