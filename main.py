#!/usr/bin/env python3
# Ensure you activate your virtual environment before running this script:
# source venv/bin/activate (macOS/Linux)
# .\venv\Scripts\activate (Windows PowerShell/CMD)

import google.generativeai as genai
from config import GEMINI_API_KEY, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI, GEMINI_TEXT_MODEL, GEMINI_IMAGE_MODEL
import requests
import json
from flask import Flask, request, redirect, url_for, session, send_from_directory
import os
from PIL import Image
import io
import base64
import uuid # For unique filenames
# from google.generativelanguage_v1beta.types import GenerateContentConfig
# from google.generativeai import Client
# from google.generativeai import types
# import google.cloud.aiplatform as aiplatform
# from google.cloud.aiplatform_v1beta1 import types
# from google.cloud.aiplatform.services import prediction_service

app = Flask(__name__)
app.secret_key = os.urandom(24) # Replace with a strong, permanent secret key in production

genai.configure(api_key=GEMINI_API_KEY)
# imagen_client = prediction_service.PredictionServiceClient(client_options={"api_endpoint": "us-central1-aiplatform.googleapis.com"})

def generate_linkedin_post(prompt):
    # Refine the prompt for better engagement, including hashtags and a call to action.
    full_prompt = f"""Generate a professional and engaging LinkedIn post based on the following topic: "{prompt}".
    The post should be concise, informative, and establish the author as an expert in AI Coding, solutions, and business automations.
    Include 3-5 relevant hashtags and a clear call to action (e.g., connect, learn more, discuss).
    """
    model = genai.GenerativeModel(GEMINI_TEXT_MODEL)
    response = model.generate_content(full_prompt)
    return response.text

def generate_ai_image(prompt):
    # Using Gemini's built-in multimodal capabilities for image generation.
    # The model must support 'TEXT' and 'IMAGE' response modalities.
    try:
        model = genai.GenerativeModel(GEMINI_IMAGE_MODEL)
        # Pass response_modalities as part of a dictionary for generation_config
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "image/jpeg", # Specify the desired MIME type for the image
                "response_modalities": ["TEXT", "IMAGE"]
            }
        )
        
        # Iterate through parts to find image data
        if response and response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    image_data_b64 = part.inline_data.data # This is already base64 encoded
                    image_bytes = base64.b64decode(image_data_b64)
                    
                    # Create static folder if it doesn't exist
                    static_folder = os.path.join(app.root_path, 'static')
                    os.makedirs(static_folder, exist_ok=True)
                    
                    # Save the image locally with a unique filename
                    filename = f"{uuid.uuid4()}.png"
                    filepath = os.path.join(static_folder, filename)
                    with open(filepath, 'wb') as f:
                        f.write(image_bytes)
                        
                    local_image_url = url_for('static', filename=filename)
                    print(f"DEBUG: Saved image to {filepath}, accessible at {local_image_url}")
                    return local_image_url # Return URL for local serving
            print(f"DEBUG: Gemini API returned no inline image data for prompt: {prompt}")
            return "https://via.placeholder.com/150"
        else:
            print(f"DEBUG: Gemini API returned no candidates or content for prompt: {prompt}")
            return "https://via.placeholder.com/150"
    except Exception as e:
        print(f"DEBUG: Error generating image with {GEMINI_IMAGE_MODEL}: {e}")
        return "https://via.placeholder.com/150"

@app.route('/login/linkedin')
def linkedin_login():
    # Define the scope of permissions your app needs
    scope = "profile email w_member_social"
    state = os.urandom(16).hex() # Generate a random state for CSRF protection
    session['oauth_state'] = state
    # Construct the authorization URL
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization?response_type=code"
        f"&client_id={LINKEDIN_CLIENT_ID}"
        f"&redirect_uri={LINKEDIN_REDIRECT_URI}"
        f"&scope={scope}"
        f"&state={state}"
    )
    return redirect(auth_url)

@app.route('/auth/linkedin/callback')
def linkedin_callback():
    code = request.args.get('code')
    state = request.args.get('state')

    # Verify the state parameter to prevent CSRF
    if 'oauth_state' not in session or state != session['oauth_state']:
        return "Error: Invalid state parameter.", 400
    del session['oauth_state'] # State parameter should be used only once

    if not code:
        return "Error: Authorization code not received."

    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': LINKEDIN_REDIRECT_URI,
        'client_id': LINKEDIN_CLIENT_ID,
        'client_secret': LINKEDIN_CLIENT_SECRET,
    }

    response = requests.post(token_url, data=payload)
    token_data = response.json()

    if 'access_token' in token_data:
        session['linkedin_access_token'] = token_data['access_token']
        return redirect(url_for('home'))  # Redirect to a home page or success page
    else:
        return f"Error exchanging code for token: {token_data.get('error_description', token_data)}"

@app.route('/')
def home():
    # This will be our main interface for the CLI-like interaction
    # We'll move the existing main() logic here or call parts of it.
    if 'linkedin_access_token' not in session:
        return '<a href="/login/linkedin">Login with LinkedIn</a>'
    else:
        return redirect(url_for('generate_post_page'))

@app.route('/generate_post', methods=['GET', 'POST'])
def generate_post_page():
    if 'linkedin_access_token' not in session:
        return redirect(url_for('linkedin_login'))

    post_content = session.get('generated_post_content')
    image_url = session.get('generated_image_url')
    
    if request.method == 'POST':
        if 'generate_button' in request.form: # First step: Generate Post
            final_topic = request.form['topic']
            
            post_content = generate_linkedin_post(f"Write a LinkedIn post about: {final_topic}. Make sure to include relevant hashtags and a call to action to connect or learn more about AI solutions.")
            image_prompt = f"Generate an image related to: {final_topic}"
            image_url = generate_ai_image(image_prompt)
            
            # Store in session for review step
            session['generated_post_content'] = post_content
            session['generated_image_url'] = image_url
            
            # Redirect to GET to show generated content and confirmation buttons
            return redirect(url_for('generate_post_page'))
            
        elif 'confirm_post' in request.form: # Second step: Confirm Post
            if post_content and image_url: # Ensure content exists in session
                post_to_linkedin(session.get('linkedin_access_token'), post_content, image_url)
                session.pop('generated_post_content', None)
                session.pop('generated_image_url', None)
                return "Post sent to LinkedIn successfully (placeholder)!"
            else:
                return "Error: No content to confirm."
        elif 'cancel_post' in request.form: # User cancelled
            session.pop('generated_post_content', None)
            session.pop('generated_image_url', None)
            return "Post cancelled and not sent to LinkedIn."
    
    # GET request or after initial generation
    topics_text = suggest_trending_topics()

    # Build the HTML response based on whether content has been generated
    html_content = f"""<!DOCTYPE html>
<html>
<head><title>LinkedIn AI Blogger</title></head>
<body>
    <h1>LinkedIn AI Blogger</h1>
    <h2>Suggested Topics:</h2>
    <pre>{topics_text}</pre>
    <form method="POST" action="/generate_post">
        <label for="topic">Enter topic or selected number:</label><br>
        <input type="text" id="topic" name="topic" value="{request.form.get('topic', '')}"><br><br>
        <input type="submit" name="generate_button" value="Generate Post">
    </form>
    <hr>
    """
    if post_content:
        html_content += f"""<h2>Generated Post Preview:</h2>
<textarea rows="10" cols="80" readonly>{post_content}</textarea><br><br>
<img src="{image_url}" alt="AI Generated Image" style="max-width:300px;"><br><br>
<form method="POST" action="/generate_post">
    <input type="submit" name="confirm_post" value="Post to LinkedIn">
    <input type="submit" name="cancel_post" value="Cancel">
</form>
        """
    html_content += """</body>
</html>"""

    return html_content

def suggest_trending_topics():
    prompt = "Suggest 5-7 trending topics related to AI Technology, AI Marketing, AI Coding, AI solutions, automations, and business automations, suitable for LinkedIn posts to establish expertise and drive engagement. Provide them as a numbered list."
    model = genai.GenerativeModel(GEMINI_TEXT_MODEL)
    response = model.generate_content(prompt)
    return response.text

def post_to_linkedin(linkedin_access_token, post_content, image_url=None):
    headers = {
        'Authorization': f'Bearer {linkedin_access_token}',
        'Content-Type': 'application/json',
        'x-li-format': 'json',
    }
    payload = {
        "author": f"urn:li:person:{linkedin_access_token.split('-')[0]}",  # This is a simplification
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": post_content
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }
    
    if image_url:
        payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "IMAGE"
        payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
            {
                "status": "READY",
                "media": image_url, # This would be a URN from LinkedIn's asset API
                "title": {"text": "AI Generated Image"}
            }
        ]
    
    # This is a placeholder for the actual API call
    # url = "https://api.linkedin.com/v2/ugcPosts"
    # response = requests.post(url, headers=headers, data=json.dumps(payload))
    # response.raise_for_status() # Raise an exception for HTTP errors
    print(f"Attempting to post to LinkedIn: {post_content}")
    if image_url:
        print(f"With image URL: {image_url}")
    print("LinkedIn posting functionality is currently a placeholder and needs real API integration.")

if __name__ == "__main__":
    # For development, run Flask app directly
    # In a real deployment, you'd use a production-ready WSGI server
    app.run(debug=True, port=3000)
