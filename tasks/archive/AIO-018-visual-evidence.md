# AIO-18 visual evidence

This index preserves the browser evidence for AIO-18, “Plane 未完成工单面板与 Prompt 解析生成”. It records visual states only; it does not replace the deterministic tests or a structured QA verdict.

All screenshots were captured at 962 px wide during the AIO-18 verification run and were moved from the local `.qa-tmp/aio18-visual/` sandbox on 2026-07-31. SHA-256 values bind this index to the archived assets.

| Evidence | UI state shown | SHA-256 |
| --- | --- | --- |
| `AIO-018-screenshot-ticket-list.png` | Ticket list | `88e834a4df2fb15de8a2e4fcdb2276fcceba4ad3f655e9e217447750cfcab4f9` |
| `AIO-018-screenshot-detail-existing-source.png` | Ticket detail with an existing prompt source | `9ef0d9fc1a44818c979c0e0f7ed9793e89ae81fc7d42fec236003448a1a5170a` |
| `AIO-018-screenshot-ineligible-disabled.png` | Ineligible ticket control is disabled | `52dc1a62f2b31be6ea959981fab6ba274226da70c802f428c18707c2389e7da7` |
| `AIO-018-screenshot-planner-hard-break.png` | Planner Hard Break state | `7eced46a4213629dd0da01f62f5a4d796bdf847b42e0f5d5739fca8d01976ae3` |
| `AIO-018-screenshot-settings-masked.png` | Settings view with masked values | `52dc1a62f2b31be6ea959981fab6ba274226da70c802f428c18707c2389e7da7` |

The one-off `qa_aio18_probe.py` remains local and ignored. If a probe becomes regression coverage, promote it to a named test under `tests/` rather than archiving the ad-hoc script.
