from flask import Flask, render_template, request, jsonify, redirect, url_for
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

# 加载学生配置
def load_students_config():
    """加载学生分组配置"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'students_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading students config: {e}")
        return {"groups": {}}

STUDENTS_CONFIG = load_students_config()

def get_student_group(student_id):
    """根据学号获取学生所属组"""
    for group_id, group_info in STUDENTS_CONFIG['groups'].items():
        if student_id in group_info['students']:
            return {
                'group_id': group_id,
                'group_name': group_info['name'],
                'llm_type': group_info['llm_type'],
                'description': group_info['description']
            }
    return None

@app.route('/')
def index():
    """主页路由 - 聊天界面"""
    try:
        return render_template('chat.html')
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return f"Template error: {str(e)}", 500

@app.route('/login')
def login_page():
    """登录页面"""
    try:
        return render_template('login.html')
    except Exception as e:
        logger.error(f"Error serving login page: {e}")
        return f"Template error: {str(e)}", 500

@app.route('/api/login', methods=['POST'])
def login():
    """学生登录验证"""
    try:
        data = request.get_json()
        student_id = data.get('student_id', '').strip().upper()
        
        if not student_id:
            return jsonify({
                'success': False,
                'error': '请输入学号'
            }), 400
        
        # 查找学生所属组
        group_info = get_student_group(student_id)
        
        if not group_info:
            return jsonify({
                'success': False,
                'error': '学号不存在，请检查后重试'
            }), 404
        
        logger.info(f"Student {student_id} logged in, group: {group_info['group_id']}")
        
        return jsonify({
            'success': True,
            'student_id': student_id,
            'group': group_info['group_id'],
            'group_name': group_info['group_name'],
            'llm_type': group_info['llm_type'],
            'description': group_info['description']
        })
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({
            'success': False,
            'error': '登录失败，请稍后重试'
        }), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """学生登出"""
    return jsonify({'success': True, 'message': '已登出'})

@app.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'api_configured': bool(API_KEY),
        'students_loaded': len(STUDENTS_CONFIG.get('groups', {}))
    })

# ================== LLM调用接口 ==================

def call_srl_llm(messages, student_id):
    """
    Group 1: SRL辅助的LLM
    Self-Regulated Learning (自我调节学习) 支持
    
    TODO: 添加SRL相关的系统提示词和引导
    - 鼓励学生设定学习目标
    - 监控学习进度
    - 反思学习策略
    - 提供元认知支持
    """
    system_prompt = {
        'role': 'system',
        'content': '''你是一个支持自我调节学习(SRL)的AI助手。请在回答中：
1. 鼓励学生设定明确的学习目标
2. 帮助学生监控自己的学习进度
3. 引导学生反思学习策略的有效性
4. 提供元认知支持，帮助学生"学会如何学习"

在适当的时候询问：
- 你的学习目标是什么？
- 你觉得这个方法对你有效吗？
- 你可以如何改进你的学习策略？'''
    }
    
    # 在消息列表开头添加系统提示
    messages_with_prompt = [system_prompt] + messages
    
    return call_qwen_api(messages_with_prompt)

def call_ai_ethics_llm(messages, student_id):
    """
    Group 2: AI Ethics辅助的LLM
    AI伦理教育支持
    
    TODO: 添加AI伦理相关的引导
    - 讨论AI的偏见和公平性
    - 强调数据隐私和安全
    - 培养批判性思维
    - 讨论AI的社会影响
    """
    system_prompt = {
        'role': 'system',
        'content': '''你是一个注重AI伦理教育的AI助手。在回答中：
1. 适时讨论AI技术的伦理问题（偏见、公平性、隐私等）
2. 鼓励学生批判性地思考AI的使用
3. 强调负责任地使用AI工具的重要性
4. 帮助学生理解AI的局限性和潜在风险

在相关话题中引导思考：
- AI在这个领域可能存在什么偏见？
- 使用AI时需要注意哪些伦理问题？
- 如何负责任地使用AI技术？'''
    }
    
    messages_with_prompt = [system_prompt] + messages
    
    return call_qwen_api(messages_with_prompt)

def call_srl_and_ethics_llm(messages, student_id):
    """
    Group 3: SRL + AI Ethics 双重辅助的LLM
    结合自我调节学习和AI伦理教育
    
    TODO: 整合SRL和AI伦理的引导
    """
    system_prompt = {
        'role': 'system',
        'content': '''你是一个同时支持自我调节学习(SRL)和AI伦理教育的AI助手。

SRL方面：
- 鼓励设定学习目标并监控进度
- 引导反思学习策略
- 提供元认知支持

AI伦理方面：
- 讨论AI的伦理问题（偏见、公平性、隐私）
- 培养批判性思维
- 强调负责任使用AI

在回答时平衡这两个方面，帮助学生成为负责任的、自主的学习者。'''
    }
    
    messages_with_prompt = [system_prompt] + messages
    
    return call_qwen_api(messages_with_prompt)

def call_original_llm(messages, student_id):
    """
    Group 4: 原始LLM（对照组）
    不添加任何特殊的系统提示词
    """
    return call_qwen_api(messages)

def call_qwen_api(messages):
    """调用通义千问API"""
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
    
    response = requests.post(
        API_BASE_URL, 
        headers=headers, 
        json=api_data, 
        timeout=30
    )
    response.raise_for_status()
    
    return response.json()

def route_llm_call(llm_type, messages, student_id):
    """根据组类型路由到对应的LLM调用函数"""
    llm_handlers = {
        'srl': call_srl_llm,
        'ai_ethics': call_ai_ethics_llm,
        'srl_and_ethics': call_srl_and_ethics_llm,
        'original': call_original_llm
    }
    
    handler = llm_handlers.get(llm_type, call_original_llm)
    return handler(messages, student_id)

# ================== 聊天接口 ==================

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
        context = data.get('context', [])
        session_id = data.get('session_id')
        student_id = data.get('student_id', 'default')
        llm_type = data.get('llm_type', 'original')  # 从前端获取LLM类型
        
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
                'messages': [],
                'llm_type': llm_type
            }
        
        session = chat_sessions.get(session_id, {
            'id': session_id,
            'student_id': student_id,
            'title': user_message[:30] + '...' if len(user_message) > 30 else user_message,
            'created_at': datetime.now().isoformat(),
            'messages': [],
            'llm_type': llm_type
        })
        chat_sessions[session_id] = session
        
        # 添加用户消息到会话
        session['messages'].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
        
        # 构建对话消息
        messages = []
        
        if context:
            recent_context = context[-20:] if len(context) > 20 else context
            messages.extend(recent_context)
        else:
            api_messages = [{'role': msg['role'], 'content': msg['content']} 
                           for msg in session['messages'] if msg['role'] in ['user', 'assistant']]
            messages.extend(api_messages[-20:])
        
        # 确保最后一条是用户消息
        if not messages or messages[-1]['role'] != 'user':
            messages.append({'role': 'user', 'content': user_message})
        
        logger.info(f"Calling LLM for student {student_id}, type: {llm_type}")
        
        # 根据学生组别调用对应的LLM
        result = route_llm_call(llm_type, messages, student_id)
        
        # 解析响应
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
        
        logger.info(f"Successfully generated AI response for {llm_type}")
        
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

# ================== 会话管理 ==================

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """获取会话列表"""
    try:
        student_id = request.args.get('student_id', 'default')
        
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
        llm_type = data.get('llm_type', 'original')
        
        session_id = str(uuid.uuid4())
        chat_sessions[session_id] = {
            'id': session_id,
            'student_id': student_id,
            'title': '新对话',
            'created_at': datetime.now().isoformat(),
            'messages': [],
            'llm_type': llm_type
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
        'available_endpoints': ['/', '/login', '/chat', '/health', '/api/sessions', '/api/login']
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
    logger.info(f"Student groups loaded: {len(STUDENTS_CONFIG.get('groups', {}))}")
    
    app.run(debug=debug, port=port, host='0.0.0.0')