import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
from groq import Groq
import json

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CLIENT_SECRET_FILE = os.getenv("GOOGLE_CREDENTIALS_PATH", "client_secret.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def authenticate_gmail():
    creds = None
    token_path = "token.json"

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    return creds



def extract_filters(query):
    client = Groq(api_key=GROQ_API_KEY)

    system_prompt = """
You are an assistant that extracts email search filters from a natural language question.

Only return a valid JSON with the following keys:
{
  "from": "sender email or domain, e.g. linkedin.com or ali@gmail.com",
  "to": "receiver email, if specified, else null",
  "subject_keywords": ["list", "of", "important", "subject", "words"],
  "contains": ["list", "of", "keywords", "from", "email", "body"],
  "date_range": "today | yesterday | last_3_days | last_week | any"
}

Use null or empty list if a field is not specified in the query.
Do not explain anything. Only return the raw JSON.
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
    )

    return response.choices[0].message.content

def build_query(filter_json):
    q_parts = []

    if filter_json.get("from"):
        q_parts.append(f"from:{filter_json['from']}")
    if filter_json.get("to"):
        q_parts.append(f"to:{filter_json['to']}")
    for word in filter_json.get("subject_keywords", []):
        q_parts.append(f"subject:{word}")
    for word in filter_json.get("contains", []):
        q_parts.append(word)

    date_range = filter_json.get("date_range", "")
    if date_range == "today":
        q_parts.append("newer_than:1d")
    elif date_range == "yesterday":
        q_parts.append("newer_than:2d older_than:1d")
    elif date_range == "last_3_days":
        q_parts.append("newer_than:3d")
    elif date_range == "last_week":
        q_parts.append("newer_than:7d")

    return " ".join(q_parts)

def get_emails(creds,gmail_query="", max_results=2):
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId="me", q=gmail_query, labelIds=["INBOX"], maxResults=max_results).execute()
    messages = results.get("messages", [])

    email_context = ""
    for msg in messages:
        msg_data = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        headers = msg_data["payload"]["headers"]
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
        to = next((h["value"] for h in headers if h["name"] == "To"), "")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")
        body = ""

        if "parts" in msg_data["payload"]:
            for part in msg_data["payload"]["parts"]:
                if part["mimeType"] == "text/plain":
                    body = part["body"].get("data", "")
                    break

        email_context += f"To: {to}\nFrom: {sender}\nSubject: {subject}\nBody: {body}\n---\n"
    return email_context

def ask_groq(question, context):
    client = Groq(api_key=GROQ_API_KEY)
    full_prompt = f"{question}\n\n{context}"
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an email assistant. Use only the following email data to answer the user's question. Do NOT say you don't have access. Do NOT simulate. Just answer using the context provided."},
                {"role": "user", "content": full_prompt}
            ],
            model="llama-3.1-8b-instant"
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error Occured: {e}"


def handle_email_query(query: str):
    creds = authenticate_gmail()
    filter_json_str = extract_filters(query)
    filter_json = json.loads(filter_json_str)    
    gmail_query = build_query(filter_json)
    context = get_emails(creds, gmail_query=gmail_query)
    result = ask_groq(query, context)
    return result


query = "List all the persons who send me email today"
print(handle_email_query(query))