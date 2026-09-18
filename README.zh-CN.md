<div align="center">

# MelodyMine

### 多平台音乐下载 & 元数据引擎

[![CI](https://img.shields.io/github/actions/workflow/status/thintsing/MelodyMine/ci.yml?branch=main&logo=github&label=CI)](https://github.com/thintsing/MelodyMine/actions)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik0xMiAyTDMgN3YxMGw5IDUgOS01VjdsLTktNXptMCAyLjJMMTguNSA3IDEyIDEwLjIgNS41IDcuMiAxMiA0LjJ6TTUgOC4ybDYgMy4zIDYtMy4zVjE1bC02IDMuMy02LTMuM1Y4LjJ6Ii8+PC9zdmc+)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-10%2B-orange)](#支持平台)
[![Tests](https://img.shields.io/badge/tests-58%20passing-brightgreen?logo=pytest)](tests/)

[English](README.md) | [简体中文](README.zh-CN.md)

从 **10+ 平台**搜索、下载、标记音乐 —— 支持无损 FLAC、自动元数据、同步歌词、零配置启动。一个 CLI 搞定一切。

</div>

---

## 核心能力

| 能力 | 说明 |
| :--- | :--- |
| **10+ 音源** | Bilibili、YouTube、YouTube Music、Spotify、Soulseek P2P、酷我、Audius、网易云、SoundCloud、Bandcamp |
| **无损音质** | 酷我 / Soulseek / 网易云原生 FLAC — 按音源自动检测 |
| **智能元数据** | MusicBrainz + 网易云 + iTunes 多源查询，封面嵌入，自动重命名 |
| **同步歌词** | LRCLIB 集成 — 为每首歌曲生成时间同步的 `.lrc` 歌词文件 |
| **零配置** | 自动检测 Python 运行时、安装依赖、查找 ffmpeg — 一条 `setup` 命令搞定 |
| **AI 原生** | 可作为独立 CLI 运行，也可作为 AI 助手的文件型 Skill |
| **标准库优先** | API 客户端仅使用 Python 标准库 — 最少依赖，最大可移植性 |

## 支持平台

| 平台 | 类型 | 认证 | 无损 | 说明 |
| :--- | :---: | :---: | :---: | :--- |
| **Bilibili** | 搜索 + 下载 | 无需 | 经 yt-dlp | 中文查询默认平台；WBI API 搜索 |
| **YouTube** | 搜索 + 下载 | 可选 | 经 yt-dlp | 国际查询默认平台；支持代理 |
| **YouTube Music** | 搜索 + 下载 | 无需 | 经 yt-dlp | 通过 `ytmusicapi` 搜索曲库 |
| **Spotify** | URL 下载 | 无需 | 经 spotDL | 粘贴 Spotify 链接即可；自动安装 spotDL |
| **Soulseek** | P2P 搜索 + 下载 | 用户名/密码 | 原生 FLAC | 多候选重试；持久会话 |
| **酷我音乐** | 搜索 + 直接下载 | 无需 | 原生 FLAC | 第三方 CDN 解析；支持无损 & 高码率 |
| **Audius** | 搜索 + 串流 | 无需 | 320kbps MP3 | Web3 音乐平台；零认证 |
| **网易云音乐** | URL 解析 + 下载 | 无需 | 128kbps MP3 | 免费歌曲 CDN 直连；自动回退 |
| **SoundCloud** | 直接下载 | 无需 | 经 yt-dlp | 粘贴 URL 直接下载 |
| **Bandcamp** | 直接下载 | 无需 | 经 yt-dlp | 粘贴 URL 直接下载 |

## 快速开始

```bash
# 一次性初始化（自动检测 Python、安装依赖、查找 ffmpeg）
python scripts/music_helper.py setup

# 下载 —— 输入歌名即可
python scripts/music_helper.py download "周杰伦 稻香"
python scripts/music_helper.py download "The Weeknd Blinding Lights"

# 从酷我下载无损 FLAC
python scripts/music_helper.py download "周杰伦 稻香" --platform kuwo --format flac

# 粘贴任意链接
python scripts/music_helper.py download "https://open.spotify.com/track/..."
python scripts/music_helper.py download "https://music.163.com/song?id=185809"
```

## 使用指南

### 搜索 & 下载

```bash
# 仅搜索 —— 先看结果再决定
python scripts/music_helper.py search "周杰伦 稻香" --platform kuwo

# 选择指定搜索结果
python scripts/music_helper.py download "稻香" --index 2

# 强制指定平台
python scripts/music_helper.py download "周杰伦 稻香" --platform bilibili
python scripts/music_helper.py download "Air Supply" --platform soulseek
python scripts/music_helper.py download "周杰伦 稻香" --platform kuwo --format flac

# 格式 & 输出控制
python scripts/music_helper.py download "周杰伦 稻香" --format mp3 --bitrate 320K
python scripts/music_helper.py download "Artist Song" --output "D:\Music"

# 代理 & Cookies（受限网络）
python scripts/music_helper.py download "The Weeknd" --proxy socks5://127.0.0.1:7897
python scripts/music_helper.py download "Artist Song" --cookies "cookies.txt"

# 跳过歌词或元数据
python scripts/music_helper.py download "Song" --no-lyrics
python scripts/music_helper.py download "Song" --no-metadata
```

### 元数据 & 歌词

```bash
# 为已下载文件更新元数据（多源查询 + 封面 + 歌词）
python scripts/music_helper.py meta "D:\Music\song.mp3"
python scripts/music_helper.py meta "D:\Music\song.mp3" --query "周杰伦 稻香"
```

### 预演 & JSON 输出

```bash
# 预演模式 —— 只看会做什么，不实际下载
python scripts/music_helper.py download "周杰伦 稻香" --platform kuwo --dry-run

# 机器可读 JSON 输出（用于自动化）
python scripts/music_helper.py download "周杰伦 稻香" --json
```

## CLI 参考

```
python scripts/music_helper.py download "query" [options]

选项：
  --platform {auto,bilibili,youtube,ytmusic,soulseek,kuwo}
                                      搜索平台（默认：auto）
  --format {auto,mp3,flac,m4a,opus,wav,vorbis}
                                      输出格式（默认：auto）
  --output PATH                       输出目录
  --proxy URL                         代理地址（如 socks5://host:port）
  --cookies PATH                      YouTube cookies.txt
  --bitrate RATE                      音频码率（如 320K）
  --index N                           搜索结果序号（从 1 开始）
  --no-thumbnail                      跳过封面嵌入
  --no-lyrics                         跳过歌词获取
  --no-metadata                       跳过元数据增强
  --dry-run                           预演模式
  --json                              机器可读 JSON 输出
  --debug                             写入会话日志用于排查
  --slsk-user USER                    Soulseek 用户名（或 SLSK_USERNAME 环境变量）
  --slsk-pass PASS                    Soulseek 密码（或 SLSK_PASSWORD 环境变量）

python scripts/music_helper.py meta "filepath" [options]

选项：
  --query QUERY                       元数据查询关键词
  --no-thumbnail                      跳过封面嵌入
  --no-lyrics                         跳过歌词获取
  --json                              机器可读 JSON 输出
```

## 平台路由

| 输入 | 路由 | 回退链 |
| :--- | :--- | :--- |
| 中文查询 | Auto → Bilibili | Soulseek → Bilibili → YouTube |
| 英文 / 国际查询 | Auto → YouTube | Soulseek → YouTube |
| `--platform kuwo` | 酷我直连 | 酷我搜索 → CDN 下载 |
| Spotify URL | spotDL | — |
| 网易云 URL | 网易云 CDN | 网易云 → Bilibili → YouTube |
| YouTube / SoundCloud / Bandcamp URL | yt-dlp 直连 | — |
| `--platform soulseek` | Soulseek P2P | Soulseek → YouTube |

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    music_helper.py                       │
│              (CLI 入口 + 平台调度 + 下载管线)              │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ Bilibili │ YouTube  │  酷我    │ Soulseek │  网易云     │
│  管线    │  管线    │  管线    │  管线    │  管线       │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  metadata.py │  │ lyrics_client│  │ melodymine    │  │
│  │  (MusicBrainz│  │ (LRCLIB API) │  │ _common.py    │  │
│  │  + 网易云 +  │  │ 同步歌词     │  │ (Python/venv/ │  │
│  │  iTunes +   │  │ 普通歌词     │  │  pip/ffmpeg)  │  │
│  │  封面下载)   │  │              │  │               │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │bili_     │ │kuwo_     │ │audius_   │ │netease_   │  │
│  │client.py │ │client.py │ │client.py │ │client.py  │  │
│  │(WBI API) │ │(第三方   │ │(Audius   │ │(CDN URL)  │  │
│  │          │ │ CDN API) │ │ REST API)│ │           │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ytmusic_  │ │soulseek_ │ │mbrainz_  │ │cover_     │  │
│  │client.py │ │client.py │ │client.py │ │client.py  │  │
│  │(ytmusic- │ │(aioslsk  │ │(Music-   │ │(URL→文件) │  │
│  │ api)     │ │ P2P)     │ │ Brainz)  │ │           │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└─────────────────────────────────────────────────────────┘
```

## AI Skill 集成

将 MelodyMine 复制到 AI 助手的 skill 目录：

| 平台 | 路径 |
| :--- | :--- |
| WorkBuddy | `~/.workbuddy/skills/melodymine/` |
| OpenClaw | `~/.openclaw/workspace/skills/melodymine/` |
| Hermes | `~/.hermes/skills/melodymine/` |

然后用自然语言直接说：

```text
下载周杰伦的稻香，要无损音质
Download Blinding Lights by The Weeknd
下载这个 Spotify 链接 https://open.spotify.com/track/...
```

## 测试

```bash
# 运行全部 58 个测试
python -m pytest tests/ -v

# 运行特定测试模块
python -m unittest tests.test_new_clients -v
```

## 文件结构

```
MelodyMine/
├── scripts/
│   ├── music_helper.py        # CLI 入口 + 平台调度 + 下载管线
│   ├── melodymine_common.py   # 共享基础设施：Python/venv/pip/ffmpeg/代理检测
│   ├── metadata.py            # 多源元数据（MusicBrainz + 网易云 + iTunes）
│   ├── spotify_helper.py      # 高级 spotDL 操作（歌单同步、URL 解析）
│   ├── bili_client.py         # Bilibili WBI API 搜索（仅标准库）
│   ├── kuwo_client.py         # 酷我音乐搜索 + CDN 下载（仅标准库）
│   ├── audius_client.py       # Audius Web3 音乐搜索 + 串流（仅标准库）
│   ├── kugou_client.py        # 酷狗音乐搜索 + 下载（仅标准库）
│   ├── migu_client.py         # 咪咕音乐搜索 + 下载（仅标准库）
│   ├── netease_client.py      # 网易云音乐 API（仅标准库）
│   ├── ytmusic_client.py      # YouTube Music API 搜索（ytmusicapi）
│   ├── soulseek_client.py     # Soulseek P2P 搜索/下载（aioslsk）
│   ├── lyrics_client.py       # LRCLIB 歌词 API — 同步 + 普通（仅标准库）
│   ├── mbrainz_client.py      # MusicBrainz 元数据查询（仅标准库）
│   └── cover_client.py        # 封面下载（仅标准库）
├── tests/                     # 58 个单元测试（标准库 unittest + 模拟 HTTP）
├── .github/workflows/ci.yml   # GitHub Actions CI（ruff + pytest）
├── SKILL.md                   # AI 助手 Skill 定义
└── references/                # spotDL CLI & 配置参考文档
```

## 免责声明

MelodyMine 仅用于**个人学习和归档**。下载受版权保护的音频可能在您所在司法管辖区违法。请勿分发、分享或用于商业目的。您有责任遵守当地法律及各平台的服务条款。

本项目不托管、存储或传输任何受版权保护的内容，不绕过数字版权管理（DRM），与上述任何平台无关联或代言关系。

## 许可证

MIT
