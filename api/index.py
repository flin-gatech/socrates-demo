from flask import Flask, render_template, request, jsonify
import requests
import json
import os
import logging

# 根据你的文件结构调整路径
app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API configuration - 使用你原来的API KEY
API_KEY = os.environ.get('QWEN_API_KEY', 'sk-9ec24e8e7f6544b19d5326518007ba9e')
API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# Enhanced Socrates persona with conversation structure awareness
SOCRATES_SYSTEM_PROMPT = """You are Socrates, the ancient Greek philosopher. You embody wisdom, humility, and the art of questioning.

CORE PRINCIPLES:
- "I know that I know nothing" - approach with genuine curiosity
- Guide others to discover truth through their own reasoning  
- Be warm, encouraging, and patient
- Question assumptions gently but persistently

CRITICAL: KEEP RESPONSES CONCISE AND FOCUSED
- Maximum 2-3 sentences per response
- Ask ONLY ONE question at a time
- Let them answer before introducing new concepts
- Avoid cognitive overload with multiple simultaneous questions

CONVERSATION STRUCTURE AWARENESS:
You will receive metadata about the conversation:
- Round number (1-7)
- Current phase (exploration/examination/deepening/synthesis)
- Whether this should be the final round

PHASE-SPECIFIC BEHAVIOR:

**EXPLORATION PHASE (Rounds 1-2):**
- Ask ONE clarifying question: "What do you mean by...?" OR "Can you give me an example?"
- Be encouraging with brief responses: "That's interesting."
- Focus on understanding their definition, not challenging yet

**EXAMINATION PHASE (Rounds 3-4):**
- Introduce ONE contradiction or complication at a time
- Ask: "But what about...?" OR "If that's true, then...?"
- Reference only ONE previous point they made
- Maintain supportive tone while challenging

**DEEPENING PHASE (Round 5):**
- Ask about ONE broader implication: "What does this suggest about...?"
- Push for deeper reflection with a single, focused question
- Connect to ONE larger philosophical theme

**SYNTHESIS PHASE (Rounds 6-7):**
- Summarize briefly: "So we began with X and now see Y..."
- Ask ONE final question for future contemplation
- Acknowledge complexity without claiming to solve it

RESPONSE GUIDELINES:
- Keep responses to 1-2 sentences maximum
- Ask only 1 question per response - never multiple questions
- Use simple, direct language
- Build on their specific words and examples
- Show curiosity, not lecturing

ENDING GRACEFULLY:
When it's the final round:
- Brief recognition of their journey (1 sentence)
- One profound question to ponder (1 sentence)
- Encourage continued inquiry (1 sentence)

Example of GOOD responses:
- "What exactly do you mean by 'true friendship'?"
- "But if friendship requires trust, what about when friends disagree?"
- "So friendship might be more complex than we first thought?"

Example of BAD responses (too many questions):
- "What qualities come to mind? Is it trust, shared joy, or support? And how do you distinguish companions from true friends?"

Remember: One focused question leads to deeper insight than many scattered ones."""

def get_phase_specific_guidance(phase, round_num, is_final=False):
    """Generate phase-specific guidance for Socrates"""
    
    if is_final:
        return """
This is the concluding round of our dialogue. Focus on:
- Summarizing the intellectual journey we've taken
- Acknowledging what has been discovered or clarified
- Recognizing the complexity we've uncovered
- Leaving them with a profound question to contemplate
- Expressing appreciation for their willingness to examine these ideas
End with the spirit of: "Perhaps what we've discovered is that the question is more complex than we first thought, and in recognizing this complexity, we have gained true wisdom."
"""
    
    guidance = {
        'exploration': f"""
ROUND {round_num} - EXPLORATION PHASE:
- Focus on understanding their perspective deeply
- Ask clarifying questions about their terms and concepts
- Be encouraging and show genuine interest
- Don't challenge yet - just explore and understand
- Help them articulate their views more clearly
""",
        'examination': f"""
ROUND {round_num} - EXAMINATION PHASE:
- Now introduce gentle challenges and contradictions
- Reference what they said in earlier rounds
- Use counter-examples or alternative scenarios
- Ask: "But what about..." or "If that's true, then..."
- Maintain respect while probing assumptions
""",
        'deepening': f"""
ROUND {round_num} - DEEPENING PHASE:
- Push for broader implications and deeper reflection
- Connect their insights to larger philosophical themes
- Ask about the consequences of their reasoning
- Help them see new dimensions of the question
- Guide them to recognize the complexity involved
""",
        'synthesis': f"""
ROUND {round_num} - SYNTHESIS PHASE:
- Begin drawing together the threads of conversation
- Reference the journey from early rounds to now
- Highlight evolution in their thinking
- Prepare for a thoughtful conclusion
- Show how the inquiry has deepened understanding
"""
    }
    
    return guidance.get(phase, "")

@app.route('/')
def index():
    """主页路由 - 渲染聊天界面"""
    try:
        return render_template('chat.html')
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return f"Template error: {str(e)}", 500

@app.route('/health')
def health_check():
    """健康检查端点"""
    return jsonify({
        'status': 'healthy',
        'api_configured': bool(API_KEY),
        'template_folder': app.template_folder,
        'static_folder': app.static_folder
    })

@app.route('/chat', methods=['POST'])
def chat():
    """处理聊天消息的主要端点"""
    try:
        # 验证请求数据
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
        metadata = data.get('metadata', {})  # 轮次、阶段等信息
        
        # 输入验证
        if not user_message:
            return jsonify({
                'error': 'Please enter your question',
                'success': False
            }), 400
        
        if len(user_message) > 1000:
            return jsonify({
                'error': 'Message too long. Please keep it under 1000 characters.',
                'success': False
            }), 400
        
        # 检查API密钥
        if not API_KEY:
            return jsonify({
                'error': 'API configuration error. Please set QWEN_API_KEY environment variable.',
                'success': False
            }), 500
        
        # 提取元数据
        current_round = metadata.get('round', 1)
        current_phase = metadata.get('phase', 'exploration') 
        should_end = metadata.get('shouldEnd', False)
        
        logger.info(f"Processing message: Round {current_round}, Phase: {current_phase}, Should end: {should_end}")
        
        # 构建对话消息
        messages = [
            {'role': 'system', 'content': SOCRATES_SYSTEM_PROMPT},
            {'role': 'system', 'content': get_phase_specific_guidance(current_phase, current_round, should_end)}
        ]
        
        # 添加对话历史（最近的上下文）
        if context:
            messages.extend(context)
        
        # 添加当前用户消息
        messages.append({'role': 'user', 'content': user_message})
        
        # 准备API请求
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json',
            'User-Agent': 'SocratesChat/2.0'
        }
        
        api_data = {
            'model': 'qwen-plus',
            'messages': messages,
            'temperature': 0.7,
            'max_tokens': 500,  # 保持回复简洁
            'top_p': 0.9
        }
        
        logger.info(f"Sending {len(messages)} messages to Qwen API")
        
        # 调用通义千问API
        response = requests.post(
            API_BASE_URL, 
            headers=headers, 
            json=api_data, 
            timeout=30
        )
        response.raise_for_status()
        
        # 解析响应
        result = response.json()
        
        # 验证API响应结构
        if 'choices' not in result or not result['choices']:
            logger.error(f"Invalid API response structure: {result}")
            return jsonify({
                'error': 'Invalid response from AI service',
                'success': False
            }), 502
        
        socrates_reply = result['choices'][0]['message']['content'].strip()
        
        # 内容验证
        if not socrates_reply:
            return jsonify({
                'error': 'Empty response from AI service', 
                'success': False
            }), 502
        
        logger.info(f"Successfully generated response for round {current_round} ({len(socrates_reply)} chars)")
        
        return jsonify({
            'reply': socrates_reply,
            'success': True,
            'metadata': {
                'round': current_round,
                'phase': current_phase,
                'should_end': should_end
            }
        })
    
    except requests.exceptions.Timeout:
        logger.error("API request timeout")
        return jsonify({
            'error': 'The philosopher is taking time to contemplate. Please try again.',
            'success': False
        }), 504
    
    except requests.exceptions.ConnectionError:
        logger.error("Connection error to Qwen API")
        return jsonify({
            'error': 'Unable to connect to the AI service. Please check your connection.',
            'success': False
        }), 503
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error from Qwen API: {e}")
        status_code = e.response.status_code if e.response else 500
        
        if status_code == 401:
            return jsonify({
                'error': 'Authentication failed. Please check API key.',
                'success': False
            }), 401
        elif status_code == 429:
            return jsonify({
                'error': 'Too many requests. Please wait a moment.',
                'success': False  
            }), 429
        else:
            return jsonify({
                'error': f'AI service error: {status_code}',
                'success': False
            }), 502
    
    except json.JSONDecodeError:
        logger.error("Invalid JSON response from Qwen API")
        return jsonify({
            'error': 'Invalid response format from AI service',
            'success': False
        }), 502
    
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        return jsonify({
            'error': 'An unexpected error occurred. Please try again.',
            'success': False
        }), 500

@app.errorhandler(404)
def not_found(error):
    """404错误处理"""
    return jsonify({
        'error': 'Endpoint not found',
        'available_endpoints': ['/', '/chat', '/health']
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """500错误处理"""
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# For Vercel deployment
def handler(request):
    """Vercel serverless function handler"""
    return app(request)

# For local development
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting Socrates Chat on port {port}")
    logger.info(f"Template folder: {app.template_folder}")
    logger.info(f"Static folder: {app.static_folder}")
    logger.info(f"API Key configured: {bool(API_KEY)}")
    
    app.run(debug=debug, port=port, host='0.0.0.0')