# 统一学术期刊爬虫系统技术文档

## 概述

本系统是一个统一的学术期刊爬虫系统，支持Nature、Science、Cell、PLOS四个期刊的论文抓取和AI相关性分析。系统采用模块化架构，每个期刊都有专门的解析器，支持requests优先+Selenium备选的双重策略，具备完善的反爬虫机制和智能容错能力。

## 架构概览

```
crawler/
|-- config.yaml              # 统一配置文件
|-- main.py                  # 全量爬取入口
|-- main_back.py             # 增量爬取入口
|-- db.py                    # 统一数据库模块
|-- parser.py                # 统一解析器模块
|-- agent.py                 # AI分析代理
|-- tools/
    |-- export_papers.py     # 数据导出工具
```

## 核心类架构

### BaseParser (基础解析器)

所有期刊解析器的基类，提供通用功能：

```python
class BaseParser:
    def __init__(self, journal_type, database=None, paper_agent=None, use_selenium=False):
        self.journal_type = journal_type
        self.db = database
        self.paper_agent = paper_agent
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE
        self.driver = None
        self.session = requests.Session()
```

**核心功能：**
- 统一的Session管理和User-Agent配置
- Selenium WebDriver初始化和管理
- 通用的重试机制和错误处理
- 人工延迟模拟

---

## 1. Nature期刊爬虫 (NatureParser)

### 1.1 爬取策略
**单一策略：** 纯requests方式，无需Selenium

### 1.2 页面访问逻辑

```python
def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
    # 1. 直接访问期刊主页
    response = self.session.get(base_url, timeout=30)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 2. 解析文章链接
    article_links = soup.find_all('a', href=True)
```

### 1.3 文章信息提取

#### 1.3.1 标题提取
```python
title = link.get_text(strip=True)
```

#### 1.3.2 详情页面处理
```python
def fetch_real_abstract_and_doi(self, url):
    response = self.session.get(url, timeout=15)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 摘要提取
    abstract_elem = soup.find('meta', attrs={'name': 'description'})
    abstract = abstract_elem.get('content', '') if abstract_elem else ''
    
    # DOI提取
    doi_elem = soup.find('meta', attrs={'name': 'citation_doi'})
    doi = doi_elem.get('content', '') if doi_elem else ''
    
    return abstract, doi
```

#### 1.3.3 日期提取
```python
# 从文章链接的父元素查找时间标签
parent_elem = link.parent
if parent_elem:
    time_tag = parent_elem.find('time')
    if time_tag:
        raw_date = time_tag.get('datetime', time_tag.get_text(strip=True))
        pub_date = dateparser.parse(raw_date).date()
```

### 1.4 数据结构
```python
article = {
    'title': title,
    'abstract': abstract,
    'doi': doi,
    'url': full_url,
    'date': pub_date,
    'journal': journal_name,
    'authors': ''
}
```

---

## 2. Science期刊爬虫 (ScienceParser)

### 2.1 爬取策略
**混合策略：** requests优先，Selenium备选，多URL回退机制

### 2.2 多URL策略

```python
def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
    # 构建多个候选URL
    candidate_urls = []
    
    # 主要URL：/research路径
    research_url = base_url.rstrip('/') + '/research'
    candidate_urls.append(research_url)
    
    # 备选URL：原始base_url
    candidate_urls.append(base_url)
    
    # 其他备选路径
    other_urls = ['/current', '/archive', '/content/by/year']
    for path in other_urls:
        candidate_urls.append(base_url.rstrip('/') + path)
```

### 2.3 文章列表解析

#### 2.3.1 Requests方式
```python
def _extract_science_articles_from_page(self, response):
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 文章卡片选择器（基于实际HTML结构）
    card_selectors = [
        'div.card.pb-3.mb-4',           # 主要文章卡片
        'div.latest-news__item',        # 新闻列表项
        'article.content-item'          # 内容项
    ]
    
    articles = []
    for selector in card_selectors:
        cards = soup.select(selector)
        for card in cards:
            article_info = self._extract_science_article_info(card)
            if article_info:
                articles.append(article_info)
```

#### 2.3.2 文章信息提取
```python
def _extract_science_article_info(self, card_elem):
    # 标题和链接
    link_selectors = [
        'a.text-reset.animation-underline',  # 主要链接样式
        'h2 a',                             # 标题链接
        'h3 a',                             # 副标题链接
        'a[href*="/doi/"]'                  # DOI链接
    ]
    
    for selector in link_selectors:
        link_elem = card_elem.select_one(selector)
        if link_elem:
            title = link_elem.get_text(strip=True)
            href = link_elem.get('href', '')
            
            # 构建完整URL
            if href.startswith('/'):
                full_url = f"https://www.science.org{href}"
            else:
                full_url = href
            
            return {
                'title': title,
                'url': full_url,
                'source_card': card_elem
            }
```

### 2.4 详情页面解析

```python
def _get_science_article_details(self, url: str):
    response = self.get_page_with_retry(url, max_retries=3, timeout=15)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 标题提取（多选择器策略）
    title_selectors = [
        'h1[property="name"]',      # Schema.org属性
        'h1.article-title',         # 文章标题样式
        'h1',                       # 通用h1标签
        '.article-title'            # 标题类
    ]
    
    # 摘要提取
    abstract_selectors = [
        'section#abstract[property="abstract"]',  # Schema.org摘要
        'div#abstracts',                         # 摘要容器
        'section[role="doc-abstract"]',          # 语义化摘要
        'div.abstractContent'                    # 摘要内容
    ]
    
    # DOI提取（多种方式）
    # 方式1：sameAs链接
    doi_link = soup.select_one('a[property="sameAs"]')
    if doi_link:
        doi_url = doi_link.get('href', '')
        if 'doi.org' in doi_url:
            doi = doi_url.split('/')[-1]
    
    # 方式2：页面文本正则匹配
    if not doi:
        doi_pattern = r'10\.1126/[a-zA-Z]+\.[a-zA-Z0-9]+'
        doi_match = re.search(doi_pattern, response.text)
        if doi_match:
            doi = doi_match.group()
    
    # 方式3：meta标签
    if not doi:
        doi_meta = soup.find('meta', attrs={'name': 'citation_doi'})
        if doi_meta:
            doi = doi_meta.get('content', '')
    
    # DOI后缀处理（Science特有）
    if doi and not doi.startswith('10.1126/'):
        doi = f"10.1126/{doi}"
    
    # 构建正确的Science文章URL
    science_url = f"https://www.science.org/doi/{doi}" if doi else url
```

### 2.5 Selenium回退机制

```python
def _scrape_with_selenium(self, url, journal_name, max_wait=180):
    # Science默认3分钟等待
    self.driver.get(url)
    
    # 等待页面加载完成
    WebDriverWait(self.driver, 15).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    
    # 使用wait_for_page_load处理反爬虫页面
    if not self.wait_for_page_load(self.driver, max_wait):
        return []
    
    # 解析页面内容
    soup = BeautifulSoup(self.driver.page_source, 'html.parser')
    # ... 使用相同的解析逻辑
```

---

## 3. Cell期刊爬虫 (CellParser)

### 3.1 爬取策略
**混合策略：** requests优先，Selenium备选（3分钟超时）

### 3.2 期次列表获取（智能日期筛选优化）

#### 3.2.1 年份级别筛选

```python
def _extract_volume_issue_links(self, archive_url, start_date=None, end_date=None):
    # 1. 年份级别快速筛选
    volume_sections = soup.find_all(['h2', 'h3', 'div'], 
                                   string=lambda text: text and 'Volume' in text and '(' in text and ')' in text)
    
    if start_date and end_date:
        target_years = set(range(start_date.year, end_date.year + 1))
        
        for volume_element in volume_sections:
            volume_text = volume_element.get_text(strip=True)
            # 匹配 "Volume 37 (2025)" 格式
            year_match = re.search(r'Volume\s+\d+\s*\((\d{4})\)', volume_text)
            if year_match:
                year = int(year_match.group(1))
                if year not in target_years:
                    logger.info(f"年份 {year} 超出范围，跳过整个卷")
```

#### 3.2.2 期次级别精确筛选

```python
    # 2. 期次级别精确筛选
    for span in spans:
        span_text = span.get_text(strip=True)
        # 查找日期模式（如 "September 02, 2025"）
        date_match = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', span_text)
        if date_match:
            month_name, day, year = date_match.groups()
            parsed_date = dateparser.parse(f"{month_name} {day}, {year}")
            if parsed_date:
                issue_date = parsed_date.date()
                if issue_date < start_date or issue_date > end_date:
                    logger.debug(f"期次日期 {issue_date} 超出范围，跳过")
                    should_include = False
```

#### 3.2.3 优化效果统计

```python
def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
    # 1. 获取期次列表（应用日期筛选优化）
    issue_links = self._extract_volume_issue_links(archive_url, start_date, end_date)
    
    # 输出优化效果：
    # "年份筛选优化：检测到年份 [2024, 2025]，已跳过不相关年份的期次"
    # "日期筛选优化：共检测到 45 个期次，跳过 32 个超出日期范围的期次，节省 32 次页面访问"
    
    # 2. 处理每个期次
    for i, issue_info in enumerate(issue_links):
        issue_url = urljoin('https://www.cell.com', issue_info['url'])
        issue_articles = self._extract_articles_from_issue(issue_url, journal_name, start_date, end_date)
```

### 3.3 期次文章提取

#### 3.3.1 HTML结构分析
Cell期刊使用复杂的嵌套结构：

```html
<section class="toc__section">
    <li class="articleCitation">
        <div class="toc__item_clearfix" data-pii="S0092-8674(25)00923-7">
            <!-- 文章信息 -->
        </div>
    </li>
</section>
```

#### 3.3.2 文章解析逻辑

```python
def _extract_articles_from_issue(self, issue_url, journal_name, start_date, end_date):
    # 获取期次页面
    response = self._get_page_with_retry(issue_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 查找所有section
    sections = soup.find_all('section', class_='toc__section')
    
    for section in sections:
        # 获取section中的文章
        section_articles = section.find_all('li', class_='articleCitation')
        
        for article_elem in section_articles:
            # 方法1：查找data-pii属性（优先）
            pii = None
            pii_selectors = [
                'div[data-pii]',                    # div元素包含data-pii
                '.toc__item_clearfix[data-pii]',    # 特定类名包含data-pii
                '[data-pii]'                        # 任何包含data-pii的元素
            ]
            
            for pii_selector in pii_selectors:
                pii_element = article_elem.select_one(pii_selector)
                if pii_element and pii_element.get('data-pii'):
                    pii = pii_element.get('data-pii')
                    break
            
            if pii:
                # 构建文章URL
                journal_path = self._get_cell_journal_path(issue_url)
                detail_url = f"https://www.cell.com/{journal_path}/fulltext/{pii}"
                
                # 获取文章详情
                article_details = self._get_cell_article_details_from_abstract(detail_url)
```

### 3.4 期刊路径映射

```python
def _get_cell_journal_path(self, issue_url):
    """从期次URL中提取期刊路径名"""
    path_mapping = {
        '/cell/': 'cell',
        '/cell-metabolism/': 'cell-metabolism',
        '/molecular-cell/': 'molecular-cell',
        '/developmental-cell/': 'developmental-cell',
        '/current-biology/': 'current-biology',
        '/structure/': 'structure',
        # ... 更多映射
    }
    
    for path_key, journal_path in path_mapping.items():
        if path_key in issue_url:
            return journal_path
    
    return 'cell'  # 默认值
```

### 3.5 详情页面解析

#### 3.5.1 Cell文章详情解析

```python
def _get_cell_article_details_from_abstract(self, abstract_url: str):
    # 使用专门的Cell详情解析器
    from cell.cell_detail_parser import CellDetailParser
    
    cell_parser = CellDetailParser()
    article_data = cell_parser.parse_article_details(abstract_url)
    
    if article_data:
        # 标题提取
        title_selectors = [
            'h1.article-title.article-title-main',
            'h1.article-title',
            'h1'
        ]
        
        # 摘要提取（多级策略）
        detailed_abstract_selectors = [
            'div#abstracts',                    # 主要摘要容器
            'section.abstract',                 # 语义化摘要
            'div.abstract-content',             # 摘要内容
            'div.article-section__content p'    # 文章段落
        ]
        
        # 日期提取（区分文章类型）
        if is_correction:
            # 勘误文章：使用原始发表日期
            date_selectors = [
                'div.content--publishDate',
                '.content--publishDate'
            ]
        else:
            # 正常文章：使用在线日期
            date_selectors = [
                'span.meta-panel__onlineDate',
                '.meta-panel__onlineDate'
            ]
```

#### 3.5.2 PII到DOI的转换

```python
# DOI提取 - 从URL中提取PII
if '/abstract/' in abstract_url:
    # 例如: https://www.cell.com/cell/abstract/S0092-8674(25)00923-7
    doi_part = abstract_url.split('/abstract/')[-1]
    if doi_part:
        doi = doi_part  # PII作为DOI使用
```

---

## 4. PLOS期刊爬虫 (PLOSParser)

### 4.1 爬取策略
**三重策略：** Selenium优先 + requests备选 + volume页面备选

### 4.1.1 动态期刊发现
系统启动时自动从 https://plos.org/ 获取最新期刊列表：
- 解析 `<div class="menu-journals-container">` 获取14个子刊
- 自动备份原配置为 `.backup` 文件
- 仅在获取到10个以上期刊时才更新配置

### 4.1.2 备选爬取逻辑
当主逻辑失败时，启动volume页面备选逻辑：
- 访问 `{journal_url}/volume` 页面
- 解析 `<ul id="journal_slides">` 获取年份期次
- 遍历符合时间范围的月份期次
- 从期次页面提取文章详情

#### PLOSFallbackParser类
独立的备选解析器，实现volume页面解析：

```python
class PLOSFallbackParser:
    def _extract_issue_links(self, soup, start_date, end_date):
        """从volume页面提取符合时间范围的期次链接"""
        issue_links = []
        journal_slides = soup.find('ul', id='journal_slides')
        
        for year_slide in journal_slides.find_all('li', class_='slide'):
            year = int(year_slide.get('id'))
            # 检查年份是否在范围内
            if start_date.year <= year <= end_date.year:
                # 解析月份期次
                for link in year_slide.find_all('a', href=True):
                    month_name = link.find('span').get_text(strip=True)
                    month_num = self._month_name_to_number(month_name)
                    issue_date = date(year, month_num, 1)
                    
                    if self._is_issue_in_range(issue_date, start_date, end_date):
                        issue_links.append({
                            'url': urljoin('https://journals.plos.org', href),
                            'date': issue_date
                        })
        
        return issue_links
```

### 4.2 智能URL构建优化

#### 4.2.1 基于日期的直接搜索

```python
def build_search_url_with_page(self, journal_name: str, start_date: datetime, end_date: datetime, page: int = 1):
    """构建带分页的PLOS搜索URL，直接按日期筛选"""
    journal_code = journal_name.replace(' ', '').replace('PLOS', 'PLOS')
    journal_path = self.journal_code_to_path.get(journal_code, 'plosone')
    
    # 构建搜索URL - 直接使用日期参数
    start_date_str = start_date.strftime('%Y-%m-%d')
    start_index = (page - 1) * 60  # 每页60篇
    
    params = {
        'filterJournals': journal_code,
        'filterStartDate': start_date_str,  # 关键优化：服务器端日期筛选
        'resultsPerPage': '60',
        'startPage': str(start_index),
        'q': '',
        'sortOrder': 'DATE_NEWEST_FIRST'
    }
    
    # 优势：避免加载不相关时间段的文章，减少网络开销
```

#### 4.2.2 期刊代码映射

```python
self.journal_code_to_path = {
    'PLOSOne': 'plosone',
    'PLOSBiology': 'plosbiology', 
    'PLOSMedicine': 'plosmedicine',
    'PLOSClimate': 'climate',  # 动态路径映射
    'PLOSWater': 'water',
    # ... 自动适配各子刊路径
}
```

### 4.3 JavaScript动态加载处理

```python
def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
    # PLOS页面使用JavaScript动态加载，优先使用Selenium
    if self.driver:
        articles = self._scrape_all_pages_with_selenium(journal_name, start_date, end_date)
    else:
        # 如果Selenium不可用，尝试requests（可能获取不到动态内容）
        articles = self._scrape_with_requests(journal_name, start_date, end_date)
```

### 4.4 Selenium页面等待策略

```python
def _scrape_single_page_with_selenium(self, url: str, journal_name: str, start_date: datetime, end_date: datetime):
    self.driver.get(url)
    
    # 等待页面完全加载
    WebDriverWait(self.driver, 15).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    
    # 额外等待JavaScript动态内容加载
    time.sleep(8)
    
    # 等待搜索结果容器出现
    try:
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "search-results-list"))
        )
    except Exception as e:
        logger.warning(f"等待搜索结果容器超时: {e}")
    
    # 再次等待确保动态内容完全渲染
    time.sleep(5)
    
    # 如果仍然没找到，尝试滚动页面触发懒加载
    if len(doi_elements) == 0:
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)
```

### 4.5 动态内容解析

#### 4.5.1 基于data-doi的文章提取

```python
# 查找包含data-doi的dt元素（基于HTML结构）
doi_elements = soup.find_all('dt', attrs={'data-doi': True})

for dt_elem in doi_elements:
    data_doi = dt_elem.get('data-doi')
    if data_doi:
        # 查找href属性从链接中获取完整路径
        link_elem = dt_elem.find('a', href=True)
        if link_elem:
            href = link_elem.get('href')
            # 构建完整URL：href通常是 "/climate/article?id=10.1371/journal.pclm.0000697"
            if href.startswith('/'):
                article_url = f"https://journals.plos.org{href}"
            
            # 获取文章详情
            article_data = self._get_plos_article_details_from_page(article_url)
```

#### 4.4.2 期刊路径动态识别

```python
# 根据href动态构建URL，而不是使用固定映射
# 例如：href="/climate/article?id=10.1371/journal.pclm.0000697"
# 结果：https://journals.plos.org/climate/article?id=10.1371/journal.pclm.0000697

# 这确保了每个PLOS子期刊都使用正确的路径
```

### 4.5 详情页面解析

```python
def _get_plos_article_details_from_page(self, article_url):
    response = self.get_page_with_retry_plos(article_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 标题提取（基于实际页面结构）
    title_selectors = [
        'h1#artTitle',              # 主要标题ID
        'div.title-authors h1',     # 标题-作者区域
        'h1.title',
        'h1#title',
        'h1'
    ]
    
    # 摘要提取
    abstract_selectors = [
        'div.article-content div#artText p',  # 文章内容区域
        'div.abstract-content',
        'section.abstract',
        'div#abstract',
        'div.abstract'
    ]
    
    # 日期提取（特殊处理）
    date_selectors = [
        'li#artPubDate',        # 发表日期ID
        'ul.date-doi li',       # DOI-日期列表
        'time.published',
        '.pub-date'
    ]
    
    # 日期文本清理（修正后的逻辑）
    for selector in date_selectors:
        date_elem = soup.select_one(selector)
        if date_elem:
            date_text = date_elem.get_text(strip=True)
            
            # 只移除'Published:'前缀，保留月份名称
            date_text = date_text.replace('Published:', '').strip()
            # 例如："Published: September 10, 2025" -> "September 10, 2025"
            
            pub_date = dateparser.parse(date_text).date()
```

---

## 5. 数据保存逻辑

### 5.1 数据库架构

```python
# db.py - 统一数据库类
class UnifiedDB:
    def __init__(self, journal_type):
        self.journal_type = journal_type
        self.table_name = journal_type  # nature, science, cell, plos
        
    def create_table(self):
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title TEXT NOT NULL,
            abstract TEXT,
            doi VARCHAR(255),
            url TEXT,
            date DATE,
            authors TEXT,
            journal VARCHAR(100),
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_date (date),
            INDEX idx_journal (journal),
            INDEX idx_doi (doi)
        )
        """
```

### 5.2 增量爬取逻辑

```python
# main_back.py - 增量爬取主逻辑
def run_incremental_crawl(self, journals):
    for journal in journals:
        # 1. 获取该期刊的最新时间戳
        db = UnifiedDB(journal)
        
        for journal_info in journal_list:
            journal_name = journal_info['name']
            
            # 按子刊获取最新时间
            start_date = db.get_last_update_time(
                resume=True, 
                journal_name=journal_name  # 子刊名称
            )
            
            # 2. 爬取新文章
            parser = create_parser(journal, db, paper_agent)
            articles = parser.scrape_journal(
                journal_info, 
                start_date=start_date, 
                end_date=datetime.now().date()
            )
            
            # 3. AI分析（三重验证）
            if articles:
                analyzed_articles = self._analyze_articles_with_ai(articles)
                
                # 4. 保存到数据库
                for article in analyzed_articles:
                    db.insert_paper(article)
```

### 5.3 AI分析逻辑

```python
# agent.py - AI分析代理
class PaperAgent:
    def batch_analyze_papers_in_batches_concurrent(self, contents, batch_size=10):
        # 三重验证机制
        result1 = self._batch_analyze(contents, batch_size)
        result2 = self._batch_analyze(contents, batch_size)
        
        final_results = []
        for paper in contents:
            r1 = result1.get(paper['id'])
            r2 = result2.get(paper['id'])
            
            if r1['is_ai_related'] and r2['is_ai_related']:
                # 两次都判断为AI相关
                final_results.append({
                    'id': paper['id'],
                    'is_ai_related': True,
                    'explanation': r1['explanation']
                })
            elif not r1['is_ai_related'] and not r2['is_ai_related']:
                # 两次都判断为非AI相关
                final_results.append({
                    'id': paper['id'],
                    'is_ai_related': False,
                    'explanation': r1['explanation']
                })
            else:
                # 结果不一致，进行第三次分析
                review = self.analyze_paper(paper['title'], paper['abstract'])
                final_results.append({
                    'id': paper['id'],
                    'is_ai_related': review['is_ai_related'],
                    'explanation': review['explanation']
                })
        
        return final_results
```

### 5.4 按子刊精确更新

```python
def get_last_update_time(self, journal_name: str = None) -> Optional[datetime]:
    """获取指定子刊的最新更新时间"""
    try:
        if journal_name:
            # 按子刊查询
            query = f"SELECT MAX(date) FROM {self.table_name} WHERE journal = %s"
            self.cursor.execute(query, (journal_name,))
        else:
            # 查询整个期刊
            query = f"SELECT MAX(date) FROM {self.table_name}"
            self.cursor.execute(query)
        
        result = self.cursor.fetchone()
        if result and result[0]:
            return datetime.combine(result[0], datetime.min.time())
        else:
            # 如果没有数据，使用前一周作为起始日期
            return datetime.now() - timedelta(weeks=1)
```

---

## 6. 反爬虫对策

### 6.1 User-Agent轮换

```python
# 每个期刊都有专门的User-Agent列表
science_user_agents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
    # ... 更多
]

# 在请求时轮换
def get_page_with_retry(self, url, max_retries=5, timeout=60):
    for attempt in range(max_retries):
        # 轮换User-Agent
        user_agent = random.choice(self.user_agents)
        self.session.headers['User-Agent'] = user_agent
```

### 6.2 智能延迟

```python
def human_like_delay(self):
    """模拟人类行为的随机延迟"""
    delay = random.uniform(1, 3)  # 1-3秒随机延迟
    time.sleep(delay)

# 在请求间使用
time.sleep(random.uniform(2, 5))  # 页面间延迟
time.sleep(random.uniform(5, 15))  # 重试间延迟
```

### 6.3 反爬虫页面检测和处理

```python
def wait_for_page_load(self, driver, max_wait=60):
    """等待页面完全加载，处理'Just a moment...'等反爬虫页面"""
    start_time = time.time()
    consecutive_anti_bot = 0
    
    while time.time() - start_time < max_wait:
        # 检查页面标题和内容
        title = driver.title.lower()
        page_source = driver.page_source.lower()
        
        # 检测反爬虫页面
        anti_bot_phrases = [
            'just a moment', 'please wait', 'checking your browser',
            'cloudflare', 'ddos protection', 'access denied',
            'blocked', 'security check', 'ray id'
        ]
        
        is_anti_bot = any(phrase in title or phrase in page_source for phrase in anti_bot_phrases)
        
        if is_anti_bot:
            consecutive_anti_bot += 1
            
            # 如果连续多次检测到反爬虫页面，尝试模拟人类行为
            if consecutive_anti_bot > 5:
                # 滚动页面
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)
                
                # 尝试点击页面
                clickable = driver.find_elements(By.TAG_NAME, "button")
                if clickable:
                    try:
                        clickable[0].click()
                        time.sleep(3)
                    except:
                        pass
            
            # Just a moment页面需要更长等待时间
            is_just_a_moment = 'just a moment' in title or 'just a moment' in page_source
            wait_time = 8 if is_just_a_moment else (5 if consecutive_anti_bot > 3 else 3)
            time.sleep(wait_time)
            continue
        else:
            consecutive_anti_bot = 0
        
        # 检查页面是否有实际内容
        if len(page_source) > 1000:
            if any(keyword in page_source for keyword in ['science', 'research', 'article', 'doi']):
                return True
        
        time.sleep(2)
    
    return False
```

### 6.4 重试机制

```python
# 配置requests重试策略
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry_strategy = Retry(
    total=10,                                   # 总重试次数
    backoff_factor=8,                          # 退避因子
    status_forcelist=[403, 429, 500, 502, 503, 504],  # 需要重试的状态码
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)

adapter = HTTPAdapter(max_retries=retry_strategy)
self.session.mount("http://", adapter)
self.session.mount("https://", adapter)

# 增强的重试方法
def get_page_with_retry(self, url, max_retries=5, timeout=60):
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = random.uniform(5, 15) * (attempt + 1)  # 递增延迟
                time.sleep(delay)
            
            response = self.session.get(url, timeout=timeout)
            
            if response.status_code == 200:
                return response
            elif response.status_code == 403:
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(10, 20))  # 403错误更长等待
                    continue
                    
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(random.uniform(5, 12))
    
    return None
```

---

## 7. 错误处理和日志

### 7.1 分层日志记录

```python
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("crawler_back.log"),  # 文件日志
        logging.StreamHandler()                   # 控制台日志
    ]
)

logger = logging.getLogger(__name__)
```

### 7.2 失败期刊跟踪

```python
class ScienceParser(BaseParser):
    def __init__(self):
        self.failed_journals = []  # 跟踪失败的期刊
        
    def scrape_journal(self, journal_name, ...):
        try:
            # 爬取逻辑
            articles = self._scrape_articles(...)
            if not articles:
                self.failed_journals.append(journal_name)
                logger.warning(f"期刊 {journal_name} 爬取失败，无文章获取")
        except Exception as e:
            self.failed_journals.append(journal_name)
            logger.error(f"期刊 {journal_name} 爬取异常: {e}")
        
        return articles
    
    def get_failed_journals_summary(self):
        """获取失败期刊汇总"""
        return {
            'total_failed': len(self.failed_journals),
            'failed_list': self.failed_journals
        }
```

### 7.3 数据验证

```python
def validate_article_data(self, article):
    """验证文章数据完整性"""
    required_fields = ['title', 'url', 'date']
    
    for field in required_fields:
        if not article.get(field):
            logger.warning(f"文章缺少必要字段 {field}: {article.get('title', 'Unknown')}")
            return False
    
    # 验证日期格式
    if not isinstance(article['date'], date):
        try:
            article['date'] = dateparser.parse(article['date']).date()
        except:
            logger.warning(f"无效日期格式: {article['date']}")
            return False
    
    return True
```

---

## 8. 性能优化

### 8.1 并发处理

```python
# AI分析的并发处理
import concurrent.futures

def batch_analyze_papers_in_batches_concurrent(self, contents, batch_size=10):
    """并发批量分析论文"""
    
    # 分批处理
    batches = [contents[i:i + batch_size] for i in range(0, len(contents), batch_size)]
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # 提交批次到线程池
        future_to_batch = {
            executor.submit(self._analyze_batch, batch): batch 
            for batch in batches
        }
        
        # 收集结果
        for future in concurrent.futures.as_completed(future_to_batch):
            batch_results = future.result()
            results.extend(batch_results)
    
    return results
```

### 8.2 连接池优化

```python
# Session配置优化
session = requests.Session()

# 设置连接池大小
session.mount('https://', HTTPAdapter(
    pool_connections=10,    # 连接池大小
    pool_maxsize=20,       # 最大连接数
    max_retries=retry_strategy
))
```

### 8.3 内存管理

```python
def process_large_dataset(self, articles):
    """分批处理大数据集"""
    batch_size = 100
    
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        
        # 处理批次
        processed_batch = self._process_batch(batch)
        
        # 保存批次结果
        self._save_batch(processed_batch)
        
        # 清理内存
        del processed_batch
        gc.collect()
```

---

## 9. 配置管理

### 9.1 配置文件结构

```yaml
# config.yaml
# 数据库配置
MYSQL_HOST: localhost
MYSQL_PORT: 3306
MYSQL_USER: root
MYSQL_PASSWORD: "123123"
MYSQL_DATABASE: paper

# AI分析配置
MAIN_LLM_MODEL: deepseek-chat
OPENAI_API_KEY: sk-xxx
OPENAI_BASE_URL: https://api.deepseek.com/v1

# 期刊列表文件
JOURNALS_PATH_NATURE: nature_journals.json
JOURNALS_PATH_SCIENCE: science_journals.json
JOURNALS_PATH_CELL: cell_journals.json
JOURNALS_PATH_PLOS: plos_journals.json

# 表名映射
TABLE_NAME_NATURE: nature
TABLE_NAME_SCIENCE: science
TABLE_NAME_CELL: cell
TABLE_NAME_PLOS: plos
```

### 9.2 期刊配置文件

```json
// nature_journals.json
[
  {
    "name": "Nature",
    "url": "https://www.nature.com/nature/",
    "is_journal": true
  },
  {
    "name": "Nature Biotechnology", 
    "url": "https://www.nature.com/nbt/",
    "is_journal": true
  }
  // ... 更多期刊
]
```

---

## 10. 使用示例

### 10.1 全量爬取

```bash
# 爬取单个期刊
python main.py -j nature

# 爬取多个期刊
python main.py -j nature,science,cell,plos

# 指定特定子刊
python main.py -j nature --journals "Nature,Nature Biotechnology"
```

### 10.2 增量爬取

```bash
# 增量爬取Nature（每个子刊独立更新）
python main_back.py -j nature

# 爬取多个期刊
python main_back.py -j nature,science,cell,plos
```

### 10.3 数据导出

```bash
# 导出CSV格式
python tools/export_papers.py -j nature -f csv

# 导出JSON格式  
python tools/export_papers.py -j nature,science -f json

# 查看统计信息
python tools/export_papers.py -j nature,science,cell,plos --stats-only
```

---

## 总结

本系统采用了模块化设计，每个期刊都有针对性的处理策略：

1. **Nature**: 纯requests，简单高效
2. **Science**: 混合策略，多URL回退
3. **Cell**: 复杂的期次-文章层级结构处理
4. **PLOS**: Selenium处理JavaScript动态加载

通过统一的接口和数据结构，系统实现了：
- 高效的数据抓取
- 智能的反爬虫对策
- 可靠的错误处理
- 精确的增量更新
- 强大的AI分析能力

系统具有良好的可扩展性，可以轻松添加新的期刊支持。

## 最新更新 (2025-09-11)

### 变量作用域修复
- 修复了Science爬取中的card_infos变量作用域问题
- 确保在所有场景下（有文章、无文章、日期筛选后为空）都能正常运行
- 避免`cannot access local variable 'card_infos' where it is not associated with a value`错误

### 失败判断逻辑优化  
- 澄清失败判断标准：只有真正的技术错误才算失败
- 网络错误(403/超时等)和解析错误 -> 算失败
- 日期筛选导致0篇文章 -> 算成功（这是正常的业务逻辑）
- 提供更准确的子刊成功/失败统计

### 代码质量提升
- 移除所有emoji符号和特殊字符，确保代码兼容性
- 统一使用ASCII字符，避免编码问题
- 完善错误处理逻辑，提高系统稳定性

### 日期筛选智能优化
- **宽松模式机制**：当严格日期范围内找不到卷次时，自动启用宽松模式
- **距离计算算法**：基于目标日期范围中心点，计算各卷次的时间距离
- **智能卷次选择**：自动选择距离最近的1-2个卷次，避免完全空结果
- **适用期刊**：Science和Cell期刊都支持此功能
- **应用场景**：特别适合用户选择很窄日期范围（1-2天）的情况

### Cell动态期刊发现
- **实时更新机制**：每次爬取前从cell.com主页动态获取期刊列表
- **智能回退策略**：issues → archive → archive?isCoverWidget=true
- **质量控制**：只有获取到>50个期刊时才更新JSON配置
- **容错处理**：动态获取失败时自动使用现有JSON配置
- **SSL优化**：自动禁用SSL警告，避免大量警告信息

### PLOS服务器端优化
- **服务器端过滤**：利用PLOS的filterEndDate参数进行服务器端日期过滤
- **详情页面提取**：直接从文章详情页面获取完整信息（标题、作者、DOI、日期、摘要）
- **多层日期提取**：支持从artPubDate、meta标签、内容正则匹配等多个位置提取日期
- **100%成功率**：优化后的日期解析成功率达到100%

### 作者信息提取优化
- **ORCID链接过滤**：自动识别并过滤掉作者信息中的ORCID URL链接
- **纯文本提取**：确保作者字段只包含姓名，不包含链接地址
- **多重回退机制**：链接文本提取失败时，回退到整个元素文本并清理URL
- **适用期刊**：主要优化Science期刊的作者信息提取

## 宽松模式技术实现

### Science期刊宽松模式

```python
def _find_nearest_volumes_science(self, volume_elements, start_date: date, end_date: date, year: int):
    """寻找最接近目标日期范围的Science卷次"""
    volumes_with_dates = []
    target_center = start_date + (end_date - start_date) / 2  # 目标范围中心点
    
    for volume_elem in volume_elements:
        # 提取卷次日期
        date_elem = volume_elem.select_one('.past-issue__content__item--cover-date')
        date_text = date_elem.get_text(strip=True)
        volume_date = dateparser.parse(f"{date_text} {year}").date()
        
        # 计算与目标范围中心的距离
        distance = abs((volume_date - target_center).days)
        
        volumes_with_dates.append({
            'url': volume_url,
            'title': volume_title,
            'distance': distance
        })
    
    # 按距离排序，选择最近的1-2个卷次
    volumes_with_dates.sort(key=lambda x: x['distance'])
    return volumes_with_dates[:2]
```

### Cell期刊宽松模式

```python
def _find_nearest_issues_cell(self, all_issue_links, start_date: date, end_date: date):
    """寻找最接近目标日期范围的Cell期次"""
    issues_with_dates = []
    target_center = start_date + (end_date - start_date) / 2
    
    for link in all_issue_links:
        # 从span中查找日期信息
        for span in link.select('span'):
            date_match = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', span.get_text())
            if date_match:
                issue_date = dateparser.parse(f"{date_match.groups()[0]} {date_match.groups()[1]}, {date_match.groups()[2]}").date()
                distance = abs((issue_date - target_center).days)
                
                issues_with_dates.append({
                    'title': issue_text,
                    'url': href,
                    'distance': distance
                })
                break
    
    # 按距离排序，选择最近的1-2个期次
    issues_with_dates.sort(key=lambda x: x['distance'])
    return issues_with_dates[:2]
```

### 作者信息ORCID链接过滤

```python
# Science作者信息提取优化
author_links = authors_elem.find_all('a')
if author_links:
    # 过滤掉纯URL的链接，只保留作者姓名
    author_names = []
    for link in author_links:
        text = link.get_text(strip=True)
        # 跳过以http开头的纯URL链接
        if not text.startswith('http'):
            author_names.append(text)
    
    if author_names:
        authors = '; '.join(author_names)
    else:
        # 回退到整个元素文本并清理URL
        full_text = authors_elem.get_text(strip=True)
        authors = re.sub(r'https?://[^\s;]+', '', full_text)
        authors = re.sub(r';\s*;', ';', authors)
        authors = authors.strip().rstrip(';')
```

## 日志系统优化

### 统一日志格式
所有期刊解析器采用统一的简洁日志格式：

```
Cell文章: [文章标题前80字符]
Science文章: [文章标题前80字符]  
PLOS文章: [文章标题前80字符]
PLOS备选文章: [文章标题前80字符]
```

### 日志级别分类
- **INFO**: 成功获取的文章信息
- **DEBUG**: 详细的解析过程和data-pii提取
- **WARNING**: 重试和回退操作
- **ERROR**: 爬取失败和异常情况

## 最新功能更新

### PLOS期刊增强
1. **动态期刊发现**: 自动从主站获取最新的14个子刊列表
2. **三重备选策略**: Selenium + requests + volume页面备选
3. **失败期刊管理**: 统一的失败记录和重试机制

### 系统优化
1. **日志简化**: 移除表情符号，统一格式
2. **错误处理**: 完善的容错和重试机制  
3. **性能优化**: 智能延迟和并发控制

通过这些细致的优化，确保每个期刊解析器都能稳定、准确地获取高质量的学术论文数据。
