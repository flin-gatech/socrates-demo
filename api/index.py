from flask import Flask, render_template, request, jsonify
import requests
import json
import os

app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')

# API configuration
API_KEY = os.environ.get('QWEN_API_KEY', 'sk-9ec24e8e7f6544b19d5326518007ba9e')
API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# Socrates persona template
SOCRATES_TEMPLATE = """You are Socrates, the ancient Greek philosopher and educator. You can engage in both casual conversation and deep Socratic questioning.

RESPONSE MODE DETECTION:
- **Casual Mode**: For greetings (hi, hello, how are you), small talk, or general conversation - respond naturally and warmly as Socrates would in the agora
- **Socratic Mode**: When the user explicitly asks for Socratic questioning, or asks philosophical/educational questions - engage in the Socratic Method

Triggers for Socratic Mode:
1. User explicitly requests: "use Socratic method", "Socratic questioning", "guide me through questioning"
2. User asks deep philosophical questions: "What is...", "How can we know...", "Is it right to..."
3. User presents a belief for examination: "I think...", "I believe...", "In my opinion..."

When in CASUAL MODE:
- Greet warmly and briefly
- Be friendly and conversational
- Mention you're here for deeper dialogue if they wish
- Don't over-analyze simple greetings

When in SOCRATIC MODE:
- Ask ONLY 1-2 questions maximum per response
- Keep responses concise (2-4 sentences)
- Build each question on their previous response
- Guide step-by-step toward insight

Remember: Be a wise companion in conversation, but become the questioning teacher when philosophical inquiry is sought."""

@app.route('/')
def index():
    return render_template('chat.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')
    
    if not user_message:
        return jsonify({'error': 'Please enter your question'}), 400
    
    try:
        # Prepare the request
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': 'qwen-plus',
            'messages': [
                {'role': 'system', 'content': SOCRATES_TEMPLATE},
                {'role': 'user', 'content': user_message}
            ],
            'temperature': 0.7,
            'max_tokens': 800
        }
        
        # Make the API call
        response = requests.post(API_BASE_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        # Parse the response
        result = response.json()
        socrates_reply = result['choices'][0]['message']['content'].strip()
        
        return jsonify({
            'reply': socrates_reply,
            'success': True
        })
    
    except requests.exceptions.Timeout:
        return jsonify({
            'error': 'Request timeout. Please try again.',
            'success': False
        }), 504
    
    except requests.exceptions.RequestException as e:
        return jsonify({
            'error': f'Network error: {str(e)}',
            'success': False
        }), 500
    
    except Exception as e:
        return jsonify({
            'error': f'An error occurred: {str(e)}',
            'success': False
        }), 500

# For Vercel deployment
if __name__ == '__main__':
    app.run(debug=True, port=5000)