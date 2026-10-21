"""对比学习微调（T36 B2）：简历-岗位双塔语义对齐，CPU 本机训练。

思路（算法设计 §8 改进路线②）：文件名角色 = 免费标签（姓名_角色.docx），每份简历
与"其角色的训练用 JD 描述"构成正对；批内其余样本为负样本（MultipleNegativesRanking
思路）。两个关键防泄漏/防退化设计：
1. 训练用 JD 为 35 个角色各写一段独立描述（ROLE_JDS），与库内 55 条评测 JD 无文案
   复制关系——模型在训练中从未见过评测 JD 原文；
2. 每个批次内角色互不重复（35 角色 > batch 32 取 32 个不同角色），避免"同角色
   不同简历"被当成假负例污染损失。

实现约束：本机被 sentence-transformers 弄坏过环境——用原生 transformers 手写损失；
mean pooling 与线上一致；起点为领域继续预训练模型 models/bert_domain（消融链：
底座 → DAPT → 对比微调）。

用法：cd backend && python -X utf8 tools/train_contrastive.py [--epochs 4] [--batch 32]
输出：models/bert_pair/（含 metrics.json：训练配置与 dev Recall@1 前后对比）
"""
import argparse
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

import torch
import torch.nn.functional as F
from torch import Tensor
from transformers import AutoModel, AutoTokenizer

# 35 个角色的训练用 JD 描述（独立撰写，非评测 JD 文案；词汇取自行业通用表述）
ROLE_JDS = {
    "Java后端开发工程师": "负责Java后端服务开发，使用SpringBoot搭建微服务，处理高并发、分布式事务与消息队列，保障系统稳定性",
    "Python后端开发工程师": "负责Python后端开发，基于Django或FastAPI构建Web服务与接口，涉及数据库设计与性能优化",
    "前端开发工程师": "负责Web前端开发，使用Vue或React构建页面与组件，关注交互体验、性能与工程化",
    ".NET开发工程师": "负责基于C#与.NET平台的桌面及工控软件研发，涉及WinForm、WPF与上位机开发",
    "C++开发工程师": "负责C++服务端或客户端研发，涉及高性能计算、图形图像处理与跨平台开发",
    "嵌入式软件工程师": "负责嵌入式软件开发，基于STM32等单片机进行固件开发、驱动调试与串口通信",
    "算法工程师": "负责机器学习与深度学习算法研发，包括模型训练、调优与落地部署，使用Python与PyTorch",
    "大数据开发工程师": "负责大数据平台开发，基于Hadoop、Spark、Hive进行数据仓库建设与离线实时计算",
    "数据分析师": "负责业务数据分析，使用SQL与Python取数建模，制作报表与数据看板，输出分析结论支持决策",
    "测试开发工程师": "负责软件测试与测试工具开发，编写自动化测试脚本，设计用例并跟进缺陷闭环",
    "运维工程师": "负责服务器运维与持续集成部署，使用Linux、Shell与监控体系保障线上服务可用性",
    "信息安全工程师": "负责网络安全与渗透测试，漏洞扫描与修复加固，制定安全规范并应急响应",
    "产品经理": "负责产品规划与需求分析，撰写PRD，跟进设计开发上线全流程，基于数据迭代功能",
    "UI设计师": "负责产品界面与视觉设计，使用PS、Figma产出界面稿与设计规范，配合前端还原",
    "新媒体运营": "负责公众号、抖音、小红书等新媒体账号的内容策划与粉丝增长，跟进热点产出图文与短视频",
    "电商运营": "负责电商店铺运营，含商品上架、活动策划、付费推广与数据分析，提升流量转化与销售额",
    "外贸业务员": "负责海外客户开发与维护，处理询盘报价与订单全流程，通过邮件与展会与外商沟通",
    "市场营销专员": "负责市场推广活动策划与执行，品牌宣传、渠道拓展与推广效果数据分析",
    "客服主管": "负责客服团队管理与排班培训，处理升级投诉，制定质检标准并跟踪服务指标",
    "人力资源专员": "负责招聘、员工关系、考勤社保等人事工作，发布职位、筛选简历与组织面试",
    "会计": "负责账务处理与报表编制，税务申报、成本核算与往来对账，确保凭证合规",
    "法务专员": "负责合同起草审查、合规咨询与纠纷处理，输出法律意见并维护合同模板",
    "行政专员": "负责办公室日常行政事务，固定资产管理、会议组织、接待与后勤保障",
    "供应链专员": "负责供应链计划与物流协调，管理库存与交期，优化采购到交付全链路",
    "采购专员": "负责供应商询价比价议价与订单执行，开发考核供应商，推动降本与供应保障",
    "金融风控专员": "负责信贷风控策略监控与迭代，基于SQL与Python进行客群分析、规则挖掘与资产质量跟踪",
    "护士": "负责病区患者临床护理，执行医嘱、输液注射与生命体征监测，配合抢救并书写护理记录",
    "医药代表": "负责辖区医院的产品学术推广与客户维护，组织科室会议，完成拜访与销售指标",
    "数学教师": "负责初中数学课程教学，备课授课、批改作业与学情辅导，参与教研并与家长沟通",
    "施工员": "负责施工现场测量放线、进度协调与质量安全管理，填写施工日志并配合监理验收",
    "机械工程师": "负责机械结构设计与非标设备研发，使用SolidWorks、AutoCAD出图，跟进装配调试与工艺对接",
    "电气工程师": "负责电气图纸设计与PLC程序开发，完成控制柜设计与现场调试，熟悉EPLAN与低压元器件选型",
    "游戏策划": "负责游戏玩法与活动系统设计，搭建数值配置表，拆解竞品并跟进版本落地",
    "视频剪辑师": "负责短视频与宣传片的剪辑包装，使用Premiere、AE、剪映产出成片，把控节奏与完播率",
    "翻译": "负责中外文笔译与审校，使用Trados等CAT工具维护术语库，保证译文质量与交付准时",
}

_ROLE_RE = re.compile(r"^[^_]+_(.+)\.(pdf|docx)$")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_pairs() -> tuple[list[tuple[str, str]], list[int]]:
    """（简历结构化文本, 角色训练JD）正对；仅收文件名可判角色的 done 简历（免费标签）。

    B8 挑刺修复：返回 (pairs, rids)——rid 清单随模型落 manifest，训练池从此可核对。
    """
    from app.svc.vectors import _current_resume_data, structured_text

    data = _current_resume_data()
    conn = None
    from app.db import get_db

    conn = get_db()
    try:
        files = {r["id"]: r["file_name"] for r in conn.execute("SELECT id, file_name FROM resumes")}
    finally:
        conn.close()

    pairs, rids, skipped = [], [], 0
    for rid, item in data.items():
        m = _ROLE_RE.match(files.get(rid, ""))
        role = m.group(1) if m else None
        if role not in ROLE_JDS:
            skipped += 1
            continue
        pairs.append((structured_text(item), ROLE_JDS[role]))
        rids.append(rid)
    log(f"训练正对 {len(pairs)} 条（非角色简历跳过 {skipped}）")
    return pairs, rids


MANIFEST_NAME = "train_manifest.json"


def check_pool_manifest(out_dir: Path, n_pairs: int) -> None:
    """训练前核对训练池是否相对上次训练发生漂移（B8 挑刺修复）。

    load_pairs 从全库现抽正对，语料增长会静默改变训练数据（实测 978→1322 对，
    压力/半规范考卷简历混入）。与 manifest 记录不一致时打醒目警告：不阻断
    （语料增长后重训本身合法），但重训后再跑 stress/semispec 考卷评测，
    "考卷生成晚于训练=跨语料泛化" 的前提即告失效，必须重新核对结论口径。
    """
    mf = out_dir / MANIFEST_NAME
    if not mf.exists():
        log(f"⚠ {out_dir / MANIFEST_NAME} 不存在，无法核对训练池漂移（首次训练可忽略）")
        return
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"⚠ train_manifest.json 读取失败（{exc}），跳过核对")
        return
    old_n = man.get("pair_count")
    if old_n != n_pairs:
        log("⚠⚠ 训练池漂移：本次抽到 "
            f"{n_pairs} 对，上次训练（{man.get('trained_at', '?')}）为 {old_n} 对。"
            "若重训后重跑 stress/semispec/fresh 考卷评测，'模型未见过考卷'的前提不再成立，"
            "相关'跨语料泛化'结论需重新核对口径！")
    else:
        log(f"训练池核对一致：{n_pairs} 对（与 {man.get('trained_at', '?')} 的记录相同）")


def write_pool_manifest(out_dir: Path, rids: list[int], n_pairs: int) -> None:
    """训练完成后落训练池 manifest（B8）：对数 + rid 清单，供下次重训前核对。"""
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps({
            "pair_count": n_pairs,
            "resume_ids": sorted(rids),
            "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "load_pairs 从全库现抽；重训前 check_pool_manifest 会比对对数防静默漂移",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mean_pool(last_hidden: Tensor, mask: Tensor) -> Tensor:
    mask = mask.unsqueeze(-1).float()
    return (last_hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)


@torch.no_grad()
def encode_all(model, tok, texts: list[str], device, batch: int = 16, max_len: int = 256) -> Tensor:
    model.eval()
    out = []
    for i in range(0, len(texts), batch):
        enc = tok(texts[i : i + batch], padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(device)
        out.append(mean_pool(model(**enc).last_hidden_state, enc["attention_mask"]))
    return F.normalize(torch.cat(out), dim=-1)


@torch.no_grad()
def dev_recall(model, tok, pairs: list[tuple[str, str]], device, max_len: int) -> float:
    """dev 集：简历向量在其角色 JD vs 全部 35 角色 JD 中排第一的比例"""
    roles = list(ROLE_JDS.values())
    jd_vec = encode_all(model, tok, roles, device, max_len=max_len)
    resume_vec = encode_all(model, tok, [p[0] for p in pairs], device, max_len=max_len)
    sims = resume_vec @ jd_vec.T
    hit = (sims.argmax(dim=1) == Tensor([roles.index(p[1]) for p in pairs]).long()).float().mean()
    return float(hit)


def train_contrastive(model, tok, train_pairs, *, epochs, batch, lr, temp, max_len, seed, device="cpu", eval_fn=None):
    """批内角色互不重复的对比训练主循环（入口 main 与留出法补验脚本共用）。

    每批从不同角色各抽 1 份简历（35 角色 > batch），批内其余样本即真负例；
    某角色队列耗尽后回填重采样，等价多轮 epoch。eval_fn 提供时每个 epoch 末调用一次。
    """
    by_role: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for p in train_pairs:
        by_role[p[1]].append(p)
    rng = random.Random(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    model.train()

    def make_batches() -> list[list[tuple[str, str]]]:
        queues = {r: rng.sample(v, len(v)) for r, v in by_role.items()}
        roles = list(by_role)
        batches = []
        n_batches = (len(train_pairs) + batch - 1) // batch
        for _ in range(n_batches):
            pick = rng.sample(roles, min(batch, len(roles)))
            b = []
            for r in pick:
                q = queues[r]
                if not q:
                    queues[r] = rng.sample(by_role[r], len(by_role[r]))
                    q = queues[r]
                b.append(q.pop())
            batches.append(b)
        return batches

    for epoch in range(1, epochs + 1):
        batches = make_batches()
        rng.shuffle(batches)
        t0, total_loss = time.time(), 0.0
        for bi, b in enumerate(batches, 1):
            enc_r = tok([p[0] for p in b], padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(device)
            enc_j = tok([p[1] for p in b], padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(device)
            vr = F.normalize(mean_pool(model(**enc_r).last_hidden_state, enc_r["attention_mask"]), dim=-1)
            vj = F.normalize(mean_pool(model(**enc_j).last_hidden_state, enc_j["attention_mask"]), dim=-1)
            labels = torch.arange(len(b))
            loss = 0.5 * (
                F.cross_entropy(vr @ vj.T / temp, labels) + F.cross_entropy(vj @ vr.T / temp, labels)
            )
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += float(loss)
            if bi % 5 == 0 or bi == len(batches):
                log(f"epoch {epoch} batch {bi}/{len(batches)} loss={total_loss / bi:.4f} ({time.time() - t0:.0f}s)")
        if eval_fn is not None:
            log(f"epoch {epoch} dev指标 = {eval_fn():.4f}")
    return model


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="models/bert_domain")
    ap.add_argument("--out", default="models/bert_pair")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--temp", type=float, default=0.05)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--dev-ratio", type=float, default=0.08)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = "cpu"

    pairs, rids = load_pairs()
    check_pool_manifest(Path(args.out), len(pairs))
    rng = random.Random(args.seed)
    idx = list(range(len(pairs)))
    rng.shuffle(idx)
    n_dev = max(8, int(len(pairs) * args.dev_ratio))
    dev_idx = set(idx[:n_dev])
    train = [pairs[i] for i in idx[n_dev:]]
    dev = [pairs[i] for i in sorted(dev_idx)]
    log(f"训练 {len(train)} / 开发 {len(dev)}（dev 仅评测，不参与训练）")

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModel.from_pretrained(args.base)

    base_recall = dev_recall(model, tok, dev, device, args.max_len)
    log(f"微调前 dev Recall@1（35 角色检索）= {base_recall:.4f}")

    model = train_contrastive(
        model, tok, train,
        epochs=args.epochs, batch=args.batch, lr=args.lr, temp=args.temp,
        max_len=args.max_len, seed=args.seed, device=device,
        eval_fn=lambda: dev_recall(model, tok, dev, device, args.max_len),
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    final_recall = dev_recall(model, tok, dev, device, args.max_len)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    metrics = {
        "encoder_id": "bert_pair-contrastive",
        "base_model": args.base,
        "train_pairs": len(train),
        "dev_size": len(dev),
        "epochs": args.epochs,
        "batch": args.batch,
        "lr": args.lr,
        "temperature": args.temp,
        "max_len": args.max_len,
        "seed": args.seed,
        "dev_recall_at1_base": round(base_recall, 4),
        "dev_recall_at1_finetuned": round(final_recall, 4),
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "批内负样本；批内角色互不重复防假负例；训练JD为35角色独立撰写，未复制评测JD文案",
    }
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    write_pool_manifest(out, rids, len(pairs))
    log(f"完成：dev Recall@1 {base_recall:.4f} → {final_recall:.4f}，模型已存 {out}/（含训练池 manifest）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
