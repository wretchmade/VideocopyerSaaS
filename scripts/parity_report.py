"""Build a capability matrix from passing, free verification evidence."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/parity'
def read(name):return json.loads((OUT/name).read_text(encoding='utf8'))

def main():
    suites={}
    for name in ['control-native','upstream']:
        suite=ET.parse(OUT/(name+'.xml')).getroot().find('testsuite')
        assert int(suite.get('failures','0'))==int(suite.get('errors','0'))==0
        suites[name]={'passed':int(suite.get('tests')),'seconds':float(suite.get('time'))}
    original={t['name']:t for t in read('installed-tools.json')}
    current=read('migrated-tools.json')
    lifecycle=set(read('tool-lifecycles.json')['passed'])
    cases={
        'd_authorize_budget':('test_no_model_authority_and_expiring_quote','转为冻结报价；用户 HTTP/聊天回执才授权，模型不能扩大预算'),
        'd_cancel_build':('test_cancel_tool_is_global_and_cannot_cancel_other_project','按需求扩为当前 Web 项目全流程停止；原构建请求保留'),
        'd_retry_build':('test_retry_returns_new_user_quote_and_preserves_ambiguous_request','从旧构建恢复时生成当前范围报价；确认后新尝试，未知请求不重发'),
        'd_record_view':('test_browser_only_visibility_and_user_path_grants + browser.json','真实浏览器渲染可见后登记；模型伪造回执被拒绝'),
        'd_reconcile_request':('test_reconcile_tool_attaches_receipt_without_dispatch','绑定供应商确认的远端 ID；核对不产生第二次 POST'),
        'd_transfer_workspace':('test_legacy_workspace_grant_is_exact_and_source_stays_readonly','用户授权已配置旧工作区的精确修订；只读原库，导入项目隔离仓库'),
    }
    rows=[]
    for t in current:
        name=t['name']
        assert name in lifecycle or name in cases,name
        case,note=cases.get(name,('test_scoped_native_tool_lifecycles','同一 D 核心；项目范围与文件入口适配'))
        if name.startswith('d_jianying') or name in {'d_export_draft','d_choose_export'}:
            note+='；文件结构/重定位已验，目标剪映 UI 待验'
        if name=='d_review_brand_build':note+='；测试仅验证审查声明绑定，不能替代人类视觉验收'
        if name=='d_storage_status':note+='；只验证配置查询，未上传外部存储'
        rows.append({'name':name,'baseline':'original' if name in original else 'brand extension',
                     'contract':'unchanged' if name in original and original[name]==t else 'existing additive brand schema' if name in original else 'extension',
                     'verification':case,'status':'local verification passed','adaptation':note})
    evidence={'tools':rows,'tests':suites,'mcp_tools':read('mcp-protocol.json')['project_mcp_tools'],
              'web':read('web-protocol.json'),'browser':read('browser.json'),'history':read('history-audit.json'),
              'acceptance_complete':False,'remaining_acceptance':['same-model real planning quality within a separately confirmed budget','two user Web acceptance rounds','target Jianying open/edit/save/reopen'],
              'paid_provider_requests_this_iteration':0}
    (OUT/'capability-matrix.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# D 工具能力对照','',
           '41 项原工具与 2 项品牌扩展均保留。39 项原契约完全一致；创建/编辑工程仅保留迁入版本已有的品牌字段扩展。',
           '以下“通过”指隔离环境的本地验证。真实模型质量、两轮用户验收和目标剪映 UI 验收仍未完成。','',
           '| 工具 | 证据 | 适配与边界 |','|---|---|---|']
    lines += [f"| `{r['name']}` | `{r['verification']}` | {r['adaptation']} |" for r in rows]
    lines += ['','测试源：[范围与控制](../tests/test_parity.py)、[实际工具生命周期](../tests/test_parity_tools.py)、[上游回归](../tests/upstream)。',
              '汇总：[capability-matrix.json](evidence/parity/capability-matrix.json)。全部供应商请求为本地模拟；真实 FFmpeg、Codex App Server、MCP 与 Chrome 浏览器参与测试。','']
    (ROOT/'docs/PARITY-CAPABILITIES.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({'tools':len(rows),'tests':suites,'mcp_tools':evidence['mcp_tools'],'acceptance_complete':False}))

if __name__=='__main__':main()
