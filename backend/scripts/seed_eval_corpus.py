"""评测语料生成：向当前业务库灌入 17 份简历 + 8 个岗位 JD（可重复执行，按文件名/标题幂等）。

用途：给 M04 三组对比实验一份有区分度的演示语料（8 个 JD 查询 ≥5、每 JD 2 正例，
覆盖 后端/前端/数据/设计/测试/运维/算法/产品 八类岗位）。
用法：backend 目录下  python scripts/seed_eval_corpus.py
"""
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app

RESUMES = [
    # (文件名, [简历行]) —— 行文走规则抽取认得的显式字段格式
    ("resume_zhangwei.docx", ["姓名：张伟", "硕士", "5年工作经验",
                              "技能：Python FastAPI MySQL Redis Docker", "担任后端开发工程师", "任职于字节跳动科技有限公司"]),
    ("resume_lina.docx", ["姓名：李娜", "本科", "4年工作经验",
                          "技能：Python Django PostgreSQL Nginx", "担任后端开发工程师", "任职于美团科技有限公司"]),
    ("resume_wangqiang.docx", ["姓名：王强", "大专", "3年工作经验",
                               "技能：Java Spring MySQL Kafka", "担任Java开发工程师", "任职于东软集团股份有限公司"]),
    ("resume_zhaomin.docx", ["姓名：赵敏", "本科", "3年工作经验",
                             "技能：JavaScript React Vue Webpack", "担任前端开发工程师", "任职于腾讯科技有限公司"]),
    ("resume_sunli.docx", ["姓名：孙丽", "本科", "2年工作经验",
                           "技能：HTML CSS JavaScript Vite", "担任前端开发工程师", "任职于小米科技有限公司"]),
    ("resume_zhoujie.docx", ["姓名：周杰", "硕士", "6年工作经验",
                             "技能：Python SQL Tableau Pandas 机器学习", "担任数据分析师", "任职于招商银行"]),
    ("resume_wujing.docx", ["姓名：吴静", "本科", "3年工作经验",
                            "技能：Excel SQL Python 数据分析", "担任数据分析师", "任职于京东科技有限公司"]),
    ("resume_zhengshuang.docx", ["姓名：郑爽", "大专", "2年工作经验",
                                 "技能：Photoshop Illustrator CorelDRAW", "担任平面设计师", "任职于奥美广告有限公司"]),
    ("resume_fenggang.docx", ["姓名：冯刚", "本科", "1年工作经验",
                              "技能：Photoshop Sketch Figma", "担任UI设计师", "任职于字节跳动科技有限公司"]),
    ("resume_gaoxiang.docx", ["姓名：高翔", "本科", "4年工作经验",
                              "技能：Selenium JUnit Python Postman", "担任测试开发工程师", "任职于华为技术有限公司"]),
    ("resume_luomin.docx", ["姓名：罗敏", "大专", "2年工作经验",
                            "技能：Jmeter LoadRunner Python Appium", "担任测试工程师", "任职于中兴通讯股份有限公司"]),
    ("resume_hanlei.docx", ["姓名：韩磊", "本科", "5年工作经验",
                            "技能：Linux Docker Kubernetes Shell Prometheus", "担任运维工程师", "任职于阿里云计算有限公司"]),
    ("resume_songjie.docx", ["姓名：宋洁", "大专", "3年工作经验",
                             "技能：Linux Nginx Zabbix Shell Kafka", "担任运维工程师", "任职于用友网络科技股份有限公司"]),
    ("resume_linhao.docx", ["姓名：林浩", "硕士", "3年工作经验",
                            "技能：Python PyTorch 机器学习 深度学习 C++", "担任算法工程师", "任职于旷视科技有限公司"]),
    ("resume_xulei.docx", ["姓名：徐蕾", "硕士", "5年工作经验",
                           "技能：Python TensorFlow 推荐系统 NLP", "担任算法研究员", "任职于字节跳动科技有限公司"]),
    ("resume_hechen.docx", ["姓名：何晨", "本科", "4年工作经验",
                            "技能：Axure SQL PRD 需求分析", "担任产品经理", "任职于腾讯科技有限公司"]),
    ("resume_tangyue.docx", ["姓名：唐悦", "本科", "2年工作经验",
                             "技能：Axure Xmind 竞品分析 用户调研", "担任产品助理", "任职于京东科技有限公司"]),
]

JDS = [
    ("Python后端工程师", "负责后端服务设计与开发。要求：3年以上Python经验，熟悉FastAPI与MySQL，本科及以上，有Docker经验优先。"),
    ("前端开发工程师", "负责Web前端页面开发。要求：2年以上经验，熟悉React或Vue，本科及以上。"),
    ("数据分析师", "负责业务数据分析与报表。要求：熟悉SQL与Python，硕士优先。"),
    ("平面设计师", "负责品牌与运营视觉设计。要求：精通Photoshop与Illustrator，大专及以上。"),
    ("测试工程师", "负责功能与自动化测试。要求：2年以上经验，熟悉Selenium或Jmeter，掌握Python，本科及以上。"),
    ("运维工程师", "负责线上服务稳定与部署。要求：3年以上经验，熟悉Linux与Docker，本科及以上。"),
    ("算法工程师", "负责机器学习算法研发与落地。要求：硕士及以上，熟悉PyTorch，有NLP或推荐系统经验优先。"),
    ("产品经理", "负责产品规划与需求管理。要求：3年以上经验，熟悉需求分析方法，本科及以上。"),
]


def make_docx(lines: list[str]) -> bytes:
    import docx

    buf = BytesIO()
    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    d.save(buf)
    return buf.getvalue()


def main() -> int:
    client = TestClient(app)

    existing = {
        r["file_name"]: r["resume_id"]
        for r in client.get("/api/resumes?page=1&page_size=100").json()["data"]["items"]
    }
    jd_titles = {
        j["title"]
        for j in client.get("/api/jds?page=1&page_size=100").json()["data"]["items"]
    }

    for fname, lines in RESUMES:
        if fname in existing:
            print(f"[跳过] {fname} 已存在")
            continue
        r = client.post(
            "/api/resumes/upload",
            files={"file": (fname, make_docx(lines), "application/octet-stream")},
        )
        assert r.status_code == 202, r.text
        rid = r.json()["data"]["resume_id"]
        st = client.get(f"/api/resumes/{rid}").json()["data"]["parse_status"]
        assert st == "done", f"{fname} 解析状态 {st}"
        print(f"[简历] {fname} -> id={rid}")

    for title, content in JDS:
        if title in jd_titles:
            print(f"[跳过] JD《{title}》已存在")
            continue
        r = client.post("/api/jds", json={"title": title, "content": content})
        assert r.status_code == 200, r.text
        print(f"[JD] {title} -> id={r.json()['data']['jd_id']}")

    print("\n语料就绪。下一步：\n"
          "  python tools/eval/build_gold.py\n"
          "  python tools/run_experiments.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
