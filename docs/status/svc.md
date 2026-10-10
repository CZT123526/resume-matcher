# status/svc.md — 服务层契约认领与状态表

> 服务层 = `backend/app/svc/` 下的 Python 函数，是 API 层与外部服务(DeepSeek/ChromaDB/模型)之间的唯一通道。
> **认领 = 把负责人改成自己并改状态为"进行中"**；实现完成必须同步本表。
> 状态取值：未开始 ｜ 进行中 ｜ 已完成 ｜ 已验收

| 编号 | 名称 | 说明 | 负责人 | 状态 | 备注 |
|---|---|---|---|---|---|
| S01 | parse_document(file_bytes, filename) -> {text, meta} | PDF/DOCX 提取纯文本；不支持的类型抛 E4002 | 成员B | 未开始 | M01 |
| S02 | extract_entities_llm(text) -> entities_json | DeepSeek 结构化抽取（统一Schema：name/degree/school/skill/years/company/title） | 成员B | 未开始 | M01 |
| S03 | llm_chat(messages, **kwargs) -> str | DeepSeek 统一封装：超时重试3次、结果缓存、限流转 E4291 | 成员B | 未开始 | 全模块基础件，最先做 |
| S04 | build_annotation(raw_text) -> 标注样本 | LLM 弱监督自动标注（产出蒸馏训练语料，目标≥1万条） | 成员A | 未开始 | M02 |
| S05 | train_distill(data_dir) -> {model_path, metrics} | BERT NER 蒸馏训练（Colab执行，产出metrics含F1） | 成员A | 未开始 | M02 |
| S06 | extract_entities_bert(text) -> entities_json | 本地蒸馏模型推理抽取（与S02同Schema，可互换） | 成员A | 未开始 | M02 |
| S07 | embed_texts(texts) -> vectors | BGE 向量化（bge-small-zh） | 成员A | 未开始 | M02/M03 |
| S08 | search_similar(jd_vector, top_k) -> [resume_id] | ChromaDB 向量检索召回 | 成员A | 未开始 | M03 |
| S09 | hard_filter(candidates, jd_reqs) -> filtered | 硬条件过滤（学历/年限），规则实现不走LLM | 成员B | 未开始 | M03 |
| S10 | score_match(jd, candidate) -> {score, evidence} | LLM 逐字段交叉验证打分 + 证据链 | 成员B | 未开始 | M03 |
| S11 | run_match_task(task_id) | 匹配任务编排器（调度Agent）：过滤→检索→打分→写库→更新进度 | 成员B | 未开始 | M03 |
| S12 | generate_report(task_id) -> pdf_path | 汇总结果生成PDF评估报告 | 成员A | 未开始 | M05 |
