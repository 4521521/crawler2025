#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一学术期刊爬虫系统 - 数据库模块
包含Nature、Science、Cell、PLOS四个期刊的数据库逻辑
"""

import pymysql
import logging
import yaml
import os
import pandas as pd
from datetime import datetime, date
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UnifiedDB:
    """统一数据库类，支持四个期刊"""
    
    def __init__(self, journal_type):
        """初始化数据库连接
        
        Args:
            journal_type: 期刊类型 (nature, science, cell, plos)
        """
        self.journal_type = journal_type.lower()
        self.connection = None
        self.cursor = None
        self.config = self._load_config()
        
        # 获取表名
        self.table_name = self.config[f'TABLE_NAME_{self.journal_type.upper()}']
        
        self._init_database()
    
    def _load_config(self):
        """加载配置文件"""
        try:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
            logger.info(f"尝试加载配置文件: {config_path}")
            
            with open(config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
            
            logger.info(f"成功加载配置文件: {config_path}")
            return config
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise
    
    def _init_database(self):
        """初始化数据库连接"""
        try:
            database_name = self.config['MYSQL_DATABASE']  # 统一数据库名
            
            # 先连接MySQL服务器（不指定数据库）
            temp_connection = pymysql.connect(
                host=str(self.config['MYSQL_HOST']),
                port=int(self.config['MYSQL_PORT']),
                user=str(self.config['MYSQL_USER']),
                password=str(self.config['MYSQL_PASSWORD']),
                charset='utf8mb4'
            )
            
            temp_cursor = temp_connection.cursor()
            
            # 创建数据库（如果不存在）
            temp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
            temp_cursor.close()
            temp_connection.close()
            
            # 连接到指定数据库
            self.connection = pymysql.connect(
                host=str(self.config['MYSQL_HOST']),
                port=int(self.config['MYSQL_PORT']),
                user=str(self.config['MYSQL_USER']),
                password=str(self.config['MYSQL_PASSWORD']),
                database=str(database_name),
                charset='utf8mb4',
                autocommit=True
            )
            
            self.cursor = self.connection.cursor()
            logger.info(f"{self.journal_type}数据库连接成功（数据库: {database_name}, 表: {self.table_name}）")
            
            # 创建表
            self._create_tables()
            
        except pymysql.Error as e:
            logger.error(f"{self.journal_type}数据库连接失败: {e}")
            self.connection = None
            raise
    
    def reconnect_if_needed(self):
        """如果连接已关闭，重新连接"""
        try:
            if not self.connection or not self.connection.open:
                logger.info(f"重新连接{self.journal_type}数据库")
                self._init_database()
            else:
                # 测试连接是否有效
                self.connection.ping(reconnect=True)
        except:
            logger.info(f"重新连接{self.journal_type}数据库")
            self._init_database()
        return True
    
    def close(self):
        """关闭数据库连接"""
        try:
            if self.connection and self.connection.open:
                if self.cursor:
                    self.cursor.close()
                self.connection.close()
                logger.info(f"已关闭{self.journal_type}数据库连接")
        except:
            pass
    
    def _create_tables(self):
        """创建必要的数据表"""
        try:
            # 只创建期刊专用表（表名为期刊名），使用pub_date字段，与Nature结构一致
            create_papers_table = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                abstract TEXT,
                doi VARCHAR(255),
                url VARCHAR(500),
                journal VARCHAR(255),
                pub_date DATE,
                authors TEXT,
                reason TEXT,
                type VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_doi (doi)
            )
            """
            
            self.cursor.execute(create_papers_table)
            
            # 检查并移除旧的URL唯一性约束（如果存在）
            self._remove_url_unique_constraint()
            
            logger.info(f"{self.journal_type}数据库表创建完成: {self.table_name}")
            
        except Exception as e:
            logger.error(f"创建数据表失败: {e}")
            raise
    
    def _remove_url_unique_constraint(self):
        """移除URL的唯一性约束（如果存在）"""
        try:
            # 检查约束是否存在
            check_constraint_query = f"""
            SELECT CONSTRAINT_NAME 
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
            WHERE TABLE_SCHEMA = %s 
            AND TABLE_NAME = %s 
            AND CONSTRAINT_NAME = 'unique_url'
            """
            
            self.cursor.execute(check_constraint_query, (self.config['MYSQL_DATABASE'], self.table_name))
            result = self.cursor.fetchone()
            
            if result:
                # 如果约束存在，删除它
                drop_constraint_query = f"ALTER TABLE {self.table_name} DROP INDEX unique_url"
                self.cursor.execute(drop_constraint_query)
                logger.info(f"{self.journal_type}表已移除URL唯一性约束")
            
        except Exception as e:
            # 如果约束不存在或其他错误，忽略
            logger.debug(f"移除URL约束时出现错误（可能约束不存在）: {e}")
    
    def save_paper(self, paper: Dict[str, Any], journal_name: str) -> bool:
        """保存论文到数据库（统一保存到papers表）
        
        Args:
            paper: 论文数据字典
            journal_name: 期刊名称
            
        Returns:
            bool: 是否保存成功
        """
        try:
            # 检查连接
            self.reconnect_if_needed()
            
            # 处理空字符串，转换为None（数据库中为NULL）
            def clean_empty_string(value):
                if isinstance(value, str) and value.strip() == '':
                    return None
                return value
            
            # 处理DOI为空的情况，使用URL作为备选
            doi_value = clean_empty_string(paper.get('doi', ''))
            url_value = clean_empty_string(paper.get('url', ''))
            
            # 如果DOI为空但URL不为空，使用URL作为DOI的备选值
            if not doi_value and url_value:
                doi_value = url_value
                logger.debug(f"DOI为空，使用URL作为DOI: {url_value}")
            
            insert_query = f"""
            INSERT IGNORE INTO {self.table_name} (title, abstract, doi, pub_date, journal, url, authors, reason, type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            values = (
                paper.get('title', '') or '未知标题',  # 标题不能为空
                clean_empty_string(paper.get('abstract', '')),
                doi_value,  # 使用处理后的DOI值（可能是URL）
                paper.get('date', datetime.now().date()),
                journal_name,
                url_value,  # 保持原始URL
                clean_empty_string(paper.get('authors', '')),
                clean_empty_string(paper.get('reason', '')),  # reason字段确实被保存
                paper.get('type', 'incremental')
            )
            
            self.cursor.execute(insert_query, values)
            
            return self.cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"保存论文失败: {e}")
            return False
    
    
    def get_last_update_time(self, journal_name: str = None) -> Optional[datetime]:
        """获取最后更新时间
        
        Args:
            journal_name: 子刊名称，如果提供则按子刊获取最新时间
            
        Returns:
            Optional[datetime]: 最后更新时间
        """
        try:
            # 检查连接
            self.reconnect_if_needed()
            
            # 统一使用papers表，不再区分recent表
            if journal_name:
                # 按子刊获取最新时间
                query = f"SELECT MAX(pub_date) FROM {self.table_name} WHERE journal = %s"
                self.cursor.execute(query, (journal_name,))
            else:
                # 获取整个期刊组的最新时间
                query = f"SELECT MAX(pub_date) FROM {self.table_name}"
                self.cursor.execute(query)
            
            result = self.cursor.fetchone()
            
            if result and result[0]:
                return result[0]
            else:
                # 如果没有数据，返回当前时间的前一周
                from datetime import timedelta
                default_date = datetime.now() - timedelta(weeks=1)
                if journal_name:
                    logger.info(f"{self.journal_type}子刊{journal_name}数据库表为空，使用前一周作为起始日期: {default_date.strftime('%Y-%m-%d')}")
                else:
                    logger.info(f"{self.journal_type}数据库表为空，使用前一周作为起始日期: {default_date.strftime('%Y-%m-%d')}")
                return default_date
                
        except Exception as e:
            logger.error(f"获取最后更新时间失败: {e}")
            # 如果出错，也返回当前时间的前一周
            from datetime import timedelta
            return datetime.now() - timedelta(weeks=1)
    
    def get_paper_count(self) -> int:
        """获取论文总数"""
        try:
            query = f"SELECT COUNT(*) FROM {self.table_name}"
            self.cursor.execute(query)
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取论文数量失败: {e}")
            return 0
    
    def get_recent_paper_count(self) -> int:
        """获取最近论文数量"""
        try:
            query = f"SELECT COUNT(*) FROM {self.table_name}_recent"
            self.cursor.execute(query)
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取最近论文数量失败: {e}")
            return 0
    
    def check_paper_exists(self, doi: str) -> bool:
        """检查论文是否已存在
        
        Args:
            doi: 论文DOI
            
        Returns:
            bool: 是否存在
        """
        try:
            # 检查连接
            self.reconnect_if_needed()
            
            query = f"SELECT COUNT(*) FROM {self.table_name} WHERE doi = %s"
            self.cursor.execute(query, (doi,))
            result = self.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            logger.error(f"检查论文存在性失败: {e}")
            return False
    
    def get_journals_from_db(self):
        """从数据库获取期刊列表"""
        try:
            query = f"SELECT DISTINCT journal FROM {self.table_name} ORDER BY journal"
            self.cursor.execute(query)
            results = self.cursor.fetchall()
            return [row[0] for row in results]
        except Exception as e:
            logger.error(f"获取期刊列表失败: {e}")
            return []
    
    def export_to_csv(self, output_file: str, table: str = "papers", include_reason: bool = False):
        """导出数据到CSV文件
        
        Args:
            output_file: 输出文件路径
            table: 表名 (papers 或 recent)
            include_reason: 是否包含AI分析原因（仅用于CSV导出，不保存到数据库）
        """
        try:
            if pd is None:
                logger.error("pandas未安装，无法导出CSV")
                return
                
            # 根据table参数确定实际表名
            actual_table = self.table_name if table == "papers" else f"{self.table_name}_recent"
            
            query = f"SELECT * FROM {actual_table} ORDER BY pub_date DESC"
            df = pd.read_sql(query, self.connection)
            
            # 如果需要包含reason字段，从内存中的数据添加
            if include_reason and hasattr(self, '_recent_papers_with_reason'):
                # 创建reason列
                df['reason'] = ''
                for paper_data in self._recent_papers_with_reason:
                    mask = df['doi'] == paper_data.get('doi', '')
                    if mask.any():
                        df.loc[mask, 'reason'] = paper_data.get('reason', '')
            
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            logger.info(f"数据已导出到: {output_file}")
            
        except Exception as e:
            logger.error(f"导出CSV失败: {e}")
    
    def export_recent_ai_papers_with_reason(self, output_file: str, papers_with_reason: list):
        """导出最近的AI相关论文（包含分析原因）到CSV
        
        Args:
            output_file: 输出文件路径
            papers_with_reason: 包含reason字段的论文列表
        """
        try:
            if pd is None:
                logger.error("pandas未安装，无法导出CSV")
                return
            
            if not papers_with_reason:
                logger.warning("没有AI相关论文数据可导出")
                return
            
            # 直接从内存数据创建DataFrame
            df = pd.DataFrame(papers_with_reason)
            
            # 确保列的顺序
            columns_order = ['title', 'abstract', 'doi', 'date', 'journal', 'url', 'authors', 'type', 'reason']
            df = df.reindex(columns=[col for col in columns_order if col in df.columns])
            
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            logger.info(f"AI相关论文数据已导出到: {output_file} (包含{len(papers_with_reason)}篇)")
            
        except Exception as e:
            logger.error(f"导出AI论文CSV失败: {e}")
    
    def export_papers_after_date(self, start_date=None, end_date=None, output_format='csv', output_file=None):
        """
        导出指定日期范围内的所有论文 (模仿paperagent (2)的逻辑)

        参数:
            start_date (datetime or str): 起始日期，可以是 datetime 对象或 'YYYY-MM-DD' 格式字符串
            end_date (datetime or str): 终止日期，可选，格式同上
            output_format (str): 输出格式，支持 'json', 'csv', 'markdown', 'xlsx'
            output_file (str): 输出文件路径，如果为 None，则生成默认文件名

        返回:
            tuple: (bool, str) - (是否成功, 输出文件路径或错误信息)
        """
        try:
            where_clause = ""
            params = []
            date_desc = ""

            # 处理起始日期
            if start_date:
                if isinstance(start_date, str):
                    try:
                        start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    except ValueError:
                        return False, f"起始日期格式无效: {start_date}，请使用 YYYY-MM-DD 格式"
                date_desc += f"from_{start_date.strftime('%Y-%m-%d')}"
                where_clause += "pub_date >= %s"
                params.append(start_date.strftime("%Y-%m-%d"))

            # 处理终止日期
            if end_date:
                if isinstance(end_date, str):
                    try:
                        end_date = datetime.strptime(end_date, "%Y-%m-%d")
                    except ValueError:
                        return False, f"终止日期格式无效: {end_date}，请使用 YYYY-MM-DD 格式"
                date_desc += f"_to_{end_date.strftime('%Y-%m-%d')}"
                if where_clause:
                    where_clause += " AND "
                where_clause += "pub_date <= %s"
                params.append(end_date.strftime("%Y-%m-%d"))

            if where_clause:
                where_clause = "WHERE " + where_clause
            else:
                date_desc = "all"

            logger.info(f"SQL查询: {where_clause}")
            logger.info(f"参数: {params}")
            
            # 默认文件名和目录
            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                suffix = output_format if output_format != 'markdown' else 'md'
                
                # 根据格式选择目录
                if output_format.lower() == 'csv':
                    output_dir = "exports/csv"
                elif output_format.lower() == 'xlsx':
                    output_dir = "exports/excel"
                elif output_format.lower() == 'markdown':
                    output_dir = "exports/markdown"
                elif output_format.lower() == 'json':
                    output_dir = "exports/json"
                else:
                    output_dir = "exports/reports"
                
                # 确保目录存在
                os.makedirs(output_dir, exist_ok=True)
                
            # 包含期刊名称的文件名
            journal_prefix = self.journal_type.lower()
            # 先执行查询获取实际的日期范围
            temp_query = f"""
            SELECT MIN(pub_date) as min_date, MAX(pub_date) as max_date
            FROM {self.table_name}
            {where_clause}
            """
            self.cursor.execute(temp_query, params)
            date_range_result = self.cursor.fetchone()
            
            if date_range_result and date_range_result[0] and date_range_result[1]:
                actual_min_date = date_range_result[0].strftime('%Y-%m-%d') if date_range_result[0] else '未知'
                actual_max_date = date_range_result[1].strftime('%Y-%m-%d') if date_range_result[1] else '未知'
                actual_date_desc = f"{actual_min_date}_{actual_max_date}"
                output_file = f"{output_dir}/{journal_prefix}_papers_{actual_date_desc}.{suffix}"
                logger.info(f"实际文献日期范围: {actual_min_date} 至 {actual_max_date}")
            else:
                # 如果没有数据，使用原来的查询日期范围
                output_file = f"{output_dir}/{journal_prefix}_papers_{date_desc}.{suffix}"
                logger.info(f"未找到数据，使用查询日期范围: {date_desc}")

            # 查询数据
            query = f"""
            SELECT id, title, abstract, doi, url, journal, pub_date, authors, type,
                   created_at, updated_at
            FROM {self.table_name}
            {where_clause}
            ORDER BY pub_date DESC, id DESC
            """
            
            # 执行查询
            if where_clause:
                self.cursor.execute(query, tuple(params))
            else:
                self.cursor.execute(query)
            
            papers = []
            columns = [desc[0] for desc in self.cursor.description]
            for row in self.cursor.fetchall():
                paper = dict(zip(columns, row))
                papers.append(paper)
            
            row_count = len(papers)

            if row_count == 0:
                return False, "未找到符合条件的论文"

            logger.info(f"找到 {row_count} 篇论文，时间范围: {start_date} - {end_date}")

            # 处理日期格式，使其可序列化
            for paper in papers:
                for key in ['pub_date', 'created_at', 'updated_at']:
                    if paper[key] and isinstance(paper[key], (datetime, date)):
                        paper[key] = paper[key].isoformat()

            # 根据输出格式导出数据
            if output_format.lower() == 'json':
                import json
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(papers, f, ensure_ascii=False, indent=2)

                logger.info(f"成功导出 {row_count} 篇论文到 JSON 文件: {output_file}")
                return True, output_file

            elif output_format.lower() == 'csv':
                import csv
                with open(output_file, 'w', encoding='utf-8', newline='') as f:
                    if papers:
                        fieldnames = papers[0].keys()
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(papers)

                logger.info(f"成功导出 {row_count} 篇论文到 CSV 文件: {output_file}")
                return True, output_file
                
            elif output_format.lower() == 'xlsx':
                try:
                    import pandas as pd
                except ImportError:
                    return False, "pandas未安装，无法导出Excel文件"
                # 使用 pandas 导出为 Excel 文件
                df = pd.DataFrame(papers)
                df.to_excel(output_file, index=False)

                logger.info(f"成功导出 {row_count} 篇论文到 Excel 文件: {output_file}")
                return True, output_file

            elif output_format.lower() == 'markdown':
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"# 论文数据导出（{date_desc}）\n\n")
                    f.write(f"*导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
                    f.write(f"*共包含 {row_count} 篇论文*\n\n")
                    f.write("---\n\n")

                    journals = {}
                    for paper in papers:
                        journal = paper['journal']
                        journals.setdefault(journal, []).append(paper)

                    for journal, journal_papers in journals.items():
                        f.write(f"## {journal}\n\n")
                        for i, paper in enumerate(journal_papers, 1):
                            pub_date = "日期未知"
                            if paper['pub_date']:
                                pub_date = paper['pub_date'].split('T')[0] if 'T' in paper['pub_date'] else paper['pub_date']
                            f.write(f"### {i}. {paper['title']}\n\n")
                            f.write(f"**发布日期:** {pub_date}\n\n")
                            if paper['doi'] and paper['doi'] != "未找到 DOI":
                                f.write(f"**DOI:** [{paper['doi']}]({paper['url']})\n\n")
                            if paper['url']:
                                f.write(f"**链接:** [{paper['url']}]({paper['url']})\n\n")
                            f.write("**摘要:**\n\n")
                            abstract = paper['abstract'] or "无摘要"
                            for line in abstract.split('\n'):
                                if line.strip():
                                    f.write(f"> {line.strip()}\n")
                            f.write("\n---\n\n")
                        f.write("\n\n")
                logger.info(f"成功导出 {row_count} 篇论文到 Markdown 文件: {output_file}")
                return True, output_file

            else:
                return False, f"不支持的输出格式: {output_format}，支持的格式有: json, csv, markdown, xlsx"

        except Exception as e:
            logger.error(f"导出论文时出错: {e}")
            return False, f"导出论文时出错: {str(e)}"
    
    def close(self):
        """关闭数据库连接"""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
            logger.info(f"{self.journal_type}数据库连接已关闭")
        except Exception as e:
            logger.error(f"关闭数据库连接失败: {e}")

# 为了向后兼容，保留各期刊的别名
class NatureDB(UnifiedDB):
    def __init__(self):
        super().__init__('nature')

class ScienceDB(UnifiedDB):
    def __init__(self):
        super().__init__('science')

class CellDB(UnifiedDB):
    def __init__(self):
        super().__init__('cell')

class PLOSDB(UnifiedDB):
    def __init__(self):
        super().__init__('plos')

# 工厂函数
def create_db(journal_type: str) -> UnifiedDB:
    """创建指定期刊的数据库实例
    
    Args:
        journal_type: 期刊类型 (nature, science, cell, plos)
        
    Returns:
        UnifiedDB: 数据库实例
    """
    return UnifiedDB(journal_type)
