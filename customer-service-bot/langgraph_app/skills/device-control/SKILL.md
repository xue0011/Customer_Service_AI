---
name: device-control
description: 智能家居设备控制：灯光、空气净化器、插座、回家/离家场景（经 MCP Server 执行）
triggers: 灯,亮度,色温,空调,净化器,插座,设备,智能家居,回家模式,离家模式
---

# 设备控制 Skill

## 能力来源
所有设备操作都通过 MCP Server（device-control）暴露的工具完成，
本 Skill 只规定「怎么问、怎么确认、怎么兜底」。

## 流程
1. 确认设备：顾客说「客厅的灯」→ 用 list_devices 找到 device_id；
   多个候选时反问一句，不要猜。
2. 确认参数：亮度 1–100、色温 1700–6500K、净化器模式 auto/silent/favorite。
3. 执行：调用对应工具（set_power / set_brightness / set_color_temp / set_purifier_mode）。
4. 回读：执行后用 get_device_status 确认结果，再向顾客确认「已经调到 30%」。
5. 失败：设备离线 → 告知检查网络/电源，不要重复重试超过 2 次。

## 安全边界
- 只允许操作 devices.json 白名单内的设备。
- 不执行未声明的动作（如重启网关、恢复出厂设置）。
- 顾客要求「关掉所有设备」时，逐台确认或要求二次确认后再执行。
