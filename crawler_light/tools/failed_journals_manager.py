#!/usr/bin/env python3
"""
失败期刊管理器
处理爬取失败的期刊重试逻辑
"""

import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class FailedJournalsManager:
    """管理失败期刊的记录和重试"""
    
    def __init__(self, journal_type: str):
        """
        初始化失败期刊管理器
        
        Args:
            journal_type: 期刊类型 (nature, science, cell, plos)
        """
        self.journal_type = journal_type.lower()
        self.failed_file = f"journals_config/failed_{self.journal_type}_journals.json"
        
        # 确保journals_config目录存在
        os.makedirs("journals_config", exist_ok=True)
        
    def add_failed_journal(self, journal_name: str, url: str, reason: str):
        """
        添加失败期刊记录
        
        Args:
            journal_name: 期刊名称
            url: 期刊URL
            reason: 失败原因
        """
        failed_record = {
            'journal_name': journal_name,
            'url': url,
            'reason': reason,
            'failed_time': datetime.now().isoformat(),
            'retry_count': 0,
            'last_retry': None
        }
        
        # 读取现有失败记录
        failed_journals = self._load_failed_journals()
        
        # 检查是否已存在该期刊的失败记录
        existing_index = -1
        for i, record in enumerate(failed_journals):
            if record['journal_name'] == journal_name:
                existing_index = i
                break
        
        if existing_index >= 0:
            # 更新现有记录
            failed_journals[existing_index]['reason'] = reason
            failed_journals[existing_index]['failed_time'] = datetime.now().isoformat()
            failed_journals[existing_index]['retry_count'] += 1
        else:
            # 添加新记录
            failed_journals.append(failed_record)
        
        # 保存到文件
        self._save_failed_journals(failed_journals)
        logger.info(f"已记录失败期刊: {journal_name} - {reason}")
    
    def get_failed_journals(self) -> List[Dict[str, Any]]:
        """获取所有失败期刊列表"""
        return self._load_failed_journals()
    
    def remove_successful_journal(self, journal_name: str):
        """
        移除成功爬取的期刊记录
        
        Args:
            journal_name: 期刊名称
        """
        failed_journals = self._load_failed_journals()
        
        # 过滤掉成功的期刊
        updated_journals = [
            journal for journal in failed_journals 
            if journal['journal_name'] != journal_name
        ]
        
        if len(updated_journals) < len(failed_journals):
            self._save_failed_journals(updated_journals)
            logger.info(f"已从失败列表中移除成功期刊: {journal_name}")
    
    def update_retry_info(self, journal_name: str):
        """
        更新期刊重试信息
        
        Args:
            journal_name: 期刊名称
        """
        failed_journals = self._load_failed_journals()
        
        for record in failed_journals:
            if record['journal_name'] == journal_name:
                record['retry_count'] += 1
                record['last_retry'] = datetime.now().isoformat()
                break
        
        self._save_failed_journals(failed_journals)
    
    def clear_failed_journals(self):
        """清空失败期刊记录"""
        self._save_failed_journals([])
        logger.info(f"已清空{self.journal_type}失败期刊记录")
    
    def _load_failed_journals(self) -> List[Dict[str, Any]]:
        """从文件加载失败期刊列表"""
        try:
            if os.path.exists(self.failed_file):
                with open(self.failed_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"加载失败期刊文件失败: {e}")
        
        return []
    
    def _save_failed_journals(self, failed_journals: List[Dict[str, Any]]):
        """保存失败期刊列表到文件"""
        try:
            with open(self.failed_file, 'w', encoding='utf-8') as f:
                json.dump(failed_journals, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存失败期刊文件失败: {e}")
    
    def get_statistics(self) -> Dict[str, int]:
        """获取失败期刊统计信息"""
        failed_journals = self._load_failed_journals()
        
        total_failed = len(failed_journals)
        retry_counts = {}
        
        for journal in failed_journals:
            count = journal.get('retry_count', 0)
            retry_counts[count] = retry_counts.get(count, 0) + 1
        
        return {
            'total_failed': total_failed,
            'retry_distribution': retry_counts,
            'file_path': self.failed_file
        }
