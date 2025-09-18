#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from openai import OpenAI
import re
import yaml
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
# self.logger = logging.getLogger(__name__)

class PaperAgent:
    """
    论文智能分析代理，用于判断论文是否与AI相关
    """
    
    def __init__(self, logger=None,config_path=None):
        """初始化论文分析代理"""
        # 先设置logger
        self.logger = logger or logging.getLogger(__name__)
        # 加载配置
        if not config_path:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        self.config = self._load_config(config_path) 
        # 初始化OpenAI客户端
        base_url = self.config.get('OPENAI_BASE_URL')
        api_key = self.config.get('OPENAI_API_KEY') or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.logger.error("未找到OpenAI API密钥，请在配置文件中设置或设置环境变量")
            raise ValueError("未提供OpenAI API密钥")
            
        self.client = OpenAI(base_url=base_url,api_key=api_key)
        self.model = self.config.get('MAIN_LLM_MODEL')
        self.logger.info(f"PaperAgent初始化完成，使用模型: {self.model}")
        
    def _load_config(self, config_path):
        """从配置文件加载设置"""
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                return yaml.safe_load(file)
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            return {}

    def analyze_batch_papers_with_id(self, paper_list):
        """
        同时分析一批论文（将多篇一起打包送入大模型，带 ID）

        参数:
            paper_list (list[dict]): 每项必须有 'id', 'title', 'abstract'

        返回:
            list[dict]: 每篇论文的分析结果，包含原始 id
        """
        self.logger.info(f"Sending {len(paper_list)} papers in batch to LLM...")

        # 拼接 prompt
        prompt_parts = []
        for paper in paper_list:
            prompt_parts.append(f"""
    <item>
    <id>{paper['id']}</id>
    <title>{paper['title']}</title>
    <abstract>{paper['abstract']}</abstract>
    </item>
    """)

        batch_prompt = f"""
    You will be given a batch of papers. For each paper, analyze whether it is related to Artificial Intelligence (AI).

    For each <item>, return the result as:
    <result>
    <id>...</id>
    <judgment>Related / Not Related</judgment>
    <explanation>...</explanation>
    </result>

    The papers are as follows:
    {''.join(prompt_parts)}
    """

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful AI paper analyzer."},
                    {"role": "user", "content": batch_prompt}
                ],
                temperature=0.2,
                max_tokens=8192
            )

            answer = response.choices[0].message.content
            # 从返回中提取每条结果
            results = []
            pattern = re.compile(
                r"<result>\s*<id>(.*?)</id>\s*<judgment>(.*?)</judgment>\s*<explanation>(.*?)</explanation>\s*</result>",
                re.DOTALL
            )
            for match in pattern.finditer(answer):
                paper_id, judgment, explanation = match.groups()
                results.append({
                    "id": paper_id.strip(),
                    "is_ai_related": judgment.strip().lower() == "related",
                    "judgment": judgment.strip(),
                    "explanation": explanation.strip()
                })
            return results

        except Exception as e:
            self.logger.error(f"Batch analyze error: {e}")
            return []

    def batch_analyze_papers_in_batches_concurrent(self, paper_list, batch_size=5, max_workers=20):
        """
        支持批量分析多篇论文（并发 + 批量发送到大模型）

        参数:
            paper_list: 每项为 {'id', 'title', 'abstract'}
            batch_size: 每批喂多少篇给模型
            max_workers: 同时运行多少个批次

        返回:
            list[dict]: 每篇论文分析结果（带原始 id）
        """
        self.logger.info(f"共需分析 {len(paper_list)} 篇论文，按 batch_size={batch_size} 并发提交...")

        batches = [
            paper_list[i:i + batch_size]
            for i in range(0, len(paper_list), batch_size)
        ]

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {
                executor.submit(self.analyze_batch_papers_with_id, batch): batch
                for batch in batches
            }
            
            completed_batches = 0
            for future in as_completed(future_to_batch):
                try:
                    batch_result = future.result()
                    results.extend(batch_result)
                    completed_batches += 1
                    
                    # 简化输出：只显示批次结果统计
                    ai_count = sum(1 for r in batch_result if r.get('is_ai_related', False))
                    self.logger.debug(f"批次完成: {len(batch_result)} 篇，AI相关: {ai_count} 篇")
                    
                    # 批次间延迟，避免API限流 (除了最后一批)
                    if completed_batches < len(batches):
                        import time
                        import random
                        delay = random.uniform(1, 3)  # 1-3秒随机延迟
                        self.logger.debug(f"批次间延迟 {delay:.1f} 秒，避免API限流...")
                        time.sleep(delay)
                        
                except Exception as e:
                    self.logger.error(f"[批次分析] 某一批处理失败: {e}")
        return results

    def analyze_paper(self, title, abstract):
        """
        分析论文是否与AI相关
        
        参数:
            title (str): 论文标题
            abstract (str): 论文摘要
            
        返回:
            dict: 包含分析结果的字典，格式如下:
                {
                    'is_ai_related': bool, # 是否与AI相关
                    'judgment': str,       # "Related" 或 "Not Related"
                    'explanation': str,    # 详细解释
                    'thinking': str        # 思考过程
                }
        """
        self.logger.debug(f"分析论文: {title[:50]}...")
        
        # 构建英文提示
        prompt = f"""
Your task is to determine whether the given paper's title and abstract are related to Artificial Intelligence (AI). Please carefully read the following information and evaluate based on the provided criteria.

Paper Title:
<title>
{title}
</title>

Paper Abstract:
<abstract>
{abstract}
</abstract>

When determining if the paper is related to AI, consider the following criteria:
If the title or abstract mentions artificial intelligence (AI), machine learning, deep learning, neural networks, natural language processing, computer vision, or other AI-related terms, or if the described research methods or application scenarios are clearly related to AI technology, the paper should be considered related to AI.

Please follow these steps for your evaluation:
1. Carefully read the title and abstract.
2. Compare the content with the criteria above.
3. Consider the overall expression and potential connections.
4. Form a preliminary judgment.
5. Check again to ensure no important details are missed.

In the <thinking> tag, analyze the paper's content and consider whether it's related to AI. Then, in the <judgment> tag, provide your final judgment using "Related" or "Not Related". Finally, in the <explanation> tag, explain your reasoning in detail.

<thinking>
[Analyze the paper's title and abstract content here]
</thinking>

<judgment>
[Provide either "Related" or "Not Related" judgment here]
</judgment>

<explanation>
[Provide a detailed explanation justifying your judgment here]
</explanation>

Please ensure your judgment is objective and based on the provided criteria. If the content is ambiguous, please explain your thought process in the explanation.
"""
        
        try:
            # 调用OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional academic paper analyst specialized in determining whether papers are related to artificial intelligence."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,  # 较低的温度使输出更加确定
                max_tokens=8192,  # 设置最大token数
            )
            
            # 提取回答内容
            answer = response.choices[0].message.content
            # 移除详细API响应日志以简化输出
            
            # 使用正则表达式提取思考、判断和解释部分
            thinking_match = re.search(r'<thinking>(.*?)</thinking>', answer, re.DOTALL)
            judgment_match = re.search(r'<judgment>(.*?)</judgment>', answer, re.DOTALL)
            explanation_match = re.search(r'<explanation>(.*?)</explanation>', answer, re.DOTALL)
            
            thinking = thinking_match.group(1).strip() if thinking_match else "No thinking process provided"
            judgment = judgment_match.group(1).strip() if judgment_match else "Unable to determine"
            explanation = explanation_match.group(1).strip() if explanation_match else "No explanation provided"
            
            # 判断是否与AI有关
            is_ai_related = True if judgment.lower() == "related" else False
            
            result = {
                'is_ai_related': is_ai_related,
                'judgment': judgment,
                'explanation': explanation,
                'thinking': thinking
            }
            
            self.logger.debug(f"分析完成: {'AI相关' if is_ai_related else '非AI'}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error analyzing paper: {e}")
            return {
                'is_ai_related': False,
                'judgment': "Unable to determine",
                'explanation': f"Error during analysis: {str(e)}",
                'thinking': "Analysis failed"
            }

    def batch_analyze_papers_concurrent(self, paper_list, max_workers=20):
        """
        并发分析多篇论文是否与AI相关（顺序保持版）

        参数:
            paper_list (list): 每项为 {'title': ..., 'abstract': ...}
            max_workers (int): 最大并发线程数

        返回:
            list[dict]: 每篇论文的分析结果列表（顺序与输入保持一致）
        """
        results = [None] * len(paper_list)  # 初始化结果列表

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务，附加索引保证顺序
            future_to_index = {
                executor.submit(self.analyze_paper, paper['title'], paper['abstract']): idx
                for idx, paper in enumerate(paper_list)
            }

            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    self.logger.error(f"[并发分析] 处理第 {idx} 篇论文时失败: {e}")
                    results[idx] = {
                        'is_ai_related': False,
                        'judgment': "Error",
                        'explanation': f"Error: {e}",
                        'thinking': "Analysis failed due to exception"
                    }

        return results
    def batch_analyze_papers(self, papers):
        """
        批量分析多篇论文
        
        参数:
            papers (list): 论文列表，每篇论文是包含title和abstract的字典
            
        返回:
            list: 包含每篇论文分析结果的列表
        """
        results = []
        for i, paper in enumerate(papers):
            self.logger.info(f"分析第 {i+1}/{len(papers)} 篇论文")
            result = self.analyze_paper(paper['title'], paper['abstract'])
            results.append({
                'paper': paper,
                'analysis': result
            })
        return results
    
    def save_analysis_results(self, results, output_file='analysis_results.json'):
        """
        保存分析结果到文件
        
        参数:
            results (list): 分析结果列表
            output_file (str): 输出文件路径
        """
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            self.logger.info(f"分析结果已保存至 {output_file}")
            return True
        except Exception as e:
            self.logger.error(f"保存分析结果时出错: {e}")
            return False

# 示例用法
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 创建代理实例
    agent = PaperAgent()
    
    # 测试论文
    test_paper = {
        'title': 'The evolutionary significance of post-transcriptional gene regulation',
        'abstract': 'Understanding the molecular mechanisms that give rise to phenotypic diversity is a major goal in evolutionary biology. Ever since King and Wilson (1975) hypothesised that changes in gene regulation may be important for species’ evolution, research has explored the various ways in which regulation of gene expression may have mediated evolutionary transitions and innovations. So far, most studies have focused on changes in mRNA abundance, i.e., total gene expression. However, the regulation of genes is not restricted to their transcript levels but includes a wide range of post-transcriptional mechanisms that affect transcript levels, functions, and/or transcript structures. These include the control of transcript levels through miRNAs (Filipowicz et al. 2008), RNA modifications (Zhao et al. 2017), and/or changes in transcript structure through alternative splicing (Verta and Jacobs 2022). In contrast to gene transcript level variation, the role of post-transcriptional mechanisms in mediating phenotypic diversity and evolutionary dynamics remain relatively unknown, yet recent work has argued that post-transcriptional processes play a potentially important role in adaptation (Verta and Jacobs 2022; Singh and Ahi 2022; Wright et al. 2022).'
    }
    
    # 分析论文
    result = agent.analyze_paper(test_paper['title'], test_paper['abstract'])
    
    # 打印结果
    print(f"是否有关: {result['is_ai_related']}")
    print(f"判断: {result['judgment']}")
    print(f"思考过程: {result['thinking']}")
    print(f"解释: {result['explanation']}")
