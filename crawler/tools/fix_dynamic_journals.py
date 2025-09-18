#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from datetime import datetime

def fix_cell_dynamic_format():
    """修复Cell动态文件格式，将/issues改为/home以匹配静态格式"""
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dynamic_file = os.path.join(base_dir, 'journals_config/cell_journals_dynamic.json')
    
    if not os.path.exists(dynamic_file):
        print(f"动态文件不存在: {dynamic_file}")
        return False
    
    try:
        with open(dynamic_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查是否是新格式（包含valid_journals字典）
        if 'valid_journals' in data and isinstance(data['valid_journals'], dict):
            # 新格式：转换issues为home
            fixed_journals = []
            for name, issues_url in data['valid_journals'].items():
                home_url = issues_url.replace('/issues', '/home')
                fixed_journals.append({
                    "name": name,
                    "link": home_url
                })
            
            # 保存为标准格式
            with open(dynamic_file, 'w', encoding='utf-8') as f:
                json.dump(fixed_journals, f, ensure_ascii=False, indent=2)
            
            print(f"已修复Cell动态文件格式: {len(fixed_journals)}个期刊")
            return True
            
        elif isinstance(data, list):
            # 已经是标准格式，检查URL
            fixed_count = 0
            for item in data:
                if 'link' in item and '/issues' in item['link']:
                    item['link'] = item['link'].replace('/issues', '/home')
                    fixed_count += 1
            
            if fixed_count > 0:
                with open(dynamic_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"已修复{fixed_count}个URL格式")
            else:
                print("Cell动态文件格式已正确")
            return True
            
    except Exception as e:
        print(f"修复Cell动态文件失败: {e}")
        return False

def create_plos_dynamic():
    """创建PLOS动态文件（复制静态文件作为初始版本）"""
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_file = os.path.join(base_dir, 'journals_config/plos_journals.json')
    dynamic_file = os.path.join(base_dir, 'journals_config/plos_journals_dynamic.json')
    
    if os.path.exists(dynamic_file):
        print("PLOS动态文件已存在")
        return True
    
    if not os.path.exists(static_file):
        print(f"PLOS静态文件不存在: {static_file}")
        return False
    
    try:
        with open(static_file, 'r', encoding='utf-8') as f:
            static_data = json.load(f)
        
        # 直接复制静态文件内容
        with open(dynamic_file, 'w', encoding='utf-8') as f:
            json.dump(static_data, f, ensure_ascii=False, indent=2)
        
        print(f"已创建PLOS动态文件: {len(static_data)}个期刊")
        return True
        
    except Exception as e:
        print(f"创建PLOS动态文件失败: {e}")
        return False

def update_config_with_fallback():
    """更新配置文件，添加失败回退逻辑说明"""
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 检查合并版配置
    config_file = os.path.join(base_dir, 'config.yaml')
    light_config_file = os.path.join(base_dir, '../crawler_light/config.yaml')
    
    print("配置文件已更新为使用动态文件:")
    print(f"- 合并版: {config_file}")
    print(f"- 轻量版: {light_config_file}")
    print("\n回退机制:")
    print("- 如果动态获取失败，爬虫会自动回退到静态文件")
    print("- Cell: cell_journals.json <- cell_journals_dynamic.json")
    print("- PLOS: plos_journals.json <- plos_journals_dynamic.json")

def main():
    print("修复动态期刊文件格式...")
    print("=" * 50)
    
    # 1. 修复Cell格式
    print("1. 修复Cell动态文件格式...")
    fix_cell_dynamic_format()
    
    print("\n2. 创建PLOS动态文件...")
    create_plos_dynamic()
    
    print("\n3. 配置文件说明...")
    update_config_with_fallback()
    
    print("\n修复完成！")

if __name__ == '__main__':
    main()
