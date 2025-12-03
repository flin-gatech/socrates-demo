import os
import json
from datetime import datetime, timezone
import logging
import requests

logger = logging.getLogger(__name__)

class RedisDB:
    """Upstash Redis REST API 数据管理 - 修复版"""
    
    def __init__(self):
        self.rest_url = os.environ.get('UPSTASH_REDIS_REST_URL')
        self.rest_token = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
        
        self.available = False
        
        try:
            if not self.rest_url or not self.rest_token:
                logger.warning("Upstash Redis credentials not found. Running without Redis.")
                return
            
            # 测试连接
            response = self._execute_command(['PING'])
            if response and response.get('result') == 'PONG':
                logger.info("✅ Successfully connected to Upstash Redis (REST API)")
                self.available = True
            else:
                logger.warning("⚠️ Redis connection test failed")
                
        except Exception as e:
            logger.warning(f"⚠️ Redis connection error: {e}. Continuing without Redis.")
            self.available = False
    
    def _execute_command(self, command):
        """执行 Redis REST API 命令"""
        if not self.available and not (self.rest_url and self.rest_token):
            return None
        
        try:
            headers = {
                'Authorization': f'Bearer {self.rest_token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                self.rest_url,
                headers=headers,
                json=command,
                timeout=10  # 增加超时时间
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Redis command failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.warning(f"Redis command error: {e}")
            return None
    
    def _set(self, key, value, ex=None):
        """设置键值"""
        if ex:
            command = ['SET', key, value, 'EX', str(ex)]
        else:
            command = ['SET', key, value]
        
        result = self._execute_command(command)
        return result is not None
    
    def _get(self, key):
        """获取键值"""
        result = self._execute_command(['GET', key])
        return result.get('result') if result else None
    
    def _delete(self, key):
        """删除键"""
        result = self._execute_command(['DEL', key])
        return result is not None
    
    def _keys(self, pattern):
        """获取匹配的键列表"""
        result = self._execute_command(['KEYS', pattern])
        if result and 'result' in result:
            return result.get('result', []) or []
        return []
    
    def _scan(self, cursor=0, match=None, count=100):
        """使用 SCAN 命令迭代键（比 KEYS 更安全）"""
        command = ['SCAN', str(cursor)]
        if match:
            command.extend(['MATCH', match])
        if count:
            command.extend(['COUNT', str(count)])
        
        result = self._execute_command(command)
        if result and 'result' in result:
            # SCAN 返回 [next_cursor, [keys...]]
            scan_result = result['result']
            if isinstance(scan_result, list) and len(scan_result) == 2:
                return int(scan_result[0]), scan_result[1] or []
        return 0, []
    
    def _sadd(self, key, *members):
        """添加到集合"""
        command = ['SADD', key] + list(members)
        result = self._execute_command(command)
        return result is not None
    
    def _smembers(self, key):
        """获取集合所有成员"""
        result = self._execute_command(['SMEMBERS', key])
        if result and 'result' in result:
            return result.get('result', []) or []
        return []
    
    def _srem(self, key, *members):
        """从集合中移除成员"""
        command = ['SREM', key] + list(members)
        result = self._execute_command(command)
        return result is not None
    
    def _hset(self, key, mapping):
        """设置哈希表"""
        command = ['HSET', key]
        for k, v in mapping.items():
            command.extend([k, str(v)])
        
        result = self._execute_command(command)
        return result is not None
    
    def _hgetall(self, key):
        """获取哈希表所有字段"""
        result = self._execute_command(['HGETALL', key])
        if not result or 'result' not in result:
            return {}
        
        # HGETALL 返回 [k1, v1, k2, v2, ...] 格式
        items = result['result']
        if not items:
            return {}
        
        # 转换为字典
        return {items[i]: items[i+1] for i in range(0, len(items), 2)}
    
    def _expire(self, key, seconds):
        """设置键过期时间"""
        result = self._execute_command(['EXPIRE', key, str(seconds)])
        return result is not None

    # ============ 学生数据操作 ============
    
    def save_student(self, student_id, student_data):
        """保存学生信息"""
        if not self.available:
            logger.debug("Redis unavailable, skipping save_student")
            return True
        
        try:
            key = f"student:{student_id}"
            return self._set(key, json.dumps(student_data), ex=86400*365)
        except Exception as e:
            logger.warning(f"Error saving student: {e}")
            return False
    
    def get_student(self, student_id):
        """获取学生信息"""
        if not self.available:
            return None
        
        try:
            key = f"student:{student_id}"
            data = self._get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Error getting student: {e}")
            return None
    
    def update_student_login(self, student_id):
        """更新学生登录信息"""
        if not self.available:
            return None
        
        try:
            student = self.get_student(student_id)
            if student:
                student['login_count'] = student.get('login_count', 0) + 1
                student['last_login_at'] = datetime.now(timezone.utc).isoformat()
                self.save_student(student_id, student)
            return student
        except Exception as e:
            logger.warning(f"Error updating student login: {e}")
            return None

    # ============ 人格测试数据操作 ============
    
    def save_personality(self, student_id, personality_data):
        """保存学生人格测试结果"""
        if not self.available:
            logger.debug("Redis unavailable, skipping save_personality")
            return True
        
        try:
            key = f"personality:{student_id}"
            return self._set(key, json.dumps(personality_data), ex=86400*365)  # 保存1年
        except Exception as e:
            logger.warning(f"Error saving personality: {e}")
            return False
    
    def get_personality(self, student_id):
        """获取学生人格测试结果"""
        if not self.available:
            return None
        
        try:
            key = f"personality:{student_id}"
            data = self._get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Error getting personality: {e}")
            return None
    
    def has_personality_data(self, student_id):
        """检查学生是否已完成人格测试"""
        if not self.available:
            return False
        
        try:
            key = f"personality:{student_id}"
            data = self._get(key)
            return data is not None
        except Exception as e:
            logger.warning(f"Error checking personality: {e}")
            return False
    
    def get_all_personality_data(self):
        """获取所有学生人格测试数据"""
        if not self.available:
            return []
        
        try:
            keys = self._keys("personality:*")
            personality_list = []
            for key in keys:
                data = self._get(key)
                if data:
                    try:
                        personality_list.append(json.loads(data))
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in key {key}")
            return personality_list
        except Exception as e:
            logger.warning(f"Error getting all personality data: {e}")
            return []

    # ============ 对话数据操作 ============
    
    def create_conversation(self, conv_id, student_id, group_info, llm_type, title):
        """创建新对话 - 同时维护学生对话索引"""
        if not self.available:
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
                'created_at': datetime.now(timezone.utc).isoformat(),
                'message_count': 0,
                'messages': []
            }
            key = f"conversation:{conv_id}"
            success = self._set(key, json.dumps(conv_data), ex=86400*30)
            
            # 🔑 维护学生对话索引
            if success:
                index_key = f"student_conversations:{student_id}"
                self._sadd(index_key, conv_id)
                self._expire(index_key, 86400*30)
                logger.info(f"Created conversation {conv_id} for student {student_id}")
            
            return success
        except Exception as e:
            logger.warning(f"Error creating conversation: {e}")
            return False
    
    def get_conversation(self, conv_id):
        """获取对话"""
        if not self.available:
            return None
        
        try:
            key = f"conversation:{conv_id}"
            data = self._get(key)
            if data:
                return json.loads(data)
            else:
                logger.debug(f"Conversation {conv_id} not found")
                return None
        except Exception as e:
            logger.warning(f"Error getting conversation: {e}")
            return None
    
    def add_message_to_conversation(self, conv_id, role, content, word_count):
        """添加消息到对话"""
        if not self.available:
            logger.debug("Redis unavailable, skipping add_message_to_conversation")
            return True
        
        try:
            conv = self.get_conversation(conv_id)
            if not conv:
                logger.warning(f"Conversation {conv_id} not found when adding message")
                return False
            
            message = {
                'role': role,
                'content': content,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'word_count': word_count
            }
            
            conv['messages'].append(message)
            conv['message_count'] = len(conv['messages'])
            
            key = f"conversation:{conv_id}"
            return self._set(key, json.dumps(conv), ex=86400*30)
        except Exception as e:
            logger.warning(f"Error adding message to conversation: {e}")
            return False
    
    def get_student_conversations(self, student_id):
        """🔑 获取特定学生的所有对话 - 使用索引"""
        if not self.available:
            logger.debug("Redis unavailable, returning empty list")
            return []
        
        try:
            # 方法1: 使用学生对话索引（更快）
            index_key = f"student_conversations:{student_id}"
            conv_ids = self._smembers(index_key)
            
            logger.info(f"Found {len(conv_ids)} conversation IDs for student {student_id}")
            
            conversations = []
            for conv_id in conv_ids:
                conv = self.get_conversation(conv_id)
                if conv:
                    conversations.append(conv)
                else:
                    # 对话已过期，从索引中移除
                    self._srem(index_key, conv_id)
            
            # 如果索引为空，尝试使用 KEYS 作为备选方案
            if not conversations:
                logger.info(f"Index empty, trying KEYS fallback for student {student_id}")
                conversations = self._get_student_conversations_fallback(student_id)
            
            # 按创建时间倒序排列
            conversations.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
            logger.info(f"Returning {len(conversations)} conversations for student {student_id}")
            return conversations
            
        except Exception as e:
            logger.error(f"Error getting student conversations: {e}")
            return []
    
    def _get_student_conversations_fallback(self, student_id):
        """使用 KEYS 作为备选方案获取学生对话"""
        try:
            keys = self._keys("conversation:*")
            logger.info(f"KEYS fallback found {len(keys)} total conversation keys")
            
            conversations = []
            index_key = f"student_conversations:{student_id}"
            
            for key in keys:
                data = self._get(key)
                if data:
                    try:
                        conv = json.loads(data)
                        if conv.get('student_id') == student_id:
                            conversations.append(conv)
                            # 重建索引
                            self._sadd(index_key, conv['conversation_id'])
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in key {key}")
            
            if conversations:
                self._expire(index_key, 86400*30)
                
            return conversations
        except Exception as e:
            logger.error(f"KEYS fallback error: {e}")
            return []
    
    def delete_conversation(self, conv_id):
        """删除对话 - 同时更新索引"""
        if not self.available:
            return False
        
        try:
            # 先获取对话以找到 student_id
            conv = self.get_conversation(conv_id)
            if conv:
                student_id = conv.get('student_id')
                if student_id:
                    # 从索引中移除
                    index_key = f"student_conversations:{student_id}"
                    self._srem(index_key, conv_id)
            
            # 删除对话
            key = f"conversation:{conv_id}"
            return self._delete(key)
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            return False

    # ============ 统计数据操作 ============
    
    def add_to_student_stats(self, student_id, messages_count, duration_seconds):
        """更新学生统计"""
        if not self.available:
            logger.debug("Redis unavailable, skipping add_to_student_stats")
            return True
        
        try:
            key = f"stats:{student_id}"
            
            stats = self._hgetall(key)
            if not stats:
                stats = {
                    'total_messages': '0',
                    'total_duration': '0.0',
                    'total_conversations': '0'
                }
            
            stats['total_messages'] = str(int(stats.get('total_messages', 0)) + messages_count)
            stats['total_duration'] = str(float(stats.get('total_duration', 0)) + duration_seconds)
            stats['total_conversations'] = str(int(stats.get('total_conversations', 0)) + 1)
            
            self._hset(key, stats)
            self._expire(key, 86400*365)
            return True
        except Exception as e:
            logger.warning(f"Error updating student stats: {e}")
            return False
    
    # ============ 批量导出操作 ============
    
    def get_all_conversations(self):
        """获取所有对话"""
        if not self.available:
            return []
        
        try:
            keys = self._keys("conversation:*")
            logger.info(f"get_all_conversations: found {len(keys)} keys")
            
            conversations = []
            for key in keys:
                data = self._get(key)
                if data:
                    try:
                        conversations.append(json.loads(data))
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in key {key}")
            
            return conversations
        except Exception as e:
            logger.warning(f"Error getting all conversations: {e}")
            return []
    
    def get_all_students(self):
        """获取所有学生"""
        if not self.available:
            return []
        
        try:
            keys = self._keys("student:*")
            students = []
            for key in keys:
                data = self._get(key)
                if data:
                    students.append(json.loads(data))
            return students
        except Exception as e:
            logger.warning(f"Error getting all students: {e}")
            return []
    
    def get_all_messages(self):
        """获取所有消息(展平)"""
        if not self.available:
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
        if not self.available:
            return []
        
        try:
            stats_keys = self._keys("stats:*")
            statistics = []
            
            for key in stats_keys:
                try:
                    student_id = key.split(':')[1]
                    student_data = self.get_student(student_id)
                    stats_data = self._hgetall(key)
                    
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