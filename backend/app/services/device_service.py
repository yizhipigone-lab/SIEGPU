"""设备服务 facade（2026-08-27 架构拆分 #3）。

实现已拆到四个内聚模块，本文件只做再导出，保持既有导入面零改动：

- ``device_crud``          设备档案 CRUD + SN 生成 + 库存看板 + Excel 批量导入
- ``device_asset_sync``    上架建卡 / 点亮激活 / 表外备查台账（D1 两段式资产生命周期）
- ``device_stage_machine`` 设备 7 节点状态机（懒初始化、物化列派生、硬流转守门）
- ``device_batch``         批次挂载/移出/批量推进 + 批次状态聚合 + 金租放款联动

模块间依赖方向：crud ← asset_sync ← stage_machine → batch（batch 顶层引 stage_machine，
stage_machine 函数级延迟引 batch，避免环——与 audit_service/insurance_service 同模式）。
"""
# ruff: noqa: F401  本文件刻意再导出
from app.services.device_asset_sync import (
    _activate_asset_for_device,
    _create_asset_card_for_device,
    _ensure_off_balance_for_device,
    _OFF_BALANCE_REGISTER_TYPE,
    _sync_device_asset,
    create_off_balance_register,
    list_off_balance_registers,
)
from app.services.device_batch import (
    _active_batch_row,
    _aggregate_batch_status,
    _batch_light_completion,
    _ensure_disbursement_leasing_process,
    _maybe_trigger_disbursement_todo,
    _resolve_project_leasing_supplier,
    _sync_batch_status,
    add_to_batch,
    advance_batch_stages,
    assert_legacy_path,
    DEVICE_FLOW_TYPES,
    EARLY_STAGES,
    list_batch_devices,
    remove_from_batch,
    resolve_flow_type,
)
from app.services.device_crud import (
    create_device,
    delete_device,
    generate_sn,
    get_device_or_404,
    IMPORT_COLS,
    import_devices,
    inventory_summary,
    list_devices,
    PRE_LIT_STAGES,
    update_device,
)
from app.services.device_stage_machine import (
    _assert_light_rework_safe,
    _assert_purchase_accepted,
    _derive_device_status,
    _ensure_device_stages,
    advance_device_stage,
    complete_device_stage,
    DEVICE_STAGE_TRANSITIONS,
    DEVICE_STAGES,
    init_device_stages,
    list_device_stages,
)
