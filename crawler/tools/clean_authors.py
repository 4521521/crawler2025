#!/usr/bin/env python3
"""
清理数据库中Science期刊的作者信息
移除ORCID链接、无关文本等杂乱信息
"""

import re
import logging
import sys
import os

# 添加父目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import UnifiedDB

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_author_text(authors_text):
    """
    清理作者文本，移除杂乱信息
    
    Args:
        authors_text: 原始作者文本
        
    Returns:
        str: 清理后的作者文本
    """
    if not authors_text:
        return authors_text
    
    # 移除ORCID链接
    cleaned = re.sub(r'https?://orcid\.org/[0-9\-X]+', '', authors_text)
    
    # 移除常见无关文本
    cleaned = re.sub(r'Authors?\s*Info\s*&?\s*Affiliations?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'View\s*ORCID\s*Profile', '', cleaned, flags=re.IGNORECASE)
    
    # 清理多余的分号和空格
    cleaned = re.sub(r';\s*;+', ';', cleaned)
    cleaned = re.sub(r'^\s*;\s*|\s*;\s*$', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # 清理开头和结尾的空白
    cleaned = cleaned.strip()
    
    return cleaned

def clean_science_authors():
    """清理Science期刊的作者信息"""
    db = UnifiedDB('science')
    
    try:
        # 查询所有Science期刊的记录
        query = "SELECT id, title, authors FROM science WHERE authors IS NOT NULL AND authors != ''"
        db.cursor.execute(query)
        records = db.cursor.fetchall()
        
        logger.info(f"找到 {len(records)} 条Science记录需要清理作者信息")
        
        updated_count = 0
        
        for record_id, title, original_authors in records:
            # 清理作者信息
            cleaned_authors = clean_author_text(original_authors)
            
            # 只有当清理后的文本与原文本不同时才更新
            if cleaned_authors != original_authors:
                update_query = "UPDATE science SET authors = %s WHERE id = %s"
                db.cursor.execute(update_query, (cleaned_authors, record_id))
                updated_count += 1
                
                logger.info(f"更新记录 {record_id}: {title[:50]}...")
                logger.info(f"  原作者: {original_authors[:100]}...")
                logger.info(f"  新作者: {cleaned_authors[:100]}...")
                logger.info("---")
        
        # 提交更改
        db.connection.commit()
        logger.info(f"成功更新了 {updated_count} 条记录的作者信息")
        
    except Exception as e:
        logger.error(f"清理作者信息时出错: {e}")
        db.connection.rollback()
    finally:
        db.close()

def clean_all_journals_authors():
    """清理所有期刊的作者信息"""
    journals = ['science', 'nature', 'cell', 'plos']
    
    for journal in journals:
        logger.info(f"开始清理 {journal.upper()} 期刊的作者信息...")
        try:
            db = UnifiedDB(journal)
            
            # 查询该期刊的记录
            query = f"SELECT id, title, authors FROM {journal} WHERE authors IS NOT NULL AND authors != ''"
            db.cursor.execute(query)
            records = db.cursor.fetchall()
            
            logger.info(f"找到 {len(records)} 条{journal.upper()}记录需要清理作者信息")
            
            updated_count = 0
            
            for record_id, title, original_authors in records:
                # 清理作者信息
                cleaned_authors = clean_author_text(original_authors)
                
                # 只有当清理后的文本与原文本不同时才更新
                if cleaned_authors != original_authors:
                    update_query = f"UPDATE {journal} SET authors = %s WHERE id = %s"
                    db.cursor.execute(update_query, (cleaned_authors, record_id))
                    updated_count += 1
                    
                    if updated_count <= 3:  # 只显示前3个例子避免日志过多
                        logger.info(f"更新{journal.upper()}记录 {record_id}: {title[:50]}...")
                        logger.info(f"  原作者: {original_authors[:80]}...")
                        logger.info(f"  新作者: {cleaned_authors[:80]}...")
                        logger.info("---")
            
            # 提交更改
            db.connection.commit()
            logger.info(f"{journal.upper()}: 成功更新了 {updated_count} 条记录的作者信息")
            
        except Exception as e:
            logger.error(f"清理{journal.upper()}作者信息时出错: {e}")
            if 'db' in locals():
                db.connection.rollback()
        finally:
            if 'db' in locals():
                db.close()
        
        logger.info(f"{journal.upper()} 清理完成\n")

if __name__ == "__main__":
    print("作者信息清理工具")
    print("1. 仅清理Science期刊")
    print("2. 清理所有期刊 (Science, Nature, Cell, PLOS)")
    
    choice = input("请选择 (1/2): ").strip()
    
    if choice == "1":
        clean_science_authors()
    elif choice == "2":
        clean_all_journals_authors()
    else:
        print("无效选择")
