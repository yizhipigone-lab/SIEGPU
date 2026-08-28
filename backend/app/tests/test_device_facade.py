"""架构拆分 + meta 常量端点的红绿契约测试（2026-08-27 架构报告 #3/#5）。

两组断言：
1. facade 契约：device_service 拆分后，外部使用的全部名字仍可访问，
   且与新模块是同一对象（不是残影拷贝）。
2. meta_service.get_constants：/api/meta/constants 的服务层真源，
   返回 DEVICE_STAGES / POOL_LABELS / STEP_HINTS 三组常量且与既有真源一致。
"""


def test_device_service_facade_reexports_all_external_names():
    """facade 契约：全部再导出名字（含私有辅助与常量）指向新模块的同一对象。

    覆盖面 = 四个新模块的全部公共面 + 测试在用的私有名，防后续删减漏网。
    """
    from app.services import device_service
    from app.services import device_asset_sync, device_batch, device_crud, device_stage_machine

    expected = {
        # device_crud（10）
        "generate_sn": device_crud.generate_sn,
        "create_device": device_crud.create_device,
        "list_devices": device_crud.list_devices,
        "inventory_summary": device_crud.inventory_summary,
        "get_device_or_404": device_crud.get_device_or_404,
        "update_device": device_crud.update_device,
        "delete_device": device_crud.delete_device,
        "import_devices": device_crud.import_devices,
        "IMPORT_COLS": device_crud.IMPORT_COLS,
        "PRE_LIT_STAGES": device_crud.PRE_LIT_STAGES,
        # device_batch（15）
        "add_to_batch": device_batch.add_to_batch,
        "remove_from_batch": device_batch.remove_from_batch,
        "list_batch_devices": device_batch.list_batch_devices,
        "advance_batch_stages": device_batch.advance_batch_stages,
        "resolve_flow_type": device_batch.resolve_flow_type,
        "assert_legacy_path": device_batch.assert_legacy_path,
        "EARLY_STAGES": device_batch.EARLY_STAGES,
        "DEVICE_FLOW_TYPES": device_batch.DEVICE_FLOW_TYPES,
        "_active_batch_row": device_batch._active_batch_row,
        "_aggregate_batch_status": device_batch._aggregate_batch_status,
        "_sync_batch_status": device_batch._sync_batch_status,
        "_batch_light_completion": device_batch._batch_light_completion,
        "_resolve_project_leasing_supplier": device_batch._resolve_project_leasing_supplier,
        "_ensure_disbursement_leasing_process": device_batch._ensure_disbursement_leasing_process,
        "_maybe_trigger_disbursement_todo": device_batch._maybe_trigger_disbursement_todo,
        # device_stage_machine（10）
        "DEVICE_STAGES": device_stage_machine.DEVICE_STAGES,
        "DEVICE_STAGE_TRANSITIONS": device_stage_machine.DEVICE_STAGE_TRANSITIONS,
        "list_device_stages": device_stage_machine.list_device_stages,
        "init_device_stages": device_stage_machine.init_device_stages,
        "advance_device_stage": device_stage_machine.advance_device_stage,
        "complete_device_stage": device_stage_machine.complete_device_stage,
        "_derive_device_status": device_stage_machine._derive_device_status,
        "_ensure_device_stages": device_stage_machine._ensure_device_stages,
        "_assert_light_rework_safe": device_stage_machine._assert_light_rework_safe,
        "_assert_purchase_accepted": device_stage_machine._assert_purchase_accepted,
        # device_asset_sync（7）
        "create_off_balance_register": device_asset_sync.create_off_balance_register,
        "list_off_balance_registers": device_asset_sync.list_off_balance_registers,
        "_OFF_BALANCE_REGISTER_TYPE": device_asset_sync._OFF_BALANCE_REGISTER_TYPE,
        "_ensure_off_balance_for_device": device_asset_sync._ensure_off_balance_for_device,
        "_create_asset_card_for_device": device_asset_sync._create_asset_card_for_device,
        "_activate_asset_for_device": device_asset_sync._activate_asset_for_device,
        "_sync_device_asset": device_asset_sync._sync_device_asset,
    }
    for name, obj in expected.items():
        assert getattr(device_service, name) is obj, f"facade 漏导出或残影拷贝: {name}"


def test_acceptance_shipped_stages_derive_from_device_stages():
    """_SHIPPED_STAGES 必须由 DEVICE_STAGES 派生（在途起），不再是手工拷贝。"""
    from app.services import acceptance_service, device_stage_machine

    expected = tuple(device_stage_machine.DEVICE_STAGES[1:])
    assert acceptance_service._SHIPPED_STAGES == expected


def test_meta_constants_single_source():
    """meta_service.get_constants 聚合三组常量，且与各自既有真源同一内容。"""
    from app.services import capital_service, device_stage_machine, meta_service

    c = meta_service.get_constants()
    assert c["DEVICE_STAGES"] == list(device_stage_machine.DEVICE_STAGES)
    assert c["POOL_LABELS"] == dict(capital_service.POOL_LABELS)
    hints = c["STEP_HINTS"]
    assert isinstance(hints, dict) and len(hints) >= 18  # 标准金租 18 步全覆盖
    # 后端模板里出现的步骤名，hints 必须都有描述（否则前端步骤说明静默缺失）
    from app.services.workflow_service import _default_steps
    for step in _default_steps():
        assert hints.get(step["name"]), f"STEP_HINTS 缺步骤: {step['name']}"
