# status/svc.md — 服务层契约认领与状态表

> 服务层 = `backend/app/svc/` 下的 Python 函数，是 API 层与本地模型/数据之间的唯一通道。
> **签名契约已落成代码**：`backend/app/svc/contracts.py`（S01–S11 签名与异常约定）——认领后把函数移入实现文件补全，禁止改签名。
> **认领 = 把负责人改成自己并改状态为"进行中"**；实现完成必须同步本表。
> 状态取值：未开始 ｜ 进行中 ｜ 已完成 ｜ 已验收

| 编号 | 名称 | 说明 | 负责人 | 状态 | 备注 |
|---|---|---|---|---|---|
| S01 | parse_document(file_bytes, filename) -> {"text": str} | PDF/DOCX 提取纯文本；不支持的类型抛 E4002 | 成员A | 已完成 | `744d0dd`；pypdf+python-docx(含表格)，扫描件E4001可读提示 |
| S02 | extract_entities_bert(text) -> list[{field_key, field_value, source}] | 本地BERT NER推理（7类实体见算法设计§1），运行时唯一抽取来源 | 成员A | 已完成 | `744d0dd` 调度层+规则兜底；`32901d8` 字段级合并(模型无标签字段由规则补) |
| S03 | train_ner(data_dir, output_dir) -> {f1, precision, recall} | NER微调：简历领域标注集(主)+CLUENER(辅)，Colab执行 | 成员A | 进行中 | `32901d8` 物料全就绪(数据集管道实跑通过+训练脚本+指标)；训练执行待Colab(待拍板#2) |
| S04 | build_jd_requirements(jd_text) -> {degree, min_years, skills} | 规则+NER 抽取JD结构化要求（学历/年限/技能列表） | 成员B | 已完成 | `2698613`；区间取下限/中文数字/展示大小写 |
| S05 | embed_texts(texts) -> np.ndarray(归一化) | BERT 语义编码（JD与简历文本向量化，批量CPU推理） | 成员B | 已完成 | `2698613`；svc/embedding.py get_encoder，BERT主路+TF-IDF降级 |
| S06 | cosine_rank(jd_vector, top_k) -> [{resume_id, score}] | numpy 矩阵余弦相似度排名，score∈0~1 降序（读 vectors.npy 缓存） | 成员B | 已完成 | `2698613`；score=(1+cos)/2 四位小数 |
| S07 | compute_evidence(jd_reqs, resume_entities) -> list[str] | 证据链生成：技能重叠/学历/年限逐项比对（文案见算法设计§4），只解释不改分 | 成员B | 已完成 | `2698613`；显式学历高低映射(修严重bug后定稿) |
| S08 | tfidf_baseline(jd_text, resume_texts) -> list[float] | 对照组一：TF-IDF+余弦 关键词基线 | 成员A | 已完成 | `a73572d`；实际入口 tools/baselines/tfidf_baseline.rank_for_jds，文本构造复用主系统 |
| S09 | deepseek_zeroshot(jd_text, resume_text) -> {score, reason} | 对照组二：DeepSeek零样本匹配（仅tools/离线脚本，禁入app/） | 成员A | 已完成 | `a73572d`；DeepSeekScorer，3次退避重试+jsonl缓存，无key干净跳过 |
| S10 | evaluate(run_files, gold_file) -> {ndcg@10, f1, latency_p95_ms, ...} | 统一计算 P/R/F1、NDCG@K、延迟、成本，图表入 docs/eval/ | 成员A+成员B | 已完成 | `a73572d`；实际入口 tools/run_experiments.py，指标NDCG@10/P@5+排序耗时 |
| S11 | generate_report(task_id) -> BinaryIO(PDF流) | 汇总结果生成PDF评估报告，api层以application/pdf响应返回 | 成员A | 已完成 | `1e3f055`；内嵌系统TrueType中文字体(CID渲染空白已修) |
