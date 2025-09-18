学术期刊数据爬虫，目前分为两个版本：
crawler：完整版，目前支持四个期刊的内容爬取（nature、science、plos、cell），子刊源均筛选处理。
crawler_light：轻量版，数据直接导出为表格，不再保存数据库。

# 学术期刊爬虫
crawler：一个完整统一的学术期刊爬虫系统，支持Nature、Science、Cell、PLOS四个期刊的论文抓取和AI相关性分析，保存数据库，可支持导出为表格。
crawler_light：一个轻量级的学术期刊爬虫系统，支持Nature、Science、Cell、PLOS四个期刊的论文抓取和AI相关性分析，导出为Excel、CSV或JSON格式。

## 快速开始（两个版本的爬虫具体执行略有区别，以各自的readme文档为主）

### 安装依赖
```bash
pip install -r requirements.txt
```
#### 全量爬取
```bash
# 爬取单个期刊
python main_forward.py -j nature
```

#### 定时爬取（智能调度）
```bash
# 运行智能定时爬虫
python main_backward.py

# 第一次运行：指定时间范围（推荐）
python main_backward.py -j nature --start-date 2025-09-01 --end-date 2025-09-16

# 后续运行：自动从各子刊的pubdate开始
python main_backward.py -j nature
```

#### 数据导出
```bash
# 基本用法：导出指定期刊的所有数据（CSV格式）
python tools/export_papers.py -j nature -f csv

# 导出指定期刊的所有数据（Excel格式）
python tools/export_papers.py -j nature -f xlsx

# 导出指定日期范围的数据
python tools/export_papers.py -j nature -f csv -s 2025-01-01 -e 2025-01-31

# 快速导出最近N天的数据
python tools/export_papers.py -j nature -d 30 --quick

# 支持的期刊：nature, science, cell, plos
# 支持的格式：csv, xlsx, json, markdown

# 查看帮助信息
python tools/export_papers.py --help
```
