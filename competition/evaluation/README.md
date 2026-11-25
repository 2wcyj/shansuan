# 评测数据集目录

本目录用于存放可公开的评测样本与原始结果。**当前没有样本**，也未产生任何实测指标。

## 目录约定

```text
competition/evaluation/
  README.md
  cases/            输入样本（合成画像、合法公开图片、冻结候选集）
  results/          原始结果（JSON/CSV）与运行日志
```

## 样本要求

- 画像：合成，不含真实姓名、联系方式、身份证号
- 图片：来源可追溯、许可允许再分发；不得使用未授权包装图
- 产品候选集：冻结版本 + 版本号，标注核实状态
- 体征：仅合成值

## 结果格式

每份结果文件必须带：

```json
{
  "software_commit": "40 位哈希",
  "model": "模型名与版本",
  "prompt_version": "字符串",
  "rules_version": "字符串",
  "hardware": "CPU/内存/OS",
  "date": "YYYY-MM-DD",
  "dataset": "cases 文件路径",
  "samples": 0,
  "metrics": {},
  "failures": [],
  "limitations": []
}
```

## 禁止

- 把目标值写成实测
- 用合成数据声称真实用户长期使用
- 删除失败样本只保留成功样本