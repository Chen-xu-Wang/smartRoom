"""批量调用已发布的百炼应用，保存输出并按契约校验。

只用标准库发请求（与 backend/app/services/llm.py 一致）；校验复用 validate_contracts.py。

用法（在项目根目录执行）::

    python data/scripts/call_bailian.py --app event            # 跑 events/ 下全部样例
    python data/scripts/call_bailian.py --app event --only 03  # 只跑文件名以 03 开头的样例
    python data/scripts/call_bailian.py --app report
    python data/scripts/call_bailian.py --app qa

配置读取顺序：环境变量 > backend/.env。需要：
    BAILIAN_API_KEY      百炼 API Key（sk- 开头）
    BAILIAN_APP_EVENT    应用① 事件解读 的 APP_ID
    BAILIAN_APP_REPORT   应用② 月度报告 的 APP_ID
    BAILIAN_APP_QA       应用③ 水电问答 的 APP_ID
    BAILIAN_BASE_URL     可选，默认 https://dashscope.aliyuncs.com （华北2 北京）

输出保存在 data/processed/bailian_kit/runs/<app>/<样例名>.output.json（原始响应另存 .raw.json）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_contracts as vc  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
KIT = os.path.join(ROOT, "data", "processed", "bailian_kit")

# app → (APP_ID 配置名, 开始节点变量名, 样例目录列表, 输入契约, 输出契约)
APPS = {
    "event": ("BAILIAN_APP_EVENT", "event_json", ["events"], "event", "event_decision"),
    "report": ("BAILIAN_APP_REPORT", "report_json", ["monthly", "batch_brief"], "monthly_input", "report_output"),
    "qa": ("BAILIAN_APP_QA", "qa_json", ["qa"], "qa_context", "qa_answer"),
}


def load_config() -> dict:
    config = {}
    env_file = os.path.join(ROOT, "backend", ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("BAILIAN_API_KEY", "BAILIAN_APP_EVENT", "BAILIAN_APP_REPORT", "BAILIAN_APP_QA", "BAILIAN_BASE_URL"):
        if os.getenv(key):
            config[key] = os.getenv(key)
    return config


def call_app(base_url: str, api_key: str, app_id: str, var_name: str, payload: dict, timeout: int = 120) -> dict:
    """调用 DashScope 应用 API。开始节点变量通过 input.biz_params 传入，值为 JSON 字符串。"""
    url = f"{base_url.rstrip('/')}/api/v1/apps/{app_id}/completion"
    body = {
        "input": {
            "prompt": "请按系统提示处理输入参数",
            "biz_params": {var_name: json.dumps(payload, ensure_ascii=False)},
        },
        "parameters": {},
        "debug": {},
    }
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_json(text: str) -> dict:
    """从 output.text 中取出 JSON 对象。

    兼容三种情况：纯 JSON；被 ```json 包裹或带解释文字；结束节点用 JSON 输出模式
    把结果包成 {"result": "<JSON 字符串>"} 这类单键对象。
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"输出中没有 JSON：{text[:200]}")
    obj = json.loads(text[start : end + 1])
    if isinstance(obj, dict) and len(obj) == 1:
        (inner,) = obj.values()
        if isinstance(inner, str) and inner.strip().startswith("{"):
            return extract_json(inner)
        if isinstance(inner, dict) and "schema_version" in inner:
            return inner
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description="批量调用百炼应用并校验输出")
    parser.add_argument("--app", required=True, choices=sorted(APPS))
    parser.add_argument("--only", help="只跑文件名以此前缀开头的样例，如 03")
    args = parser.parse_args()

    app_key, var_name, folders, in_contract, out_contract = APPS[args.app]
    config = load_config()
    api_key, app_id = config.get("BAILIAN_API_KEY"), config.get(app_key)
    if not api_key or not app_id:
        print(f"缺少配置：BAILIAN_API_KEY 或 {app_key}（写入 backend/.env 或设置环境变量）")
        return 2
    base_url = config.get("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com")

    validators = vc.build_validators()
    run_dir = os.path.join(KIT, "runs", args.app)
    os.makedirs(run_dir, exist_ok=True)

    samples = [p for folder in folders for p in sorted(glob.glob(os.path.join(KIT, folder, "*.json")))]
    if args.only:
        samples = [p for p in samples if os.path.basename(p).startswith(args.only)]
    if not samples:
        print("没有匹配的样例")
        return 2

    failed = 0
    for path in samples:
        stem = os.path.basename(path)[: -len(".json")]
        payload = vc._load(path)
        started = time.time()
        try:
            raw = call_app(base_url, api_key, app_id, var_name, payload)
        except urllib.error.HTTPError as e:
            print(f"✗ {stem}：HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}")
            failed += 1
            continue
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"✗ {stem}：网络错误 {e}")
            failed += 1
            continue
        elapsed = time.time() - started
        with open(os.path.join(run_dir, f"{stem}.raw.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        text = (raw.get("output") or {}).get("text") or ""
        try:
            output = extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"✗ {stem}（{elapsed:.1f}s）：无法解析 JSON — {e}")
            failed += 1
            continue
        with open(os.path.join(run_dir, f"{stem}.output.json"), "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        errs = vc.schema_errors(validators[out_contract], output, stem)
        if not errs and in_contract == "event":
            errs = vc.check_event_pair(payload, output, stem)
        elif not errs and in_contract == "qa_context":
            errs = vc.check_qa_pair(payload, output, stem)
        tokens = (raw.get("usage") or {}).get("models") or []
        if errs:
            failed += 1
            print(f"✗ {stem}（{elapsed:.1f}s）：{len(errs)} 处不符合契约")
            for err in errs:
                print(f"    {err}")
        else:
            print(f"✓ {stem}（{elapsed:.1f}s）通过  usage={tokens}")

    print(f"\n完成 {len(samples)} 个，失败 {failed} 个。输出目录：{run_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
