from flask import Flask, render_template, request, jsonify, redirect, url_for
import requests
import json
import os
import logging
from datetime import datetime
import uuid

# 处理导入问题
try:
    from .redis_db import get_redis_db
except ImportError:
    from redis_db import get_redis_db

redis_db = get_redis_db()

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
        config_path = os.path.join(os.path.dirname(__file__), '..', 'students_config.json')
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
        
        group_info = get_student_group(student_id)
        
        if not group_info:
            return jsonify({
                'success': False,
                'error': '学号不存在，请检查后重试'
            }), 404
        
        # 保存或更新学生信息
        existing_student = redis_db.get_student(student_id)
        
        if existing_student:
            redis_db.update_student_login(student_id)
        else:
            student_data = {
                'student_id': student_id,
                'group_id': group_info['group_id'],
                'group_name': group_info['group_name'],
                'llm_type': group_info['llm_type'],
                'login_count': 1,
                'first_login_at': datetime.utcnow().isoformat(),
                'last_login_at': datetime.utcnow().isoformat()
            }
            redis_db.save_student(student_id, student_data)
        
        logger.info(f"Student {student_id} logged in")
        
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
    Group 2: AI Ethics辅助的LLM - 两步工作流
    
    工作流程:
    1. 先将学生问题发送给 AI Ethics Instruction Agent,获取基于AI伦理的指导
    2. 将 AI Ethics 指导 + 学生原始问题一起发送给最终 LLM 生成回答
    """
    
    # 提取学生的最新问题
    user_message = messages[-1]['content'] if messages and messages[-1]['role'] == 'user' else ''
    
    if not user_message:
        return call_qwen_api(messages)
    
    # ========== 步骤1: 调用 AI Ethics Instruction Agent ==========
    ethics_agent_prompt = {
        'role': 'system',
        'content': '''你是一个AI伦理教育专家。

请分析学生的问题,并提供简短的AI伦理指导建议(2-3句话),帮助学生:
- 识别AI技术中的潜在偏见和公平性问题
- 理解数据隐私和安全的重要性
- 培养对AI使用的批判性思维
- 认识AI的社会影响和责任

只需要返回AI伦理指导建议,不要直接回答学生的问题。'''
    }
    
    ethics_agent_messages = [
        ethics_agent_prompt,
        {'role': 'user', 'content': f'学生问题: {user_message}\n\n请给出AI伦理指导建议:'}
    ]
    
    logger.info(f"Step 1: Calling AI Ethics Instruction Agent for student {student_id}")
    
    try:
        ethics_response = call_qwen_api(ethics_agent_messages)
        ethics_instruction = ethics_response['choices'][0]['message']['content'].strip()
        logger.info(f"AI Ethics Instruction generated: {ethics_instruction[:100]}...")
    except Exception as e:
        logger.error(f"Error calling AI Ethics agent: {e}")
        # 如果 AI Ethics agent 失败,使用默认指导
        ethics_instruction = "在使用AI技术时,请思考可能存在的偏见和伦理问题,并负责任地使用。"
    
    # ========== 步骤2: 调用最终 LLM 回答学生问题 ==========
    final_system_prompt = {
        'role': 'system',
        'content': f'''你是一个注重AI伦理教育的AI助手。

**AI伦理指导建议:**
{ethics_instruction}

请在回答学生问题时:
1. 自然地融入上述AI伦理指导建议
2. 提供准确、有帮助的答案
3. 适时讨论AI技术的伦理问题(偏见、公平性、隐私等)
4. 鼓励学生批判性地思考AI的使用
5. 强调负责任地使用AI工具的重要性
6. 帮助学生理解AI的局限性和潜在风险

记住:你的回答应该既解决学生的具体问题,又培养他们对AI伦理的意识和批判性思维。'''
    }
    
    # 构建最终的消息列表
    # 包含对话历史(不含最后一条用户消息) + 新的系统提示 + 最后一条用户消息
    final_messages = [final_system_prompt]
    
    # 添加历史对话(排除最后一条,因为我们要重新添加)
    if len(messages) > 1:
        for msg in messages[:-1]:
            final_messages.append({
                'role': msg['role'],
                'content': msg['content']
            })
    
    # 添加当前用户问题
    final_messages.append({
        'role': 'user',
        'content': user_message
    })
    
    logger.info(f"Step 2: Calling final LLM with AI Ethics guidance for student {student_id}")
    
    return call_qwen_api(final_messages)

def call_srl_and_ethics_llm(messages, student_id):
    """
    Group 3: SRL + AI Ethics 双重辅助的LLM - 三步级联工作流
    
    工作流程:
    1. 先将学生问题发送给 AI Ethics Instruction Agent,获取AI伦理指导
    2. 将 AI Ethics 指导发送给 SRL Instruction Agent,进行SRL调整
    3. 将最终整合的指导 + 学生原始问题一起发送给最终 LLM
    """
    
    # 提取学生的最新问题
    user_message = messages[-1]['content'] if messages and messages[-1]['role'] == 'user' else ''
    
    if not user_message:
        return call_qwen_api(messages)
    
    # ========== 步骤1: 调用 AI Ethics Instruction Agent ==========
    ethics_agent_prompt = {
        'role': 'system',
        'content': '''你是一个AI伦理教育专家。

请分析学生的问题,并提供简短的AI伦理指导建议(2-3句话),帮助学生:
- 识别AI技术中的潜在偏见和公平性问题
- 理解数据隐私和安全的重要性
- 培养对AI使用的批判性思维
- 认识AI的社会影响和责任

只需要返回AI伦理指导建议,不要直接回答学生的问题。'''
    }
    
    ethics_agent_messages = [
        ethics_agent_prompt,
        {'role': 'user', 'content': f'学生问题: {user_message}\n\n请给出AI伦理指导建议:'}
    ]
    
    logger.info(f"Step 1: Calling AI Ethics Instruction Agent for student {student_id}")
    
    try:
        ethics_response = call_qwen_api(ethics_agent_messages)
        ethics_instruction = ethics_response['choices'][0]['message']['content'].strip()
        logger.info(f"AI Ethics Instruction generated: {ethics_instruction[:100]}...")
    except Exception as e:
        logger.error(f"Error calling AI Ethics agent: {e}")
        # 如果失败,使用默认指导
        ethics_instruction = "在使用AI技术时,请思考可能存在的偏见和伦理问题,并负责任地使用。"
    
    # ========== 步骤2: 调用 SRL Instruction Agent 对伦理指导进行调整 ==========
    srl_agent_prompt = {
        'role': 'system',
        'content': '''你是一个自我调节学习(SRL)指导专家。

你将收到一个AI伦理方面的指导建议。请基于SRL原则对这个指导进行调整和扩展,使其:
- 鼓励学生设定学习目标
- 引导学生监控和评估自己的理解
- 促进学生的元认知思考
- 帮助学生反思学习策略

请保留原有的AI伦理内容,但用SRL的视角进行重新表述和扩展(3-4句话)。'''
    }
    
    srl_agent_messages = [
        srl_agent_prompt,
        {'role': 'user', 'content': f'''学生的原始问题: {user_message}

AI伦理指导建议:
{ethics_instruction}

请基于SRL原则调整和扩展这个指导:'''}
    ]
    
    logger.info(f"Step 2: Calling SRL Instruction Agent to adjust ethics guidance for student {student_id}")
    
    try:
        srl_response = call_qwen_api(srl_agent_messages)
        final_instruction = srl_response['choices'][0]['message']['content'].strip()
        logger.info(f"Final SRL-adjusted instruction generated: {final_instruction[:100]}...")
    except Exception as e:
        logger.error(f"Error calling SRL agent: {e}")
        # 如果SRL调整失败,使用原始的伦理指导
        final_instruction = ethics_instruction + " 请在学习过程中监控自己的理解,并反思你的学习策略。"
    
    # ========== 步骤3: 调用最终 LLM 回答学生问题 ==========
    final_system_prompt = {
        'role': 'system',
        'content': f'''你是一个同时支持自我调节学习(SRL)和AI伦理教育的AI助手。

**整合指导建议(SRL + AI Ethics):**
{final_instruction}

请在回答学生问题时:
1. 自然地融入上述整合指导建议
2. 提供准确、有帮助的答案
3. **SRL方面**: 鼓励学生设定学习目标、监控进度、反思策略、提供元认知支持
4. **AI伦理方面**: 讨论AI的伦理问题(偏见、公平性、隐私)、培养批判性思维、强调负责任使用
5. 平衡这两个方面,帮助学生成为负责任的、自主的学习者

记住:你的回答应该既解决学生的具体问题,又同时促进他们的自我调节学习能力和AI伦理意识。'''
    }
    
    # 构建最终的消息列表
    final_messages = [final_system_prompt]
    
    # 添加历史对话(排除最后一条,因为我们要重新添加)
    if len(messages) > 1:
        for msg in messages[:-1]:
            final_messages.append({
                'role': msg['role'],
                'content': msg['content']
            })
    
    # 添加当前用户问题
    final_messages.append({
        'role': 'user',
        'content': user_message
    })
    
    logger.info(f"Step 3: Calling final LLM with integrated SRL+Ethics guidance for student {student_id}")
    
    return call_qwen_api(final_messages)

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
        if not request.is_json:
            return jsonify({
                'error': 'Content-Type must be application/json',
                'success': False
            }), 400
        
        data = request.get_json()
        user_message = data.get('message', '').strip()
        session_id = data.get('session_id')
        student_id = data.get('student_id', 'default')
        llm_type = data.get('llm_type', 'original')
        context = data.get('context', [])
        
        if not user_message or len(user_message) > 2000:
            return jsonify({
                'error': 'Invalid message',
                'success': False
            }), 400
        
        if not API_KEY:
            return jsonify({
                'error': 'API configuration error',
                'success': False
            }), 500
        
        # 创建新对话
        if not session_id:
            session_id = str(uuid.uuid4())
            group_info = get_student_group(student_id) or {'group_id': 'unknown', 'group_name': 'unknown'}
            
            redis_db.create_conversation(
                session_id, 
                student_id, 
                group_info, 
                llm_type,
                user_message[:30] + ('...' if len(user_message) > 30 else '')
            )
            
            logger.info(f"Conversation {session_id} created")
        
        # 获取当前对话
        conversation = redis_db.get_conversation(session_id)
        
        # 构建消息列表
        messages = []
        if conversation and conversation.get('messages'):
            # 使用之前的对话历史（最多20条）
            for msg in conversation['messages'][-20:]:
                messages.append({
                    'role': msg['role'],
                    'content': msg['content']
                })
        
        # 确保最后一条是用户消息
        if not messages or messages[-1]['role'] != 'user':
            messages.append({'role': 'user', 'content': user_message})
        
        logger.info(f"Calling LLM for student {student_id}, type: {llm_type}")
        
        # 调用LLM
        result = route_llm_call(llm_type, messages, student_id)
        
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
        
        # 保存消息到Redis
        user_word_count = len(user_message.split())
        ai_word_count = len(ai_reply.split())
        
        redis_db.add_message_to_conversation(session_id, 'user', user_message, user_word_count)
        redis_db.add_message_to_conversation(session_id, 'assistant', ai_reply, ai_word_count)
        
        # 更新学生统计
        redis_db.add_to_student_stats(student_id, 2, 0)  # 2条消息
        
        logger.info(f"Successfully generated AI response for {llm_type}")
        
        return jsonify({
            'reply': ai_reply,
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({
            'error': 'An unexpected error occurred.',
            'success': False
        }), 500
# ========== 数据导出接口 ==========

@app.route('/api/export/conversations', methods=['GET'])
def export_conversations():
    """导出所有对话为CSV"""
    try:
        import pandas as pd
        from io import BytesIO
        from flask import send_file
        
        conversations = redis_db.get_all_conversations()
        
        data = []
        for conv in conversations:
            data.append({
                'conversation_id': conv['conversation_id'],
                'student_id': conv['student_id'],
                'group_id': conv['group_id'],
                'group_name': conv['group_name'],
                'llm_type': conv['llm_type'],
                'title': conv['title'],
                'created_at': conv['created_at'],
                'message_count': conv['message_count']
            })
        
        if not data:
            return jsonify({'error': 'No data to export'}), 404
        
        df = pd.DataFrame(data)
        
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'conversations_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/messages', methods=['GET'])
def export_messages():
    """导出所有消息为CSV"""
    try:
        import pandas as pd
        from io import BytesIO
        from flask import send_file
        
        messages = redis_db.get_all_messages()
        
        if not messages:
            return jsonify({'error': 'No data to export'}), 404
        
        df = pd.DataFrame(messages)
        
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'messages_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/statistics', methods=['GET'])
def export_statistics():
    """导出学生统计数据为CSV"""
    try:
        import pandas as pd
        from io import BytesIO
        from flask import send_file
        
        stats = redis_db.export_statistics()
        
        if not stats:
            return jsonify({'error': 'No data to export'}), 404
        
        df = pd.DataFrame(stats)
        
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'statistics_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({'error': str(e)}), 500

# ================== 会话管理 ==================

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """获取会话列表 - 从 Redis 获取"""
    try:
        student_id = request.args.get('student_id')
        
        if not student_id:
            return jsonify({'error': '缺少学生ID', 'success': False}), 400
        
        # 从 Redis 获取该学生的所有对话
        all_conversations = redis_db.get_all_conversations()
        
        # 筛选该学生的对话
        student_sessions = []
        for conv in all_conversations:
            if conv.get('student_id') == student_id:
                session_info = {
                    'id': conv['conversation_id'],
                    'title': conv.get('title', '无标题对话'),
                    'created_at': conv['created_at'],
                    'message_count': conv['message_count']
                }
                
                # 添加最后一条消息预览
                if conv.get('messages'):
                    last_msg = conv['messages'][-1]
                    session_info['last_message'] = last_msg['content'][:50] + ('...' if len(last_msg['content']) > 50 else '')
                else:
                    session_info['last_message'] = ''
                
                student_sessions.append(session_info)
        
        # 按创建时间倒序排列
        student_sessions.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            'sessions': student_sessions,
            'success': True
        })
        
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({'error': str(e), 'success': False}), 500


@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    """获取特定会话的详细信息 - 从 Redis 获取"""
    try:
        # 从 Redis 获取
        session = redis_db.get_conversation(session_id)
        
        if not session:
            return jsonify({
                'error': '会话不存在',
                'success': False
            }), 404
        
        return jsonify({
            'session': session,
            'success': True
        })
        
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        return jsonify({
            'error': str(e),
            'success': False
        }), 500


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """删除会话 - 从 Redis 删除"""
    try:
        if not redis_db.available:
            return jsonify({
                'error': 'Redis 不可用',
                'success': False
            }), 503
        
        # 先检查会话是否存在
        session = redis_db.get_conversation(session_id)
        if not session:
            return jsonify({
                'error': '会话不存在',
                'success': False
            }), 404
        
        # 从 Redis 删除
        key = f"conversation:{session_id}"
        success = redis_db._delete(key)
        
        if success:
            return jsonify({
                'message': '会话已删除',
                'success': True
            })
        else:
            return jsonify({
                'error': '删除失败',
                'success': False
            }), 500
            
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({
            'error': str(e),
            'success': False
        }), 500


@app.route('/api/sessions', methods=['POST'])
def create_session():
    """创建新会话 - 这个函数现在主要由 /chat 接口自动调用"""
    try:
        data = request.json or {}
        student_id = data.get('student_id')
        llm_type = data.get('llm_type', 'original')
        title = data.get('title', '新对话')
        
        if not student_id:
            return jsonify({
                'error': '缺少学生ID',
                'success': False
            }), 400
        
        session_id = str(uuid.uuid4())
        group_info = get_student_group(student_id) or {
            'group_id': 'unknown',
            'group_name': 'unknown'
        }
        
        # 在 Redis 中创建新会话
        redis_db.create_conversation(
            session_id,
            student_id,
            group_info,
            llm_type,
            title
        )
        
        return jsonify({
            'session_id': session_id,
            'message': '新会话已创建',
            'success': True
        })
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

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