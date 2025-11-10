import os
import redis
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class RedisDB:
    """Upstash Redis 数据管理"""
    
    def __init__(self):
        # 连接到Upstash Redis
        redis_url = os.environ.get('UPSTASH_REDIS_REST_URL')
        redis_token = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
        
        self.available = False
        self.client = None
        
        try:
            if not redis_url or not redis_token:
                logger.warning("Upstash Redis credentials not found, trying local Redis")
                try:
                    self.client = redis.Redis(host='localhost', port=6379, decode_responses=True, socket_connect_timeout=2)
                    self.client.ping()
                    logger.info("✅ Connected to local Redis")
                    self.available = True
                except Exception as e:
                    logger.warning(f"⚠️ Local Redis not available: {e}. Running without Redis.")
                    self.available = False
                    self.client = None
                    return
            else:
                # 使用Upstash Redis
                self.client = redis.Redis(
                    url=redis_url,
                    decode_responses=True,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                    connection_pool_kwargs={"socket_connect_timeout": 5, "retry_on_timeout": True}
                )
                self.client.ping()
                logger.info("✅ Successfully connected to Upstash Redis")
                self.available = True
        except Exception as e:
            logger.warning(f"⚠️ Redis connection error: {e}. Continuing without Redis.")
            self.available = False
            self.client = None

    # ============ 学生数据操作 ============
    
    def save_student(self, student_id, student_data):
        """保存学生信息"""
        if not self.available or not self.client:
            logger.debug("Redis unavailable, skipping save_student")
            return True
        
        try:
            key = f"student:{student_id}"
            return self.client.set(key, json.dumps(student_data), ex=86400*365)
        except Exception as e:
            logger.warning(f"Error saving student: {e}")
            return False
    
    def get_student(self, student_id):
        """获取学生信息"""
        if not self.available or not self.client:
            return None
        
        try:
            key = f"student:{student_id}"
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Error getting student: {e}")
            return None
    
    def update_student_login(self, student_id):
        """更新学生登录信息"""
        if not self.available or not self.client:
            return None
        
        try:
            student = self.get_student(student_id)
            if student:
                student['login_count'] = student.get('login_count', 0) + 1
                student['last_login_at'] = datetime.utcnow().isoformat()
                self.save_student(student_id, student)
            return student
        except Exception as e:
            logger.warning(f"Error updating student login: {e}")
            return None

    # ============ 对话数据操作 ============
    
    def create_conversation(self, conv_id, student_id, group_info, llm_type, title):
        """创建新对话"""
        if not self.available or not self.client:
            logger.debug("Redis unavailable, skipping create_conversation")
            return True
        
        try:
            conv_data = {
                'conversation_id': conv_id,
                'student_id': student_id,
                'group_id': group_info.get('group_id') if group_info else 'unknown',
                'group_name': group_info.get('group_name') if group_info else 'unknown',
                'llm_type': llm_type,
                'title': title,
                'created_at': datetime.utcnow().isoformat(),
                'message_count': 0,
                'messages': []
            }
            key = f"conversation:{conv_id}"
            return self.client.set(key, json.dumps(conv_data), ex=86400*30)
        except Exception as e:
            logger.warning(f"Error creating conversation: {e}")
            return False
    
    def get_conversation(self, conv_id):
        """获取对话"""
        if not self.available or not self.client:
            return None
        
        try:
            key = f"conversation:{conv_id}"
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Error getting conversation: {e}")
            return None
    
    def add_message_to_conversation(self, conv_id, role, content, word_count):
        """添加消息到对话"""
        if not self.available or not self.client:
            logger.debug("Redis unavailable, skipping add_message_to_conversation")
            return True
        
        try:
            conv = self.get_conversation(conv_id)
            if not conv:
                return False
            
            message = {
                'role': role,
                'content': content,
                'timestamp': datetime.utcnow().isoformat(),
                'word_count': word_count
            }
            
            conv['messages'].append(message)
            conv['message_count'] = len(conv['messages'])
            
            key = f"conversation:{conv_id}"
            return self.client.set(key, json.dumps(conv), ex=86400*30)
        except Exception as e:
            logger.warning(f"Error adding message to conversation: {e}")
            return False

    # ============ 统计数据操作 ============
    
    def add_to_student_stats(self, student_id, messages_count, duration_seconds):
        """更新学生统计"""
        if not self.available or not self.client:
            logger.debug("Redis unavailable, skipping add_to_student_stats")
            return True
        
        try:
            key = f"stats:{student_id}"
            
            stats = self.client.hgetall(key)
            if not stats:
                stats = {
                    'total_messages': 0,
                    'total_duration': 0.0,
                    'total_conversations': 0
                }
            
            stats['total_messages'] = int(stats.get('total_messages', 0)) + messages_count
            stats['total_duration'] = float(stats.get('total_duration', 0)) + duration_seconds
            stats['total_conversations'] = int(stats.get('total_conversations', 0)) + 1
            
            self.client.hset(key, mapping=stats)
            self.client.expire(key, 86400*365)
            return True
        except Exception as e:
            logger.warning(f"Error updating student stats: {e}")
            return False
    
    # ============ 批量导出操作 ============
    
    def get_all_conversations(self):
        """获取所有对话"""
        if not self.available or not self.client:
            return []
        
        try:
            keys = self.client.keys("conversation:*")
            conversations = []
            for key in keys:
                data = self.client.get(key)
                if data:
                    conversations.append(json.loads(data))
            return conversations
        except Exception as e:
            logger.warning(f"Error getting all conversations: {e}")
            return []
    
    def get_all_students(self):
        """获取所有学生"""
        if not self.available or not self.client:
            return []
        
        try:
            keys = self.client.keys("student:*")
            students = []
            for key in keys:
                data = self.client.get(key)
                if data:
                    students.append(json.loads(data))
            return students
        except Exception as e:
            logger.warning(f"Error getting all students: {e}")
            return []
    
    def get_all_messages(self):
        """获取所有消息（展平）"""
        if not self.available or not self.client:
            return []
        
        try:
            conversations = self.get_all_conversations()
            all_messages = []
            
            for conv in conversations:
                for msg in conv.get('messages', []):
                    msg_record = {
                        'conversation_id': conv['conversation_id'],
                        'student_id': conv['student_id'],
                        'llm_type': conv['llm_type'],
                        'role': msg['role'],
                        'content': msg['content'],
                        'timestamp': msg['timestamp'],
                        'word_count': msg['word_count']
                    }
                    all_messages.append(msg_record)
            
            return all_messages
        except Exception as e:
            logger.warning(f"Error getting all messages: {e}")
            return []
    
    def export_statistics(self):
        """导出统计数据"""
        if not self.available or not self.client:
            return []
        
        try:
            stats_keys = self.client.keys("stats:*")
            statistics = []
            
            for key in stats_keys:
                try:
                    student_id = key.split(':')[1]
                    student_data = self.get_student(student_id)
                    stats_data = self.client.hgetall(key)
                    
                    record = {
                        'student_id': student_id,
                        'group_id': student_data.get('group_id') if student_data else '',
                        'group_name': student_data.get('group_name') if student_data else '',
                        'llm_type': student_data.get('llm_type') if student_data else '',
                        'login_count': student_data.get('login_count', 0) if student_data else 0,
                        'first_login_at': student_data.get('first_login_at') if student_data else '',
                        'last_login_at': student_data.get('last_login_at') if student_data else '',
                        'total_conversations': stats_data.get('total_conversations', 0),
                        'total_messages': stats_data.get('total_messages', 0),
                        'total_duration': stats_data.get('total_duration', 0)
                    }
                    statistics.append(record)
                except Exception as e:
                    logger.warning(f"Error processing stats for key {key}: {e}")
                    continue
            
            return statistics
        except Exception as e:
            logger.warning(f"Error exporting statistics: {e}")
            return []

# 单例
_redis_instance = None

def get_redis_db():
    """获取Redis实例"""
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = RedisDB()
    return _redis_instance