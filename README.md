# AutoCheckBJMF — 班级魔方 GPS 自动签到

> 自动完成班级魔方平台的 GPS 定位签到，支持多账号、多班级、多定位点、定时触发，适合部署在 24h 运行的电脑或云服务器上。

---

## ✨ 功能特性

- **GPS 定位签到**：自动完成 GPS 定位签到，无需手动操作
- **多账号支持**：可同时为多个同学的账号签到，每次带随机坐标微偏移
- **多班级支持**：配置多个班级 ID，每次签到轮流对所有班级发起请求
- **多定位点**：配置多个真实坐标，遍历所有坐标签到
- **定时调度**：支持设置多个时间点，程序在指定时刻自动触发签到
- **失败重试**：签到失败后自动在 30 秒、5 分钟后各重试一次
- **PushPlus 推送**：签到成功后可发送微信消息通知
- **美化终端**：使用 Rich 库输出清晰的彩色面板、进度状态、倒计时

---

## 📂 文件说明

| 文件 | 用途 |
|------|------|
| `make_config.py` | **配置向导**：一次性交互配置，生成 `config.json` |
| `main.py` | **定时签到**：读取配置，按设定时间定时签到（长期运行） |
| `once.py` | **立即签到**：应急使用，启动即刻执行一次签到，不等待 |
| `config.json` | 配置文件（由 `make_config.py` 自动生成） |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 推荐使用 uv（速度更快）
uv sync

# 或使用 pip
pip install beautifulsoup4 drissionpage prompt-toolkit questionary requests rich schedule
```

### 2. 生成配置文件（在 Windows 上完成）

> [!IMPORTANT]
> **强烈建议在 Windows 桌面上完成配置**，因为配置过程需要打开浏览器扫码登录和获取经纬度。配置完成后再将 `config.json` 拷贝到服务器。

```bash
python make_config.py
```

配置向导会引导你完成以下 4 个步骤：

#### 步骤 1 — 获取班级 ID 与 Cookie

- 程序自动打开浏览器，显示微信扫码登录页面
- 用微信扫描二维码登录后，程序自动：
  - 从课程列表页面提取所有**班级 ID**
  - 从网络请求中捕获**登录 Cookie**
- 支持循环添加多个账号（每人扫一次码）
- 也支持手动补充班级 ID（应对课程未显示的情况）

#### 步骤 2 — 配置签到定位点

- 程序自动打开 [腾讯坐标拾取工具](https://lbs.qq.com/getPoint/)
- 在浏览器地图上点击你的签到地点，记录显示的经纬度
- 在终端输入纬度 (lat)、经度 (lng)、海拔 (acc)
- 支持添加多个定位点，程序签到时随机选取

> [!TIP]
> 经纬度请尽量输入 8 位小数（如 `39.90123456`），否则脚本自动随机补全到8位，小数位数越多，坐标微偏移越精准。

#### 步骤 3 — 配置定时签到时间

- 输入每天自动签到的时间点，格式为 `HH:MM`（如 `08:05`）
- 可添加多个时间点（如早上、中午、晚上各一次）
- 若不设置，`main.py` 启动后将立即执行一次签到

#### 步骤 4 — 配置 PushPlus 推送（可选）

- 前往 [PushPlus 官网](http://www.pushplus.plus/) 获取 Token
- 签到成功时会通过微信发送通知

配置完成后，当前目录会生成 `config.json`，格式如下：

```json
{
    "classes": ["136341", "136342"],
    "locations": [
        {"lat": "39.90123456", "lng": "116.40123456", "acc": "10"},
        {"lat": "39.90234567", "lng": "116.40234567", "acc": "8"}
    ],
    "cookies": [
        "remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=xxxxx"
    ],
    "scheduletimes": ["08:05", "12:30"],
    "pushplus": "",
    "debug": false
}
```

---

### 3. 运行签到程序

#### 定时自动签到（推荐）

```bash
python main.py
```

- 读取 `config.json` 中的 `scheduletimes`，为每个时间点注册定时任务
- 终端实时显示距离下次签到的倒计时
- 程序会一直运行，直到手动停止（`Ctrl+C`）

#### 应急立即签到

```bash
python once.py
```

- 启动后**立即执行一次**全班级签到，不等待
- 适用于忘记配置定时、临时需要签到等场景

---

## 💡 推荐部署方案

### 方案一：Windows 长期运行（适合有家用电脑/台式机）

在 Windows 上完成配置后，直接运行 `main.py` 即可。

```bash
# 保持终端窗口不关闭
python main.py
```

---

### 方案二：云服务器 + pm2（推荐，24h 稳定运行）

**在 Windows 上完成配置后，将 `config.json` 上传到服务器**，然后用 pm2 管理进程：

#### 安装 pm2

```bash
npm install -g pm2
```

#### 创建 pm2 配置文件 `ecosystem.config.js`

```js
module.exports = {
  apps: [{
    name: "AutoCheckBJMF",
    script: "main.py",
    interpreter: "python3",   // 或 python，取决于服务器环境
    cwd: "/path/to/AutoCheckBJMF",
    restart_delay: 5000,      // 崩溃后 5 秒重启
    max_restarts: 10,
    log_date_format: "YYYY-MM-DD HH:mm:ss"
  }]
};
```

#### 启动、监控与开机自启

```bash
# 启动
pm2 start ecosystem.config.js

# 查看日志
pm2 logs AutoCheckBJMF

# 查看状态
pm2 status

# 设置开机自启
pm2 startup
pm2 save
```

> [!NOTE]
> 云服务器没有图形界面，**无法运行 `make_config.py`**（需要浏览器）。请务必在 Windows 上生成好 `config.json` 再上传到服务器。

> [!WARNING]
> Cookie 具有有效期，过期后签到会失败。需要在 Windows 上重新运行 `make_config.py` 更新 Cookie，然后将新的 `config.json` 上传到服务器并重启 pm2。

---

## 🔄 更新 Cookie

Cookie 过期时，在 Windows 上执行：

```bash
python make_config.py
```

程序会检测到已有配置并询问清空配置重新配置，如果只是为了刷新cookie，请勿清空配置。选择继续后重新扫码即可更新 Cookie，其余配置（班级、定位、定时）保持不变。

配置更新后，将新的 `config.json` 上传服务器，然后：

```bash
pm2 restart AutoCheckBJMF
```

---

## ❓ 常见问题

**Q：Cookie 在哪里获取？**  
A：运行 `make_config.py`，扫码登录后自动进行网页监听和html解析捕获，无需手动抓包。

**Q：签到失败是什么原因？**  
A：大概率是由 Cookie 过期导致，请重新运行 `make_config.py` 更新 Cookie。

**Q：经纬度填多少合适？**  
A：腾讯地图点击你的教室/校园位置，至少填 8 位小数。程序会自动在此基础上做微偏移。

**Q：多人签到时经纬度会一样吗？**  
A：不会。每个账号签到时程序都会对坐标做随机微偏移（±0.00015 度范围内），避免相同坐标被检测。

---

## ⚠️ 免责声明

本项目仅供学习交流使用，请勿用于作弊等违规行为。使用本项目产生的一切后果由使用者自行承担。
