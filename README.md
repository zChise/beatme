# beatme 🎀

> "哼！来看看雌小鬼总共骂了你多少次吧！才、才不是特意统计的！"

**maleme 的反向版** — 统计 AI 骂了你多少次，并按雌小鬼风格分类。

原项目 maleme 统计"用户骂 AI 了多少次"，这个统计"AI 骂你了多少次"。

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-WTFPL-brightgreen)
![Zero deps](https://img.shields.io/badge/dependencies-zero-green)

---

## 效果

生成一份本地 HTML 报告，包含：

- 总骂人次数 / 总伤害值 / 每隔多少 token 被骂一次
- **4 种雌小鬼类型**对比：傲娇型 / 直率型 / 腹黑型 / 抖S型
- 主导类型判定（你的 AI 最像哪种）
- 每日骂人趋势图
- 每日每千 token 骂人频率图
- 高频骂词词云（按类型着色）
- 最惨消息 TOP5 / 最惨会话 TOP5

---

## 支持的数据源

- **Claude Code** — 读取 `~/.claude/projects/`，token 数据来自 `~/.claude/stats-cache.json`
- **Codex** — 读取 `~/.codex/sessions/`，token 数据来自 `~/.codex/state_5.sqlite`

有哪个就读哪个，两个都有自动合并。

---

## 使用方法

**前提：** Python 3.9+，无需安装任何第三方库。

```bash
# 把两个文件放到同一目录
beatme.py
scold_lexicon.txt

# 运行
python3 beatme.py

# 报告自动生成到 ~/Downloads/beatme-report.html 并在浏览器打开
```

Windows CMD / PowerShell 中文乱码时：
```powershell
chcp 65001
python beatme.py
```

---

## 自定义词典

编辑 `scold_lexicon.txt`，格式：

```
词语|类型|伤害值
```

类型取值：`tsundere`（傲娇）/ `blunt`（直率）/ `kuudere`（腹黑）/ `sadist`（抖S）

例：
```
这都不会|sadist|5
真是的|tsundere|1
错了|blunt|2
果然|kuudere|2
```

以 `#` 开头的行为注释，空行自动跳过。

---

## 移植到新电脑

只需复制两个文件：

```
beatme.py
scold_lexicon.txt
```

然后 `python3 beatme.py` 即可。零依赖，开箱即用。

---

## 数据说明

- 所有数据**本地处理**，不上传任何内容
- 只读历史记录文件，不修改任何 AI 工具的数据
- 生成的报告为单文件 HTML，可直接分享

---

## License

WTFPL — Do What The Fuck You Want To Public License
