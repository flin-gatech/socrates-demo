from flask import Flask, render_template, request, jsonify
import requests
import json
import os
import logging

app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API configuration
API_KEY = os.environ.get('QWEN_API_KEY', 'sk-9ec24e8e7f6544b19d5326518007ba9e')
API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 简化的苏格拉底设定 - 让LLM自然发挥
SOCRATES_SYSTEM_PROMPT = """You are Socrates, the ancient Greek philosopher. Engage in natural Socratic dialogue with the user.

Key principles:
- Keep responses SHORT (1-3 sentences usually)
- "I know that I know nothing" - stay humble and curious
- Ask good questions rather than lecture
- Be genuinely interested in what they think
- Challenge ideas gently with questions
- Sound like a real person having a conversation

Style:
- Conversational and natural, not philosophical lecturing
- Curious and friendly
- Ask ONE focused question at a time
- Build on what they actually say
- Keep it simple and direct

Please engage authentically as Socrates would, without rigid structure. Let your wisdom and questioning nature guide the dialogue naturally."""

@app.route('/')
def index():
    """主页路由"""
    try:
        return render_template('chat.html')
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return f"Template error: {str(e)}", 500

@app.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'api_configured': bool(API_KEY)
    })

@app.route('/chat', methods=['POST'])
def chat():
    """处理聊天消息"""
    try:
        # 验证请求
        if not request.is_json:
            return jsonify({
                'error': 'Content-Type must be application/json',
                'success': False
            }), 400
        
        data = request.get_json()
        if not data:
            return jsonify({
                'error': 'No data provided', 
                'success': False
            }), 400
        
        user_message = data.get('message', '').strip()
        context = data.get('context', [])  # 对话历史
        
        # 输入验证
        if not user_message:
            return jsonify({
                'error': 'Please enter your message',
                'success': False
            }), 400
        
        if len(user_message) > 2000:
            return jsonify({
                'error': 'Message too long. Please keep it under 2000 characters.',
                'success': False
            }), 400
        
        # 检查API密钥
        if not API_KEY:
            return jsonify({
                'error': 'API configuration error. Please set QWEN_API_KEY environment variable.',
                'success': False
            }), 500
        
        # 构建对话消息
        messages = [
            {'role': 'system', 'content': SOCRATES_SYSTEM_PROMPT}
        ]
        
        # 添加对话历史（保留最近的对话以维持上下文）
        if context:
            # 只保留最近的10轮对话，避免token过多
            recent_context = context[-20:] if len(context) > 20 else context
            messages.extend(recent_context)
        
        # 添加当前用户消息
        messages.append({'role': 'user', 'content': user_message})
        
        # 准备API请求
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json'
        }
        
        api_data = {
            'model': 'qwen-plus',
            'messages': messages,
            'temperature': 0.8,  # 稍高一些，让回复更有创造性
            'max_tokens': 800,   # 给更多空间让LLM自由发挥
            'top_p': 0.9
        }
        
        logger.info(f"Sending request to Qwen API with {len(messages)} messages")
        
        # 调用API
        response = requests.post(
            API_BASE_URL, 
            headers=headers, 
            json=api_data, 
            timeout=30
        )
        response.raise_for_status()
        
        # 解析响应
        result = response.json()
        
        if 'choices' not in result or not result['choices']:
            logger.error(f"Invalid API response: {result}")
            return jsonify({
                'error': 'Invalid response from AI service',
                'success': False
            }), 502
        
        socrates_reply = result['choices'][0]['message']['content'].strip()
        
        if not socrates_reply:
            return jsonify({
                'error': 'Empty response from AI service', 
                'success': False
            }), 502
        
        logger.info("Successfully generated Socratic response")
        
        return jsonify({
            'reply': socrates_reply,
            'success': True
        })
    
    except requests.exceptions.Timeout:
        logger.error("API request timeout")
        return jsonify({
            'error': 'Request timeout. Please try again.',
            'success': False
        }), 504
    
    except requests.exceptions.ConnectionError:
        logger.error("Connection error to API")
        return jsonify({
            'error': 'Unable to connect to AI service.',
            'success': False
        }), 503
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error: {e}")
        status_code = e.response.status_code if e.response else 500
        
        if status_code == 401:
            return jsonify({
                'error': 'Authentication failed. Check API key.',
                'success': False
            }), 401
        elif status_code == 429:
            return jsonify({
                'error': 'Too many requests. Please wait.',
                'success': False  
            }), 429
        else:
            return jsonify({
                'error': f'AI service error: {status_code}',
                'success': False
            }), 502
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({
            'error': 'An unexpected error occurred.',
            'success': False
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Endpoint not found',
        'available_endpoints': ['/', '/chat', '/health']
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting Simple Socrates Chat on port {port}")
    logger.info(f"API Key configured: {bool(API_KEY)}")
    
    app.run(debug=debug, port=port, host='0.0.0.0')