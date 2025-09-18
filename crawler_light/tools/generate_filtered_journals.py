#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from datetime import datetime

try:
    from openpyxl import Workbook
except Exception as e:  # 延迟到运行前安装
    Workbook = None


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL_CONFIG_DIR = os.path.join(BASE_DIR, 'journals_config')
EXPORT_DIR = os.path.join(BASE_DIR, 'exports')


def ensure_dirs():
    if not os.path.exists(EXPORT_DIR):
        os.makedirs(EXPORT_DIR, exist_ok=True)


def load_family_list(filename):
    path = os.path.join(JOURNAL_CONFIG_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_curated_scoring():
    # 依据先前确认的稳态一区与评分（口碑/影响力/专业性，满分各10）
    nature_scores = {
        'Nature': (10, 10, 10),
        'Nature Medicine': (10, 10, 10),
        'Nature Biotechnology': (10, 10, 10),
        'Nature Methods': (9, 9, 9),
        'Nature Genetics': (10, 10, 10),
        'Nature Materials': (10, 10, 10),
        'Nature Nanotechnology': (10, 10, 10),
        'Nature Photonics': (10, 10, 10),
        'Nature Chemistry': (10, 10, 9),
        'Nature Physics': (10, 10, 9),
        'Nature Neuroscience': (10, 10, 10),
        'Nature Microbiology': (9, 9, 9),
        'Nature Catalysis': (10, 10, 9),
        'Nature Energy': (10, 10, 9),
        'Nature Sustainability': (9, 9, 9),
        'Nature Metabolism': (9, 9, 9),
        'Nature Communications': (9, 9, 8),
        'Nature Cell Biology': (10, 10, 10),
        'Nature Chemical Biology': (9, 9, 9),
        'Nature Ecology & Evolution': (9, 9, 9),
        'Nature Human Behaviour': (8, 8, 8),
        'Nature Plants': (9, 9, 9),
        'Nature Biomedical Engineering': (9, 9, 9),
        'Nature Machine Intelligence': (9, 9, 9),
    }

    science_scores = {
        'Science': (10, 10, 10),
        'Science Translational Medicine': (10, 10, 10),
        'Science Immunology': (9, 9, 9),
        'Science Robotics': (9, 9, 9),
        'Science Advances': (9, 9, 8),
        # 'Science Signaling': Excluded by default
    }

    cell_scores = {
        'Cell': (10, 10, 10),
        'Cancer Cell': (10, 10, 10),
        'Immunity': (10, 10, 10),
        'Molecular Cell': (10, 10, 10),
        'Neuron': (10, 10, 10),
        'Cell Host & Microbe': (10, 10, 10),
        'Cell Metabolism': (10, 10, 10),
        'Joule': (9, 9, 9),
        'Chem': (9, 9, 9),
        'Matter': (9, 9, 9),
        'One Earth': (9, 9, 9),
        'Molecular Therapy (partner)': (9, 9, 9),
        'Trends in Ecology & Evolution': (10, 10, 9),
        'Trends in Cognitive Sciences': (10, 10, 9),
        'Trends in Genetics': (9, 9, 9),
        'Trends in Microbiology': (9, 9, 9),
        'Trends in Biotechnology': (9, 9, 9),
        'Trends in Neurosciences': (9, 9, 9),
        'Trends in Pharmacological Sciences': (8, 8, 9),
    }

    plos_scores = {
        'PLOS Medicine': (9, 9, 9),
        'PLOS Biology': (9, 9, 9),
        'PLOS Genetics': (9, 9, 9),
        'PLOS Pathogens': (9, 9, 9),
        'PLOS Computational Biology': (9, 9, 9),
    }

    return nature_scores, science_scores, cell_scores, plos_scores


def filter_and_score():
    nature_list = load_family_list('nature_journals.json')
    science_list = load_family_list('science_journals.json')
    cell_list = load_family_list('cell_journals.json')
    plos_list = load_family_list('plos_journals.json')

    nature_scores, science_scores, cell_scores, plos_scores = build_curated_scoring()

    def apply_scores(items, family_name, score_map):
        results = []
        for item in items:
            name = item.get('name')
            link = item.get('link')
            if name in score_map:
                rep, imp, spec = score_map[name]
                total = rep + imp + spec
                results.append({
                    'family': family_name,
                    'name': name,
                    'link': link,
                    'scores': {
                        'reputation': rep,
                        'impact': imp,
                        'specialization': spec,
                        'total': total
                    }
                })
        return results

    combined = []
    combined.extend(apply_scores(nature_list, 'nature', nature_scores))
    combined.extend(apply_scores(science_list, 'science', science_scores))
    combined.extend(apply_scores(cell_list, 'cell', cell_scores))
    combined.extend(apply_scores(plos_list, 'plos', plos_scores))

    combined.sort(key=lambda x: (-x['scores']['total'], x['family'], x['name']))
    return combined


def write_json(items, path):
    payload = {
        'generated_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'families': ['nature', 'science', 'cell', 'plos'],
        'items': items
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_excel(items, path):
    if Workbook is None:
        raise RuntimeError('openpyxl 未安装')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Filtered Journals'
    ws.append(['Family', 'Name', 'Link', 'Reputation', 'Impact', 'Specialization', 'Total'])
    for it in items:
        ws.append([
            it.get('family'),
            it.get('name'),
            it.get('link'),
            it['scores'].get('reputation'),
            it['scores'].get('impact'),
            it['scores'].get('specialization'),
            it['scores'].get('total')
        ])
    wb.save(path)


def main():
    ensure_dirs()
    items = filter_and_score()
    json_path = os.path.join(EXPORT_DIR, 'filtered_journals.json')
    xlsx_path = os.path.join(EXPORT_DIR, 'filtered_journals.xlsx')
    write_json(items, json_path)
    write_excel(items, xlsx_path)
    print('JSON 保存至: ' + json_path)
    print('Excel 保存至: ' + xlsx_path)


if __name__ == '__main__':
    main()


