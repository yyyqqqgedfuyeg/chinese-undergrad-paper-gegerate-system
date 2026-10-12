"""完整短篇论文验收事实源：实现、实验、图表与论述边界使用同一份数据。"""

from pathlib import Path

from agent import create_initial_global_state
from test.writing_reference import SCHEMA, run_evidence


def build_state(workspace: Path):
    evidence = run_evidence(workspace / "evidence")
    outline = []

    def add(sid, title, words=0, assets=None):
        outline.append({"section_id": sid, "title": title, "target_words": words,
                        "planned_assets": assets or [], "status": "pending"})

    add("1", "第一章 绪论")
    add("1.1", "研究背景与问题界定", 400)
    add("1.2", "研究方法与工作范围", 350)
    add("2", "第二章 需求分析与业务约束")
    add("2.1", "角色权限与状态流转", 550,
        ["tbl_2_1 (角色与操作权限表)", "fig_2_1 (预约状态流转图，含全部合法边与开始时刻限制)"])
    add("2.2", "资源互斥与时间边界", 500)
    add("3", "第三章 系统设计")
    add("3.1", "模块与数据设计")
    add("3.1.1", "模块划分与信任边界", 450)
    add("3.1.2", "关系模型与约束设计", 600, ["tbl_3_1 (bookings 数据表字段结构)"])
    add("4", "第四章 参考实现与界面原型")
    add("4.1", "核心实现")
    add("4.1.1", "事务处理与异常分支", 650)
    add("4.1.2", "预约页面原型", 350, ["fig_4_1 (学生端预约页面原型截图，明确静态原型与模拟数据)"])
    add("5", "第五章 验证与结果分析")
    add("5.1", "验证过程")
    add("5.1.1", "验证环境、用例与实测结果", 650, ["tbl_5_1 (六项约束验证实际结果)"])
    add("5.1.2", "结果解释与有效性边界", 450)
    add("6", "第六章 总结与展望")
    add("6.1", "工作总结与后续改进", 350)
    table_data = {
        "tbl_2_1": {"columns": ["角色", "操作", "条件", "结果"], "rows": [
            ["学生", "提交预约", "时隙未开始且资源未被占用", "新建 pending"],
            ["学生", "取消预约", "本人 pending/confirmed 且未开始", "变为 cancelled"],
            ["管理员", "审核通过", "pending 且未开始", "变为 confirmed"],
            ["管理员", "审核拒绝", "pending 且未开始", "变为 rejected"]]},
        "tbl_3_1": {"columns": ["字段", "类型", "约束与含义"], "rows": [
            ["id", "INTEGER", "主键；预约标识"],
            ["resource_id", "INTEGER", "非空；外键 resources(id)"],
            ["slot_id", "INTEGER", "非空；外键 slots(id)"],
            ["user_id", "INTEGER", "非空；外键 users(id)"],
            ["status", "TEXT", "非空；CHECK 限定四种状态"]]},
        "tbl_5_1": {"columns": ["编号", "验证目标", "实际结果", "结论"], "rows": [
            ["T1", "取消后释放资源", "创建→确认→取消→再次创建", "通过"],
            ["T2", "越权取消", "返回 forbidden；原记录仍 pending", "通过"],
            ["T3", "审核权限与拒绝终态", "越权被拒；拒绝后不可确认；可重新预约", "通过"],
            ["T4", "开始时刻边界", "提交、取消、确认均返回 too_late", "通过"],
            ["T5", "资源互斥范围", "同资源同槽冲突；不同资源可独立预约", "通过"],
            ["T6", "双连接并发抢占", "20轮：20成功、20冲突、0次互斥违例", "通过"]]},
    }
    facts = {
        "tech_stack": {"backend": f"Python {evidence['environment']['python']} 标准库服务类",
                       "database": f"SQLite {evidence['environment']['sqlite']}", "frontend": "静态 HTML/CSS 原型"},
        "implementation_status": "已实现并实际运行 test/writing_reference.py 中的 BookingService 和验证程序；未实现HTTP服务、登录鉴权或前后端联调。网页只用于展示。",
        "closed_roles": {"student": "学生", "admin": "管理员"},
        "closed_states": {"pending": "待审核", "confirmed": "已确认", "cancelled": "已取消", "rejected": "已拒绝"},
        "state_edges": ["提交成功→pending", "pending→confirmed：管理员确认",
                        "pending→rejected：管理员拒绝", "pending→cancelled：本人取消",
                        "confirmed→cancelled：本人取消"],
        "rules": ["状态只有四种，不存在草稿、已完成或过期状态；新申请直接进入pending。",
                  "资源均为独占单容量，待审核与已确认均占用名额；取消与拒绝释放名额但保留历史记录。",
                  "同一(resource_id,slot_id)最多一条活动记录；不限制同一学生在不同设备上的同时预约。",
                  "slots为预置、不重叠的固定时隙；原型不提供用户自定义时间段，也未实现任意区间冲突检测。",
                  "所有提交、确认、拒绝、取消都要求now<starts_at；等于开始时刻也拒绝。",
                  "管理员只能审核pending，不能取消他人预约；学生不能审核，且只能取消本人pending或confirmed。",
                  "cancelled与rejected为终态，不能恢复；需重新提交生成新记录。",
                  "没有到时自动结束/过期清理；开始后未审核记录仍可保持pending，但禁止变更；这是明确局限。"],
        "db_schema_sql": SCHEMA,
        "service_interface": {"book(actor,resource,slot,now)": "返回created/id、conflict、forbidden、too_late、resource_not_found或database_error",
                              "transition(actor,booking,action,now)": "action为confirm/reject/cancel；服务端从users表读取角色；事务中检查归属、状态及时间；返回新状态或明确错误",
                              "snapshot()": "验证使用的数据库快照，不是面向用户的授权查询接口"},
        "atomicity": ["每次写操作独立连接，foreign_keys=ON，timeout=5秒，isolation_level=None，显式BEGIN IMMEDIATE。",
                      "部分唯一索引one_active_booking覆盖(resource_id,slot_id)，WHERE status IN ('pending','confirmed')。",
                      "BEGIN IMMEDIATE使读校验和状态更新位于同一写事务；唯一索引是资源互斥的最终约束，单纯先查后写不能替代。",
                      "book先校验用户角色、时隙开始时间和资源存在，再INSERT。IntegrityError回滚返回conflict；ValueError返回业务错误；OperationalError回滚返回database_error。",
                      "prototype将OperationalError统一归类，不提供业务自动重试；busy等待不等同于多个并行写入。",
                      "SQLite单写者机制限制并发写扩展性；该实现不适合据此声称高并发生产能力。"],
        "trust_boundary": "actor由测试程序直接传入，是可信身份假设；读取users角色和校验归属不是完整登录认证，不能声称防止身份冒用。",
        "evidence": {**{k: evidence[k] for k in ("environment", "method", "time_model", "limitations")},
                     "cases": [{k: v for k, v in case.items() if k != "snapshot"} for case in evidence["cases"]]},
        "evidence_paths": ["evidence/reference.py", "evidence/schema.sql", "evidence/evidence.json"],
        "canonical_table_data": table_data,
        "asset_instructions": "三个表格必须逐字使用canonical_table_data对应JSON；图题不超过30个汉字，图中状态边、权限与数据必须吻合事实源。",
        "section_requirements": {
            "1.1": "提出待审核占用、并发重复预约和越权取消三个具体问题，不捏造学校统计数字。",
            "1.2": "说明规范→数据库约束→参考实现→可复现验证方法及范围。",
            "2.1": "四状态、完整五条边、两种角色、时刻前置条件和终态；引用本节图表。",
            "2.2": "精确定义活动集合与每个资源时隙至多一条的不变量、开始边界及固定时隙假设；引用cite_partial。",
            "3.1.1": "说明展示层原型/服务类/持久化及输入身份信任边界，不能说已部署HTTP接口。",
            "3.1.2": "四张真实表关系，bookings五字段；部分唯一索引覆盖两状态；普通全表唯一不能满足保留取消历史后重新预约。",
            "4.1.1": "严格按参考源码解释BEGIN IMMEDIATE、索引兜底、回滚及异常分类；解释单纯事务内先查后写不是一般性并发证明。引用cite_transaction与cite_python。",
            "4.1.2": "静态UI应显示待审核/已确认两条不同设备模拟预约与取消入口、原型标记；按钮不是服务端权限证明。",
            "5.1.1": "说明本机版本、注入时钟、两个线程各自独立连接，六项测试及20轮40次申请的观察，引用结果表。",
            "5.1.2": "区分有限测试证据和由唯一索引推导的不变量；列明未经验证的认证/多机/高负载/故障恢复、时间清理和自定义区间局限。",
            "6.1": "回扣最初三个问题、实际完成内容、有限结论与后续工作，不写生产系统已上线。"},
    }
    bib = [
        {"key": "cite_partial", "title": "Partial Indexes", "authors": "SQLite Development Team",
         "url": "https://www.sqlite.org/partialindex.html", "evidence_summary": "WHERE限定被索引的行，UNIQUE约束仅对这些行生效；部分唯一索引可保证满足谓词的子集键唯一。",
         "formatted": "SQLite Development Team. Partial Indexes[EB/OL]. https://www.sqlite.org/partialindex.html, 访问日期：2026-10-03."},
        {"key": "cite_transaction", "title": "Transaction", "authors": "SQLite Development Team",
         "url": "https://www.sqlite.org/lang_transaction.html", "evidence_summary": "SQLite支持多个同时读事务但同一时刻只有一个写事务；BEGIN IMMEDIATE立即尝试开启写事务，其他连接正写时可能返回SQLITE_BUSY。",
         "formatted": "SQLite Development Team. Transaction[EB/OL]. https://www.sqlite.org/lang_transaction.html, 访问日期：2026-10-03."},
        {"key": "cite_python", "title": "sqlite3 — DB-API 2.0 interface for SQLite databases", "authors": "Python Software Foundation",
         "url": "https://docs.python.org/3/library/sqlite3.html", "evidence_summary": "Python sqlite3允许设置连接超时、使用SQL占位符绑定参数并捕获IntegrityError和OperationalError；显式事务需要管理提交与回滚。",
         "formatted": "Python Software Foundation. sqlite3 — DB-API 2.0 interface for SQLite databases[EB/OL]. https://docs.python.org/3/library/sqlite3.html, 访问日期：2026-10-03."},
    ]
    return create_initial_global_state(topic="共享设备预约系统的设计与一致性验证", workspace_dir=str(workspace),
                                       project_id="writing_docx_acceptance", single_source_of_truth=facts,
                                       bib_pool=bib, outline_plan=outline)
