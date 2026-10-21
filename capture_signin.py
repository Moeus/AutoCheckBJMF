"""手动协作抓取：默认只检查配置；加 --run 后执行一次真实签到并保存前后报文。"""

import argparse
import difflib
import json
import re
import time
import traceback
from pathlib import Path
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

from core.constants import BASE_DIR, CONFIG_PATH
from core.cooldown import cooldown_minutes
from core.session import AccountSessions, parse_cookie
from core.signin import _already_signed, signin_headers
from core.timezone import beijing_now


class CaptureStopped(Exception):
    """已保存响应，停止后续请求。"""


class Recorder:
    def __init__(self, directory, raw_cookie):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.secrets = set(parse_cookie(raw_cookie).values())
        self.stage = ""
        self.records = []

    def clean(self, value):
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if not isinstance(value, str):
            return value
        for secret in sorted(self.secrets, key=len, reverse=True):
            if len(secret) >= 4:
                value = value.replace(secret, "<redacted>")
        return re.sub(
            r'''(?i)([?&](?:token|access_token|code|key|password)=)[^&#\s"'<>]*''',
            r"\1<redacted>", value,
        )

    def headers(self, headers):
        return {k: "<redacted>" if k.lower() in {
            "cookie", "set-cookie", "authorization", "proxy-authorization",
        } else v for k, v in headers.items()}

    def request_data(self, request):
        body = request.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        return {"method": request.method, "url": request.url,
                "headers": self.headers(request.headers), "body": body}

    def write_json(self, name, data):
        (self.directory / name).write_text(
            json.dumps(self.clean(data), ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def response_hook(self, response, **kwargs):
        for header in [response.request.headers.get("Cookie", ""),
                       response.headers.get("Set-Cookie", "")]:
            try:
                self.secrets.update(parse_cookie(header).values())
            except ValueError:
                pass
        self.secrets.update(cookie.value for cookie in response.cookies)
        body = response.text
        soup = BeautifulSoup(body, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        minutes = cooldown_minutes(body)
        record = {
            "timestamp": beijing_now().isoformat(timespec="milliseconds"),
            "stage": self.stage,
            "request": self.request_data(response.request),
            "response": {"url": response.url, "status": response.status_code,
                         "reason": response.reason, "headers": self.headers(response.headers),
                         "encoding": response.encoding, "body": body},
            "observations": {"title": title, "cooldown_minutes": minutes,
                             "gps_button_ids": [a['id'] for a in soup.select('a[id^="gps_btn_"]')]},
        }
        stem = f"{len(self.records) + 1:02d}_{self.stage}"
        self.write_json(stem + ".json", record)
        (self.directory / (stem + ".html")).write_text(self.clean(body), encoding="utf-8")
        self.records.append(self.clean(record))
        print(f"{record['timestamp']} | {self.stage} | {response.request.method} | HTTP {response.status_code}")
        if minutes is not None:
            response.close()
            raise CaptureStopped(f"请求过于频繁，服务器要求冷却 {minutes} 分钟；已停止采集，不重试。")
        if response.status_code >= 400:
            response.close()
            raise CaptureStopped(f"HTTP {response.status_code}，报文已保存，停止后续请求。")
        if "登录" in title or "/login" in response.url.lower():
            response.close()
            raise CaptureStopped("返回登录页面，报文已保存，停止后续请求。")
        return response

    def compare(self, name, before, after):
        diff = difflib.unified_diff(
            self.clean(before).splitlines(True), self.clean(after).splitlines(True),
            fromfile=f"{name}_before", tofile=f"{name}_after",
        )
        (self.directory / f"{name}.diff").write_text("".join(diff), encoding="utf-8")


def capture(cfg, class_id, account, location, task_id, directory):
    """最多五个业务请求（加服务器跳转）；只提交一次，不轮询、不自动重试。"""
    raw_cookie = cfg["cookies"][account - 1]
    loc = cfg["locations"][location - 1]
    recorder = Recorder(directory, raw_cookie)
    summary = {"class_id": class_id, "account": account, "location": location,
               "task_id": task_id, "status": "started"}
    print(f"报文保存目录：{recorder.directory.resolve()}")
    try:
        with AccountSessions() as sessions:
            session = sessions.get(raw_cookie)
            session.max_redirects = 5
            session.hooks["response"].append(recorder.response_hook)
            headers = signin_headers(class_id)

            def request(stage, method, url, **kwargs):
                if recorder.records:
                    time.sleep(2)
                recorder.stage = stage
                return session.request(method, url, headers=headers, timeout=15, **kwargs)

            course_url = f"http://k8n.cn/student/course/{class_id}/punchs"
            course_before = request("course_before", "GET", course_url)
            soup = BeautifulSoup(course_before.text, "html.parser")
            ids = list(dict.fromkeys(a["id"].removeprefix("gps_btn_") for a in
                       soup.find_all("a", id=re.compile(r"^gps_btn_\d+$"))))
            if task_id is None:
                if len(ids) != 1:
                    raise CaptureStopped(f"发现 {len(ids)} 个 GPS 任务 {ids}；请指定唯一任务 ID 后再采集。")
                task_id = ids[0]
            elif task_id not in ids:
                raise CaptureStopped(f"指定任务 {task_id} 不在本次页面的 GPS 按钮中，停止提交。")
            summary["task_id"] = task_id
            task_url = f"http://k8n.cn/student/punchs/course/{class_id}/{task_id}"
            task_before = request("task_before", "GET", task_url)
            if _already_signed(BeautifulSoup(task_before.text, "html.parser")):
                raise CaptureStopped("该任务采集前已经签到，已保存页面；需要新的未签到任务进行前后对比。")
            payload = {"id": task_id, "lat": float(loc["lat"]), "lng": float(loc["lng"]),
                       "acc": loc["acc"], "res": "", "gps_addr": ""}
            request("submit", "POST", task_url, data=payload)
            task_after = request("task_after", "GET", task_url)
            course_after = request("course_after", "GET", course_url)
            recorder.compare("task", task_before.text, task_after.text)
            recorder.compare("course", course_before.text, course_after.text)
            summary["status"] = "captured"
            summary["note"] = "采集完成；是否签到成功及已签到标记需根据报文判断。"
    except CaptureStopped as exc:
        summary.update(status="stopped", reason=str(exc))
        print(str(exc))
    except requests.RequestException as exc:
        summary.update(status="network_error", reason=type(exc).__name__)
        error = {"timestamp": beijing_now().isoformat(), "stage": recorder.stage,
                 "traceback": traceback.format_exc()}
        if exc.request is not None:
            error["request"] = recorder.request_data(exc.request)
        recorder.write_json("network_error.json", error)
        print("网络异常，已保存诊断，不自动重试（提交超时也不重复提交）。")
    finally:
        summary["http_responses"] = len(recorder.records)
        recorder.write_json("summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--class-id")
    parser.add_argument("--account", type=int, default=1)
    parser.add_argument("--location", type=int, default=1)
    parser.add_argument("--task-id")
    parser.add_argument("--run", action="store_true", help="执行真实请求并提交一次签到")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    classes = list(map(str, cfg["classes"]))
    if not 1 <= args.account <= len(cfg["cookies"]):
        parser.error("账号序号超出配置范围")
    if not 1 <= args.location <= len(cfg["locations"]):
        parser.error("定位点序号超出配置范围")
    if args.class_id is not None and args.class_id not in classes:
        parser.error("班级 ID 不在配置中")
    loc = cfg["locations"][args.location - 1]
    if not (-90 <= float(loc["lat"]) <= 90 and -180 <= float(loc["lng"]) <= 180):
        parser.error("配置的经纬度超出范围")
    if not args.run:
        print(f"配置检查通过：班级 {classes}；账号 {args.account}；定位点 {args.location}。")
        print("未发送任何请求。收到签到任务就绪通知后，用 --run --class-id 班级ID 启动一次采集。")
        return 0
    class_id = args.class_id or (classes[0] if len(classes) == 1 else None)
    if class_id is None:
        parser.error("配置有多个班级，请用 --class-id 指定本次测试班级")
    directory = BASE_DIR / "captures" / (beijing_now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])
    summary = capture(cfg, class_id, args.account, args.location, args.task_id, directory)
    return 0 if summary["status"] == "captured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
