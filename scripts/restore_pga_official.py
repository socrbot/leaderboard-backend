"""
Restore 2026 PGA Championship leaderboard from official RapidAPI data.
1. Stores the official leaderboardRows in Firestore
2. Computes team scores in the exact format the backend/frontend expect
"""
import json
import re
import unicodedata
import firebase_admin
from firebase_admin import credentials, firestore
import os
from datetime import datetime, timezone

os.environ['GOOGLE_CLOUD_PROJECT'] = 'alumni-golf-tournament'
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {'projectId': 'alumni-golf-tournament'})
db = firestore.client()

TOURN_ID = '1yRK1FAq9AqKQp3goX91'
PAR = 70

# ─── Official RapidAPI data ────────────────────────────────────────────────────
OFFICIAL_ROWS = [
    {"lastName":"Rai","firstName":"Aaron","playerId":"46414","status":"complete","position":"1","total":"-9","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"-3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"-5","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"65"}}],"thru":"F"},
    {"lastName":"Rahm","firstName":"Jon","playerId":"46970","status":"complete","position":"T2","total":"-6","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"E","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"-2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"68"}}],"thru":"F"},
    {"lastName":"Smalley","firstName":"Alex","playerId":"46340","status":"complete","position":"T2","total":"-6","rounds":[{"scoreToPar":"-3","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"-2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Thomas","firstName":"Justin","playerId":"33448","status":"complete","position":"T4","total":"-5","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-5","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"65"}}],"thru":"F"},
    {"lastName":"Åberg","firstName":"Ludvig","playerId":"52955","status":"complete","position":"T4","total":"-5","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-4","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"66"}},{"scoreToPar":"-2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Schmid","firstName":"Matti","playerId":"48867","status":"complete","position":"T4","total":"-5","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-5","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"65"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Smith","firstName":"Cameron","playerId":"35891","status":"complete","position":"T7","total":"-4","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"-2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"68"}}],"thru":"F"},
    {"lastName":"McIlroy","firstName":"Rory","playerId":"28237","status":"complete","position":"T7","total":"-4","rounds":[{"scoreToPar":"+4","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"74"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"-4","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"66"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Schauffele","firstName":"Xander","playerId":"48081","status":"complete","position":"T7","total":"-4","rounds":[{"scoreToPar":"-2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"-4","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"66"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Kitayama","firstName":"Kurt","playerId":"48117","status":"complete","position":"T10","total":"-3","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+5","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"75"}},{"scoreToPar":"-7","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"63"}}],"thru":"F"},
    {"lastName":"Gotterup","firstName":"Chris","playerId":"59095","status":"complete","position":"T10","total":"-3","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-5","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"65"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Rose","firstName":"Justin","playerId":"22405","status":"complete","position":"T10","total":"-3","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"-5","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"65"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Reed","firstName":"Patrick","playerId":"34360","status":"complete","position":"T10","total":"-3","rounds":[{"scoreToPar":"-2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Fitzpatrick","firstName":"Matt","playerId":"40098","status":"complete","position":"T14","total":"-2","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-5","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"65"}}],"thru":"F"},
    {"lastName":"Scheffler","firstName":"Scottie","playerId":"46046","status":"complete","position":"T14","total":"-2","rounds":[{"scoreToPar":"-3","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Greyserman","firstName":"Max","playerId":"51977","status":"complete","position":"T14","total":"-2","rounds":[{"scoreToPar":"-2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Griffin","firstName":"Ben","playerId":"54591","status":"complete","position":"T14","total":"-2","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"E","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Spieth","firstName":"Jordan","playerId":"34046","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"E","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"68"}}],"thru":"F"},
    {"lastName":"Jaeger","firstName":"Stephan","playerId":"36799","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"-3","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"E","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Harrington","firstName":"Padraig","playerId":"20766","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"+4","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"74"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"-3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"-1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"69"}}],"thru":"F"},
    {"lastName":"Puig","firstName":"David","playerId":"61193","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"English","firstName":"Harris","playerId":"34099","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Lee","firstName":"Min Woo","playerId":"37378","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"-3","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"E","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"71"}}],"thru":"F"},
    {"lastName":"Niemann","firstName":"Joaquin","playerId":"45486","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"-4","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"66"}},{"scoreToPar":"+1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"71"}}],"thru":"F"},
    {"lastName":"McNealy","firstName":"Maverick","playerId":"46442","status":"complete","position":"T18","total":"-1","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"72"}}],"thru":"F"},
    {"lastName":"Noren","firstName":"Alex","playerId":"27349","status":"complete","position":"T26","total":"E","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"E","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-4","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"66"}}],"thru":"F"},
    {"lastName":"Young","firstName":"Cameron","playerId":"57366","status":"complete","position":"T26","total":"E","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Burns","firstName":"Sam","playerId":"47504","status":"complete","position":"T26","total":"E","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-3","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"71"}}],"thru":"F"},
    {"lastName":"Matsuyama","firstName":"Hideki","playerId":"32839","status":"complete","position":"T26","total":"E","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"72"}}],"thru":"F"},
    {"lastName":"Cantlay","firstName":"Patrick","playerId":"35450","status":"complete","position":"T35","total":"+1","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+4","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"74"}},{"scoreToPar":"-2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"68"}}],"thru":"F"},
    {"lastName":"Kim","firstName":"Si Woo","playerId":"37455","status":"complete","position":"T35","total":"+1","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"67"}},{"scoreToPar":"+2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+1","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"71"}}],"thru":"F"},
    {"lastName":"Morikawa","firstName":"Collin","playerId":"50525","status":"complete","position":"T55","total":"+3","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+4","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"74"}},{"scoreToPar":"-2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"68"}}],"thru":"F"},
    {"lastName":"Conners","firstName":"Corey","playerId":"39997","status":"complete","position":"T55","total":"+3","rounds":[{"scoreToPar":"-2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"+2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"E","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"70"}}],"thru":"F"},
    {"lastName":"Koepka","firstName":"Brooks","playerId":"36689","status":"complete","position":"T55","total":"+3","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"+4","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"74"}}],"thru":"F"},
    {"lastName":"Fowler","firstName":"Rickie","playerId":"32102","status":"complete","position":"T60","total":"+4","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"-2","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"+5","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"75"}}],"thru":"F"},
    {"lastName":"Day","firstName":"Jason","playerId":"28089","status":"complete","position":"T65","total":"+6","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"E","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+5","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"75"}},{"scoreToPar":"+2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"72"}}],"thru":"F"},
    {"lastName":"Brennan","firstName":"Michael","playerId":"61522","status":"complete","position":"81","total":"+11","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-1","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+8","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"78"}}],"thru":"F"},
    {"lastName":"Campbell","firstName":"Brian","playerId":"46443","status":"complete","position":"82","total":"+18","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+12","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"82"}},{"scoreToPar":"+2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"72"}}],"thru":"F"},
    # Højgaard
    {"lastName":"Højgaard","firstName":"Nicolai","playerId":"52453","status":"complete","position":"T44","total":"+2","rounds":[{"scoreToPar":"-1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"69"}},{"scoreToPar":"+5","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"75"}},{"scoreToPar":"-4","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"66"}},{"scoreToPar":"+2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"72"}}],"thru":"F"},
    {"lastName":"Reitan","firstName":"Kristoffer","playerId":"49855","status":"complete","position":"T44","total":"+2","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"-5","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"65"}},{"scoreToPar":"+4","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"74"}}],"thru":"F"},
    {"lastName":"Lowry","firstName":"Shane","playerId":"33204","status":"complete","position":"T44","total":"+2","rounds":[{"scoreToPar":"-2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"68"}},{"scoreToPar":"+6","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"76"}},{"scoreToPar":"E","roundId":{"$numberInt":"3"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"-2","roundId":{"$numberInt":"4"},"strokes":{"$numberInt":"68"}}],"thru":"F"},
    # CUT players
    {"lastName":"Im","firstName":"Sungjae","playerId":"39971","status":"cut","position":"CUT","total":"+5","rounds":[{"scoreToPar":"+3","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}}],"thru":"-"},
    {"lastName":"MacIntyre","firstName":"Robert","playerId":"52215","status":"cut","position":"CUT","total":"+5","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+5","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"75"}}],"thru":"-"},
    {"lastName":"Fleetwood","firstName":"Tommy","playerId":"30911","status":"cut","position":"CUT","total":"+5","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}}],"thru":"-"},
    {"lastName":"Bhatia","firstName":"Akshay","playerId":"56630","status":"cut","position":"CUT","total":"+5","rounds":[{"scoreToPar":"+1","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"71"}},{"scoreToPar":"+4","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"74"}}],"thru":"-"},
    {"lastName":"Henley","firstName":"Russell","playerId":"34098","status":"cut","position":"CUT","total":"+5","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}}],"thru":"-"},
    {"lastName":"Hovland","firstName":"Viktor","playerId":"46717","status":"cut","position":"CUT","total":"+6","rounds":[{"scoreToPar":"+4","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"74"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}}],"thru":"-"},
    {"lastName":"Straka","firstName":"Sepp","playerId":"49960","status":"cut","position":"CUT","total":"+6","rounds":[{"scoreToPar":"+3","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"73"}},{"scoreToPar":"+3","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"73"}}],"thru":"-"},
    {"lastName":"Bradley","firstName":"Keegan","playerId":"33141","status":"cut","position":"CUT","total":"+6","rounds":[{"scoreToPar":"+4","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"74"}},{"scoreToPar":"+2","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"72"}}],"thru":"-"},
    {"lastName":"Woodland","firstName":"Gary","playerId":"31323","status":"cut","position":"CUT","total":"+6","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+4","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"74"}}],"thru":"-"},
    {"lastName":"Hatton","firstName":"Tyrrell","playerId":"34363","status":"cut","position":"CUT","total":"+6","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+4","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"74"}}],"thru":"-"},
    {"lastName":"DeChambeau","firstName":"Bryson","playerId":"47959","status":"cut","position":"CUT","total":"+7","rounds":[{"scoreToPar":"+6","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"76"}},{"scoreToPar":"+1","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"71"}}],"thru":"-"},
    {"lastName":"Scott","firstName":"Adam","playerId":"24502","status":"cut","position":"CUT","total":"+8","rounds":[{"scoreToPar":"+2","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"72"}},{"scoreToPar":"+6","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"76"}}],"thru":"-"},
    {"lastName":"Spaun","firstName":"J.J.","playerId":"39324","status":"cut","position":"CUT","total":"+6","rounds":[{"scoreToPar":"E","roundId":{"$numberInt":"1"},"strokes":{"$numberInt":"70"}},{"scoreToPar":"+6","roundId":{"$numberInt":"2"},"strokes":{"$numberInt":"76"}}],"thru":"-"},
]

# ─── Helpers ──────────────────────────────────────────────────────────────────
def unwrap(v):
    if isinstance(v, dict):
        for k in ['$numberInt', '$numberDouble', '$numberLong']:
            if k in v:
                return v[k]
    return v

CHAR_MAP = {
    'å':'a','Å':'A','ä':'a','Ä':'A','ö':'o','Ö':'O','ø':'o','Ø':'O',
    'ü':'u','Ü':'U','é':'e','É':'E','è':'e','È':'E','ê':'e','Ê':'E',
    'á':'a','Á':'A','à':'a','À':'A','ñ':'n','Ñ':'N','ó':'o','Ó':'O',
    'ú':'u','Ú':'U','í':'i','Í':'I',
}

def normalize_name(name):
    if not name:
        return ''
    for ch, rep in CHAR_MAP.items():
        name = name.replace(ch, rep)
    nfd = unicodedata.normalize('NFD', name)
    ascii_str = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    return re.sub(r'[-\s]+', ' ', ascii_str).strip().lower()

def clean_for_firestore(obj):
    """Recursively remove MongoDB Extended JSON wrappers."""
    if isinstance(obj, dict):
        keys = list(obj.keys())
        # Unwrap $numberInt etc.
        for k in ['$numberInt', '$numberDouble', '$numberLong']:
            if k in obj:
                return int(obj[k]) if k != '$numberDouble' else float(obj[k])
        if '$date' in obj:
            return clean_for_firestore(obj['$date'])
        return {k: clean_for_firestore(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_firestore(i) for i in obj]
    return obj

def parse_stp(s):
    """Parse scoreToPar string to int."""
    if s in ('E', '', None, '-'):
        return 0
    v = unwrap(s)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

def get_round_score(player, round_num):
    """Return {score, isLive, isPenalty} for a player's round, or score=None if not played."""
    for r in player.get('rounds', []):
        rid = int(unwrap(r.get('roundId', {}).get('$numberInt', 0)))
        if rid == round_num:
            stp = r.get('scoreToPar')
            if stp is not None and stp != '-':
                return {'score': parse_stp(stp), 'isLive': False, 'isPenalty': False}
    return {'score': None, 'isLive': False, 'isPenalty': False}

def sum_best_n(round_score_list, n):
    """Sum n lowest scores from list of {score, ...} objects. Returns None if no valid scores."""
    scores = [s['score'] for s in round_score_list if s and s.get('score') is not None]
    if not scores:
        return None
    return sum(sorted(scores)[:n])

# ─── Build name index ─────────────────────────────────────────────────────────
name_index = {}
last_name_index = {}
for p in OFFICIAL_ROWS:
    full = normalize_name(f"{p['firstName']} {p['lastName']}")
    if full and full not in name_index:
        name_index[full] = p
    last = normalize_name(p['lastName'])
    if last:
        last_name_index.setdefault(last, []).append(p)

def find_player(golfer_name):
    norm = normalize_name(golfer_name)
    player = name_index.get(norm)
    if not player:
        parts = norm.split()
        if len(parts) >= 2:
            last = parts[-1]
            candidates = last_name_index.get(last, [])
            for c in candidates:
                first = normalize_name(c.get('firstName', ''))
                if any(part in first or first in part for part in parts[:-1]):
                    player = c
                    break
    return player

# ─── Compute cut penalties ────────────────────────────────────────────────────
worst_round_scores = {}
for rnum in [1, 2, 3, 4]:
    worst = None
    for p in OFFICIAL_ROWS:
        if p.get('status') != 'cut':
            rs = get_round_score(p, rnum)
            if rs['score'] is not None:
                if worst is None or rs['score'] > worst:
                    worst = rs['score']
    worst_round_scores[rnum] = (worst + 1) if worst is not None else None

print(f'Cut penalties: {worst_round_scores}')

# ─── Load teams ───────────────────────────────────────────────────────────────
tourn = db.collection('tournaments').document(TOURN_ID).get().to_dict()
teams = tourn.get('teams', [])
print(f'Teams: {len(teams)}')

# ─── Calculate team scores ────────────────────────────────────────────────────
team_scores = []

for team in teams:
    team_name = team.get('name', '')
    golfer_names = team.get('golferNames', [])
    team_rounds = {'r1': [], 'r2': [], 'r3': [], 'r4': []}
    players_out = []

    for gname in golfer_names:
        found = find_player(gname)
        if not found:
            print(f'  WARNING: {gname} not found')
            placeholder = {
                'name': gname, 'status': 'Missing', 'total': None, 'thru': '',
                'isCut': False, 'cutPenaltyScore': None,
                'r1': {'score': None, 'isLive': False, 'isPenalty': False},
                'r2': {'score': None, 'isLive': False, 'isPenalty': False},
                'r3': {'score': None, 'isLive': False, 'isPenalty': False},
                'r4': {'score': None, 'isLive': False, 'isPenalty': False},
            }
            players_out.append(placeholder)
            for rk in team_rounds:
                team_rounds[rk].append({'score': None, 'isLive': False, 'isPenalty': False})
            continue

        is_cut = found.get('status', '').lower() == 'cut'
        golfer_round_scores = {}
        cut_total = 0
        cut_penalty_rounds = []

        for rnum in [1, 2, 3, 4]:
            rk = f'r{rnum}'
            rs = get_round_score(found, rnum)
            if is_cut and rs['score'] is None:
                pen = worst_round_scores[rnum]
                if pen is not None:
                    rs = {'score': pen, 'isLive': False, 'isPenalty': True}
                    cut_total += pen
                    cut_penalty_rounds.append(rnum)
                else:
                    rs['isPenalty'] = False
            else:
                rs['isPenalty'] = False
                if rs['score'] is not None:
                    cut_total += rs['score'] if is_cut else 0
            golfer_round_scores[rk] = rs

        total_val = parse_stp(found.get('total', 'E')) if not is_cut else cut_total

        processed = {
            'name': f"{found['firstName']} {found['lastName']}".strip(),
            'status': found.get('status', ''),
            'total': total_val,
            'thru': found.get('thru', 'F'),
            'isCut': is_cut,
            'cutPenaltyScore': {f'r{r}': worst_round_scores[r] for r in cut_penalty_rounds} if cut_penalty_rounds else None,
            **golfer_round_scores
        }
        players_out.append(processed)
        for rk in team_rounds:
            team_rounds[rk].append(golfer_round_scores[rk])

    # Best 3-of-4 per round
    total_score = 0
    round_details = {}
    for rk in ['r1', 'r2', 'r3', 'r4']:
        best = sum_best_n(team_rounds[rk], 3)
        penalty_count = sum(1 for s in team_rounds[rk] if s and s.get('isPenalty'))
        valid_count = sum(1 for s in team_rounds[rk] if s and s.get('score') is not None)
        round_details[rk] = {'score': best, 'penaltyScores': penalty_count, 'validScores': valid_count}
        if best is not None:
            total_score += best

    team_scores.append({
        'teamName': team_name,
        'team': team_name,
        'totalScore': total_score,
        'players': players_out,
        'roundDetails': round_details,
        'cutPlayersCount': sum(1 for p in players_out if p.get('isCut')),
        'penaltyStrokesApplied': sum(rd['penaltyScores'] for rd in round_details.values()),
        'worstRoundScores': {f'r{k}': v for k, v in worst_round_scores.items()},
        'validRounds': sum(1 for rd in round_details.values() if rd['score'] is not None),
        'ownerUid': team.get('ownerUid', '')
    })

team_scores.sort(key=lambda x: (x['totalScore'] is None, x['totalScore']))

print('\nFinal Results:')
for i, t in enumerate(team_scores):
    rd = t['roundDetails']
    print(f"  {i+1}. {t['teamName']}: {t['totalScore']}  "
          f"(r1:{rd['r1']['score']} r2:{rd['r2']['score']} r3:{rd['r3']['score']} r4:{rd['r4']['score']})")
    for p in t['players']:
        r1s = p['r1'].get('score')
        r2s = p['r2'].get('score')
        r3s = p['r3'].get('score')
        r4s = p['r4'].get('score')
        cut_flag = ' [CUT]' if p.get('isCut') else ''
        print(f"      {p['name']}{cut_flag}: r1={r1s} r2={r2s} r3={r3s} r4={r4s} total={p['total']}")

# ─── Write to Firestore ───────────────────────────────────────────────────────
leaderboard_data = clean_for_firestore({
    'orgId': '1', 'year': '2026', 'tournId': '033',
    'status': 'Official', 'roundId': {'$numberInt': '4'}, 'roundStatus': 'Official',
    'leaderboardRows': OFFICIAL_ROWS
})

db.collection('tournament_scores').document(TOURN_ID + '_latest').update({
    'teamScores': team_scores,
    'leaderboardData': leaderboard_data,
    'calculatedAt': firestore.SERVER_TIMESTAMP,
})
db.collection('tournaments').document(TOURN_ID).update({
    'lastCalculatedScores': team_scores,
    'lastScoreCalculation': firestore.SERVER_TIMESTAMP,
})
print(f'\nWrote {len(team_scores)} team scores and official leaderboard data to Firestore.')
