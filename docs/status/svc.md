# status/svc.md — 服务层契约认领与状态表

> 服务层 = `backend/app/svc/` 下的 Python 函数，是 API 层与本地模型/数据之间的唯一通道。
> **签名契约已落成代码**：`backend/app/svc/contracts.py`（S01–S11 签名与异常约定）——认领后把函数移入实现文件补全，禁止改签名。
> **认领 = 把负责人改成自己并改状态为"进行中"**；实现完成必须同步本表。
> 状态取值：未开始 ｜ 进行中 ｜ 已完成 ｜ 已验收

| 编号 | 名称 | 说明 | 负责人 | 状态 | 备注 |
|---|---|---|---|---|---|
| S01 | parse_document(file_bytes, filename) -> {text, meta} | PDF/DOCX 提取纯文本；不支持的类型抛 E4002 | 成员A | 未开始 | M01 |
| S02 | extract_entities_bert(text) -> entities_json | 本地BERT NER推理（name/degree/school/skill/years/company/title），运行时唯一抽取来源 | 成员A | 未开始 | M01 |
| S03 | train_ner(data_dir) -> {model_path, metrics} | NER微调：简历领域标注集(主)+CLUENER(辅)，Colab执行，产出F1 | 成员A | 未开始 | M01 |
| S04 | build_jd_requirements(jd_text) -> req_json | 规则+NER 抽取JD结构化要求（学历/年限/技能列表） | 成员B | 未开始 | M02 |
| S05 | embed_texts(texts) -> vectors | BERT 语义编码（JD与简历文本向量化） | 成员B | 未开始 | M02 |
| S06 | cosine_rank(jd_vector, top_k) -> [resume_id] | numpy 矩阵余弦相似度排名（读 vectors.npy 缓存） | 成员B | 未开始 | M02 |
| S07 | compute_evidence(jd_reqs, resume_entities) -> evidence[] | 证据链生成：技能重叠/学历/年限逐项比对，可解释可复核 | 成员B | 未开始 | M02 |
| S08 | tfidf_baseline(jd, resumes) -> ranking | 对照组一：TF-IDF+余弦 关键词基线 | 成员A | 未开始 | M04 |
| S09 | deepseek_zeroshot(jd, resume) -> score | 对照组二：DeepSeek零样本匹配（仅tools/离线脚本，禁入app/） | 成员A | 未开始 | M04 |
| S10 | evaluate(run_files, gold_file) -> metrics + 图表 | 统一计算 P/R/F1、NDCG@K、延迟、成本，产出对比表与图 | 成员A+成员B | 未开始 | M04 |
| S11 | generate_report(task_id) -> pdf_path | 汇总结果生成PDF评估报告 | 成员A | 未开始 | M05 |
