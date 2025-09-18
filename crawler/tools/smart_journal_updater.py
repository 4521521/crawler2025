# -*- coding: utf-8 -*-
"""
智能期刊更新器
- 保持筛选后的高质量期刊列表
- 只更新现有期刊的URL链接，不添加新期刊
- 支持模糊匹配期刊名称
"""

import json
import os
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class SmartJournalUpdater:
    """智能期刊更新器"""
    
    def __init__(self, base_dir=None):
        if base_dir is None:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self.base_dir = base_dir
        
        # 初始化时，确保dynamic文件包含筛选后的期刊列表
        self.initialize_dynamic_files()
    
    def similarity(self, a, b):
        """计算两个字符串的相似度"""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()
    
    def normalize_journal_name(self, name):
        """标准化期刊名称用于比较"""
        # 移除常见的变体
        name = name.lower().strip()
        # 处理常见的名称变化
        replacements = {
            'cancer cell': 'cancer cell',
            'cell stem cell': 'cell stem cell',
            'molecular cell': 'molecular cell',
            'developmental cell': 'developmental cell',
            'current biology': 'current biology',
            'cell metabolism': 'cell metabolism',
            'cell reports': 'cell reports',
            'plos one': 'plos one',
            'plos biology': 'plos biology',
            'plos medicine': 'plos medicine',
            'plos genetics': 'plos genetics',
            'plos computational biology': 'plos computational biology',
            'plos pathogens': 'plos pathogens'
        }
        
        for old, new in replacements.items():
            if old in name:
                return new
        
        return name
    
    def initialize_dynamic_files(self):
        """初始化dynamic文件，确保包含筛选后的期刊列表"""
        # 初始化Cell dynamic文件
        cell_new_file = os.path.join(self.base_dir, 'journals_new', 'cell_journals.json')
        cell_dynamic_file = os.path.join(self.base_dir, 'journals_config', 'cell_journals_dynamic.json')
        
        if os.path.exists(cell_new_file):
            if not os.path.exists(cell_dynamic_file):
                # dynamic文件不存在，复制筛选文件
                with open(cell_new_file, 'r', encoding='utf-8') as f:
                    cell_data = json.load(f)
                with open(cell_dynamic_file, 'w', encoding='utf-8') as f:
                    json.dump(cell_data, f, ensure_ascii=False, indent=2)
                logger.info(f"初始化Cell dynamic文件: {len(cell_data)} 个期刊")
            else:
                # dynamic文件存在，检查是否需要重新同步筛选列表
                with open(cell_new_file, 'r', encoding='utf-8') as f:
                    new_data = json.load(f)
                with open(cell_dynamic_file, 'r', encoding='utf-8') as f:
                    dynamic_data = json.load(f)
                
                # 如果期刊数量差异很大，可能需要重新同步
                if abs(len(new_data) - len(dynamic_data)) > 10:
                    with open(cell_dynamic_file, 'w', encoding='utf-8') as f:
                        json.dump(new_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"重新同步Cell dynamic文件: {len(new_data)} 个期刊")
        
        # 初始化PLOS dynamic文件
        plos_new_file = os.path.join(self.base_dir, 'journals_new', 'plos_journals.json')
        plos_dynamic_file = os.path.join(self.base_dir, 'journals_config', 'plos_journals_dynamic.json')
        
        if os.path.exists(plos_new_file):
            if not os.path.exists(plos_dynamic_file):
                # dynamic文件不存在，复制筛选文件
                with open(plos_new_file, 'r', encoding='utf-8') as f:
                    plos_data = json.load(f)
                with open(plos_dynamic_file, 'w', encoding='utf-8') as f:
                    json.dump(plos_data, f, ensure_ascii=False, indent=2)
                logger.info(f"初始化PLOS dynamic文件: {len(plos_data)} 个期刊")
            else:
                # dynamic文件存在，检查是否需要重新同步筛选列表
                with open(plos_new_file, 'r', encoding='utf-8') as f:
                    new_data = json.load(f)
                with open(plos_dynamic_file, 'r', encoding='utf-8') as f:
                    dynamic_data = json.load(f)
                
                # 如果期刊数量差异很大，可能需要重新同步
                if abs(len(new_data) - len(dynamic_data)) > 2 or len(dynamic_data) > 10:
                    with open(plos_dynamic_file, 'w', encoding='utf-8') as f:
                        json.dump(new_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"重新同步PLOS dynamic文件: {len(new_data)} 个期刊")
    
    def find_best_match(self, target_name, candidate_names):
        """在候选名称中找到最佳匹配"""
        target_norm = self.normalize_journal_name(target_name)
        best_match = None
        best_score = 0.0
        
        for candidate in candidate_names:
            candidate_norm = self.normalize_journal_name(candidate)
            score = self.similarity(target_norm, candidate_norm)
            
            # 如果是完全匹配或高度相似（>0.8），认为是匹配的
            if score > 0.8 and score > best_score:
                best_score = score
                best_match = candidate
        
        return best_match, best_score
    
    def update_cell_journals(self, dynamic_journals_data):
        """
        更新Cell期刊列表
        dynamic_journals_data: 从动态获取得到的期刊数据
        """
        # 读取筛选后的高质量期刊列表
        filtered_file = os.path.join(self.base_dir, 'journals_new', 'cell_journals.json')
        if not os.path.exists(filtered_file):
            logger.warning(f"筛选文件不存在: {filtered_file}")
            return False
        
        with open(filtered_file, 'r', encoding='utf-8') as f:
            filtered_journals = json.load(f)
        
        # 创建动态数据的名称到链接映射
        dynamic_name_to_link = {}
        for journal in dynamic_journals_data:
            if isinstance(journal, dict) and 'name' in journal and 'link' in journal:
                dynamic_name_to_link[journal['name']] = journal['link']
        
        # 更新筛选列表中的期刊链接
        updated_count = 0
        updated_journals = []
        
        for filtered_journal in filtered_journals:
            original_link = filtered_journal['link']
            updated_journal = filtered_journal.copy()
            
            # 尝试在动态数据中找到匹配的期刊
            best_match, score = self.find_best_match(
                filtered_journal['name'], 
                dynamic_name_to_link.keys()
            )
            
            if best_match and score > 0.8:
                new_link = dynamic_name_to_link[best_match]
                # 确保链接格式一致（使用/home结尾）
                if '/issues' in new_link:
                    new_link = new_link.replace('/issues', '/home')
                elif not new_link.endswith('/home') and not new_link.endswith('/home/'):
                    if new_link.endswith('/'):
                        new_link += 'home'
                    else:
                        new_link += '/home'
                
                updated_journal['link'] = new_link
                
                if original_link != new_link:
                    logger.info(f"更新: {filtered_journal['name']}")
                    updated_count += 1
            else:
                logger.debug(f"未找到匹配期刊: {filtered_journal['name']}")
            
            updated_journals.append(updated_journal)
        
        # 保存更新后的期刊列表到dynamic文件
        dynamic_output = os.path.join(self.base_dir, 'journals_config', 'cell_journals_dynamic.json')
        with open(dynamic_output, 'w', encoding='utf-8') as f:
            json.dump(updated_journals, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Cell期刊: 保持{len(updated_journals)}个筛选期刊，更新{updated_count}个链接")
        return True
    
    def update_plos_journals(self, dynamic_journals_data):
        """
        更新PLOS期刊列表
        dynamic_journals_data: 从动态获取得到的期刊数据
        """
        # 读取筛选后的高质量期刊列表
        filtered_file = os.path.join(self.base_dir, 'journals_new', 'plos_journals.json')
        if not os.path.exists(filtered_file):
            logger.warning(f"筛选文件不存在: {filtered_file}")
            return False
        
        with open(filtered_file, 'r', encoding='utf-8') as f:
            filtered_journals = json.load(f)
        
        # 创建动态数据的名称到链接映射
        dynamic_name_to_link = {}
        for journal in dynamic_journals_data:
            if isinstance(journal, dict) and 'name' in journal and 'link' in journal:
                dynamic_name_to_link[journal['name']] = journal['link']
        
        # 更新筛选列表中的期刊链接
        updated_count = 0
        updated_journals = []
        
        for filtered_journal in filtered_journals:
            original_link = filtered_journal['link']
            updated_journal = filtered_journal.copy()
            
            # 尝试在动态数据中找到匹配的期刊
            best_match, score = self.find_best_match(
                filtered_journal['name'], 
                dynamic_name_to_link.keys()
            )
            
            if best_match and score > 0.8:
                new_link = dynamic_name_to_link[best_match]
                # 确保链接格式一致
                if not new_link.endswith('/'):
                    new_link += '/'
                
                updated_journal['link'] = new_link
                
                if original_link != new_link:
                    logger.info(f"更新: {filtered_journal['name']}")
                    updated_count += 1
            else:
                logger.debug(f"未找到匹配期刊: {filtered_journal['name']}")
            
            updated_journals.append(updated_journal)
        
        # 保存更新后的期刊列表到dynamic文件
        dynamic_output = os.path.join(self.base_dir, 'journals_config', 'plos_journals_dynamic.json')
        with open(dynamic_output, 'w', encoding='utf-8') as f:
            json.dump(updated_journals, f, ensure_ascii=False, indent=2)
        
        logger.info(f"PLOS期刊: 保持{len(updated_journals)}个筛选期刊，更新{updated_count}个链接")
        return True

def main():
    """测试智能更新器"""
    updater = SmartJournalUpdater()
    
    # 测试Cell期刊更新
    print("测试Cell期刊智能更新...")
    try:
        # 读取当前的动态期刊数据进行测试
        current_dynamic = os.path.join(updater.base_dir, 'journals_config', 'cell_journals_dynamic.json')
        if os.path.exists(current_dynamic):
            with open(current_dynamic, 'r', encoding='utf-8') as f:
                test_data = json.load(f)
            result = updater.update_cell_journals(test_data)
            print(f"Cell更新结果: {result}")
        else:
            print("当前Cell动态文件不存在，跳过测试")
    except Exception as e:
        print(f"Cell测试失败: {e}")
    
    # 测试PLOS期刊更新
    print("\n测试PLOS期刊智能更新...")
    try:
        # 读取当前的动态期刊数据进行测试
        current_dynamic = os.path.join(updater.base_dir, 'journals_config', 'plos_journals_dynamic.json')
        if os.path.exists(current_dynamic):
            with open(current_dynamic, 'r', encoding='utf-8') as f:
                test_data = json.load(f)
            result = updater.update_plos_journals(test_data)
            print(f"PLOS更新结果: {result}")
        else:
            print("当前PLOS动态文件不存在，跳过测试")
    except Exception as e:
        print(f"PLOS测试失败: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
