#!/usr/bin/env python3
"""
GitHub Actions 爬取脚本 - 改进版
- 增强错误处理和重试机制
- 优化 API 调用频率
"""
import requests, time, json, os, xml.etree.ElementTree as ET
from datetime import datetime

KEYWORDS = ["3dgs", "3D Gaussian Splatting"]
MAX_RESULTS = 300
SS_BATCH = 10  # 减小批次大小
OUT_PATH = os.path.join(os.path.dirname(__file__), "../data/papers.json")


def search_arxiv(query, max_results=300, retry=3):
    url = "http://export.arxiv.org/api/query"
    params = {"search_query": f"all:{query}", "start": 0,
              "max_results": max_results, "sortBy": "submittedDate", "sortOrder": "descending"}
    
    for attempt in range(retry):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(resp.text)
            papers = []
            for entry in root.findall("atom:entry", ns):
                aid = entry.find("atom:id", ns).text.strip().split("/abs/")[-1].split("v")[0]
                title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
                published = entry.find("atom:published", ns).text[:10]
                authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
                summary = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
                papers.append({
                    "arxiv_id": aid, "title": title, "published": published,
                    "year": published[:4],
                    "authors": "; ".join(authors[:5]) + (" et al." if len(authors) > 5 else ""),
                    "abstract": summary,
                    "arxiv_url": f"https://arxiv.org/abs/{aid}",
                })
            return papers
        except Exception as e:
            print(f"  ArXiv 查询失败 (尝试 {attempt+1}/{retry}): {e}")
            if attempt < retry - 1:
                time.sleep(5)
    return []


def get_citations(arxiv_ids, retry=3):
    url = "https://api.semanticscholar.org/graph/v1/paper/batch"
    payload = {"ids": [f"ARXIV:{i}" for i in arxiv_ids]}
    
    for attempt in range(retry):
        try:
            resp = requests.post(url, json=payload,
                                 params={"fields": "citationCount,externalIds"}, timeout=30)
            if resp.status_code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"  SS 限流，等待 {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            resp.raise_for_status()
            data = resp.json()
            result = {}
            for item in data:
                if item:
                    aid = (item.get("externalIds") or {}).get("ArXiv")
                    if aid:
                        result[aid] = item.get("citationCount", 0) or 0
            return result
        except Exception as e:
            print(f"  SS 查询失败 (尝试 {attempt+1}/{retry}): {e}")
            if attempt < retry - 1:
                time.sleep(10)
    return {}


def main():
    all_papers = {}
    for kw in KEYWORDS:
        print(f"搜索: {kw}")
        papers = search_arxiv(kw, MAX_RESULTS)
        for p in papers:
            all_papers[p["arxiv_id"]] = p
        time.sleep(3)  # ArXiv 建议间隔

    ids = list(all_papers.keys())
    print(f"去重后 {len(ids)} 篇，查询引用量...")
    citation_map = {}
    for i in range(0, len(ids), SS_BATCH):
        batch = ids[i:i+SS_BATCH]
        batch_citations = get_citations(batch)
        citation_map.update(batch_citations)
        time.sleep(2)  # 增加间隔
        print(f"  {min(i+SS_BATCH, len(ids))}/{len(ids)}")

    for aid, p in all_papers.items():
        p["citations"] = citation_map.get(aid, 0)

    papers_list = sorted(all_papers.values(), key=lambda x: x["citations"], reverse=True)

    output = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(papers_list),
        "papers": papers_list
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"完成！共 {len(papers_list)} 篇 → {OUT_PATH}")


if __name__ == "__main__":
    main()
