from flask import Flask, render_template, request, jsonify
import requests
import json
import os
import logging
from datetime import datetime
import uuid

app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API configuration  
API_KEY = os.environ.get('QWEN_API_KEY', 'sk-9ec24e8e7f6544b19d5326518007ba9e')
API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 简单的内存存储（生产环境建议使用数据库）
chat_sessions = {}

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
        session_id = data.get('session_id')
        student_id = data.get('student_id', 'default')
        
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
        
        # 创建或获取会话
        if not session_id:
            session_id = str(uuid.uuid4())
            chat_sessions[session_id] = {
                'id': session_id,
                'student_id': student_id,
                'title': user_message[:30] + '...' if len(user_message) > 30 else user_message,
                'created_at': datetime.now().isoformat(),
                'messages': []
            }
        
        session = chat_sessions.get(session_id, {
            'id': session_id,
            'student_id': student_id,
            'title': user_message[:30] + '...' if len(user_message) > 30 else user_message,
            'created_at': datetime.now().isoformat(),
            'messages': []
        })
        chat_sessions[session_id] = session
        
        # 添加用户消息到会话
        session['messages'].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
        
        # 构建对话消息（使用context如果有，否则使用session messages）
        messages = []
        
        # 添加对话历史
        if context:
            # 只保留最近的10轮对话，避免token过多
            recent_context = context[-20:] if len(context) > 20 else context
            messages.extend(recent_context)
        else:
            # 使用会话中的消息
            api_messages = [{'role': msg['role'], 'content': msg['content']} 
                           for msg in session['messages'] if msg['role'] in ['user', 'assistant']]
            messages.extend(api_messages[-20:])  # 只取最近20条
        
        # 确保最后一条是用户消息
        if not messages or messages[-1]['role'] != 'user':
            messages.append({'role': 'user', 'content': user_message})
        
        # 准备API请求
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json'
        }
        
        api_data = {
            'model': 'qwen-plus',
            'messages': messages,
            'temperature': 0.7,
            'max_tokens': 800,
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
        
        ai_reply = result['choices'][0]['message']['content'].strip()
        
        if not ai_reply:
            return jsonify({
                'error': 'Empty response from AI service', 
                'success': False
            }), 502
        
        # 添加AI回复到会话
        session['messages'].append({
            'role': 'assistant',
            'content': ai_reply,
            'timestamp': datetime.now().isoformat()
        })
        
        logger.info("Successfully generated AI response")
        
        return jsonify({
            'reply': ai_reply,
            'success': True,
            'session_id': session_id
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

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """获取会话列表"""
    try:
        student_id = request.args.get('student_id', 'default')
        
        # 筛选该学生的会话
        student_sessions = [
            {
                'id': session['id'],
                'title': session['title'],
                'created_at': session['created_at'],
                'message_count': len([m for m in session['messages'] if m['role'] == 'user'])
            }
            for session in chat_sessions.values()
            if session.get('student_id') == student_id
        ]
        
        # 按创建时间倒序排序
        student_sessions.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({'sessions': student_sessions})
        
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    """获取特定会话的详细信息"""
    try:
        session = chat_sessions.get(session_id)
        
        if not session:
            return jsonify({'error': '会话不存在'}), 404
        
        return jsonify(session)
        
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """删除会话"""
    try:
        if session_id in chat_sessions:
            del chat_sessions[session_id]
            return jsonify({'message': '会话已删除'})
        else:
            return jsonify({'error': '会话不存在'}), 404
            
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions', methods=['POST'])
def create_session():
    """创建新会话"""
    try:
        data = request.json or {}
        student_id = data.get('student_id', 'default')
        
        session_id = str(uuid.uuid4())
        chat_sessions[session_id] = {
            'id': session_id,
            'student_id': student_id,
            'title': '新对话',
            'created_at': datetime.now().isoformat(),
            'messages': []
        }
        
        return jsonify({
            'session_id': session_id,
            'message': '新会话已创建'
        })
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Endpoint not found',
        'available_endpoints': ['/', '/chat', '/health', '/api/sessions']
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting AI Chat on port {port}")
    logger.info(f"API Key configured: {bool(API_KEY)}")
    
    app.run(debug=debug, port=port, host='0.0.0.0')