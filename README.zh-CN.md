# MelodyMine

[English](README.md)

从 Bilibili、YouTube、YouTube Music、Spotify 和 Soulseek（P2P）下载音乐，支持自动搜索、音频转换、元数据清理和零配置依赖安装。

MelodyMine 可以作为独立 CLI 运行，也可以作为 AI 助手的文件型 skill（WorkBuddy、Hermes 和 OpenClaw）。它会自动检测各平台自带的 Python 运行时（WorkBuddy/Hermes 自带；OpenClaw 用户需安装一次 Python），因此任何平台首次运行都只需要一条命令。

## 功能特性

- 中文音乐查询走 Bilibili，使用直连 WBI 搜索 + `yt-dlp`。
- 英文与国际音乐查询走 YouTube。
- 通过 `ytmusicapi` 搜索 YouTube Music 曲库（搜索无需 cookies）。
- 通过 spotDL 下载 Spotify URL。
- 通过 `aioslsk` 进行 Soulseek P2P 下载，支持多候选重试和 FLAC→MP3 回退。
- 零配置自动安装：自动检测宿主助手的 Python 运行时（WorkBuddy/Hermes 自带、uv 管理或系统 Python），安装 pip 包，并回退到 `imageio-ffmpeg` 获取 ffmpeg。
- 共享依赖层（`melodymine_common.py`）+ 统一虚拟环境：依赖只安装一次，即可在两个 helper 和所有支持的助手之间复用。
- 元数据清理：标题、艺术家、专辑、封面，并自动重命名为 `Artist - Title` 格式。
- 支持代理和 cookies，应对受限网络或 YouTube 机器人验证。

## 快速开始

在仓库或 skill 根目录下执行：

```bash
python scripts/music_helper.py setup
python scripts/music_helper.py download "周杰伦 稻香"
python scripts/music_helper.py download "The Weeknd Blinding Lights"
```

唯一的前置要求是 Python 3.10+。`setup` 命令会自动安装 MelodyMine 所需的 Python 包。

## 常用命令

下载中文歌曲（自动模式优先使用 Bilibili）：

```bash
python scripts/music_helper.py download "周杰伦 稻香"
```

下载英文歌曲（自动模式优先使用 YouTube）：

```bash
python scripts/music_helper.py download "The Weeknd Blinding Lights"
```

从 Spotify URL 下载：

```bash
python scripts/music_helper.py download "https://open.spotify.com/track/..."
```

从网易云音乐 URL 下载（先解析歌曲名，再走 Bilibili/YouTube）：

```bash
python scripts/music_helper.py download "https://music.163.com/song?id=185809"
```

从直接链接下载（YouTube / SoundCloud / Bandcamp）：

```bash
python scripts/music_helper.py download "https://www.youtube.com/watch?v=..."
python scripts/music_helper.py download "https://soundcloud.com/artist/song"
python scripts/music_helper.py download "https://artist.bandcamp.com/track/song"
```

只搜索不下载：

```bash
python scripts/music_helper.py search "周杰伦 稻香"
python scripts/music_helper.py search "The Weeknd" --platform youtube
```

强制指定平台：

```bash
python scripts/music_helper.py download "周杰伦 稻香" --platform bilibili
python scripts/music_helper.py download "The Weeknd Blinding Lights" --platform youtube
python scripts/music_helper.py download "Air Supply Complete" --platform soulseek
```

选择格式、码率、输出目录或搜索结果序号：

```bash
python scripts/music_helper.py download "周杰伦 稻香" --format flac --bitrate 320K
python scripts/music_helper.py download "稻香" --index 2
python scripts/music_helper.py download "Artist Song" --output "D:\Music"
```

当 YouTube 直接访问失败时使用代理：

```bash
python scripts/music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://HOST:PORT
```

当 YouTube 要求登录或机器人验证时使用 cookies：

```bash
python scripts/music_helper.py download "Artist Song" --cookies "D:\path\cookies.txt"
```

为已下载的文件更新元数据：

```bash
python scripts/music_helper.py meta "D:\Music\song.mp3"
python scripts/music_helper.py meta "D:\Music\song.mp3" --query "周杰伦 稻香"
```

检查依赖：

```bash
python scripts/music_helper.py check
```

## CLI 选项

```text
python scripts/music_helper.py download "query" [options]

选项：
  --platform {auto,bilibili,youtube,ytmusic,soulseek}
                                      默认：auto
  --format {auto,mp3,flac,m4a,opus,wav,vorbis}
                                      默认：auto（无损源输出 flac，否则 mp3 320K）
  --output PATH
  --proxy URL                         例如 socks5://host:port
  --cookies PATH                      用于 YouTube 验证的 cookies.txt
  --bitrate RATE                      例如 320K
  --index N                           搜索结果序号，从 1 开始
  --no-thumbnail
  --no-metadata
  --dry-run                           预览命令而不执行
  --json                              输出机器可读的 JSON
  --slsk-user USER                    Soulseek 用户名（或设置 SLSK_USERNAME 环境变量）
  --slsk-pass PASS                    Soulseek 密码（或设置 SLSK_PASSWORD 环境变量）

python scripts/music_helper.py meta "filepath" [options]

选项：
  --query QUERY                       元数据查询关键词（默认从文件名推断）
  --no-thumbnail                      跳过封面嵌入
  --json                              输出机器可读的 JSON
```

## 平台路由

| 输入 | 默认路由 | 说明 |
| --- | --- | --- |
| 中文查询 | Bilibili | 无需代理。如失败会回退到 YouTube。 |
| 英文或非中文查询 | YouTube | 先尝试直连；网络失败后再使用代理。 |
| Spotify URL | spotDL | 首次使用时会自动安装 spotDL。 |
| 网易云音乐 URL（`music.163.com`） | 网易云直连 → Bilibili/YouTube | 通过网易云 API 获取歌曲名。免费歌曲先尝试网易云 CDN 直连，版权受限时回退 Bilibili/YouTube。 |
| YouTube/SoundCloud/Bandcamp URL | yt-dlp 直连 | 无需搜索，直接下载 URL。YouTube 可能需要 `--proxy`。 |
| Soulseek P2P（`--platform soulseek`） | Soulseek 网络 | 直接从分享者搜索下载。需要设置 `SLSK_USERNAME` 和 `SLSK_PASSWORD` 环境变量。通过单一会话多候选重试下载。自动回退到 YouTube。代理自动从 `ALL_PROXY`/`HTTP_PROXY` 环境变量或常见 Clash 端口（7897/7890/1080）检测；会代理所有连接（服务器 + 节点）。 |
| 中文查询 → YouTube 失败 → Soulseek | 自动回退 | 当 Bilibili 和 YouTube 都失败时，会自动尝试 Soulseek。 |

## 高级 Spotify 操作

使用 `scripts/spotify_helper.py` 进行歌单同步、仅保存元数据、URL 解析或更新元数据：

```bash
python scripts/spotify_helper.py sync "https://open.spotify.com/playlist/..." --save-file playlist.spotdl
python scripts/spotify_helper.py save "https://open.spotify.com/album/..." --save-file album.spotdl
python scripts/spotify_helper.py url "Artist - Song"
python scripts/spotify_helper.py meta "D:\Music\song.mp3"
python scripts/spotify_helper.py meta "D:\Music\song.mp3" --query "Artist - Song"
```

spotDL 选项详情请参阅 `references/usage.md`，配置字段请参阅 `references/config.md`。

## 安装为 AI Skill

将此文件夹复制到助手的 skill 目录：

| 平台 | 示例路径 |
| --- | --- |
| WorkBuddy | `~/.workbuddy/skills/melodymine/` |
| OpenClaw | `~/.openclaw/workspace/skills/melodymine/` |
| Hermes | `~/.hermes/skills/melodymine/` |
| 自定义 | 助手扫描文件型 skill 的任意目录 |

> 运行时说明：WorkBuddy 和 Hermes 自带 Python，MelodyMine 会在首次运行时自动检测。OpenClaw 运行在 Node.js 上，**不自带 Python**，因此 OpenClaw 用户必须先从 python.org 安装 Python 3.10+，然后 `setup` 命令会找到它。

然后重启助手，用自然语言发出请求：

```text
下载周杰伦的稻香
Download Blinding Lights by The Weeknd
下载这个 https://open.spotify.com/track/...
```

助手会读取 `SKILL.md`，在需要时运行 setup，执行下载命令，并报告保存路径。

## 故障排除

| 问题 | 解决方案 |
| --- | --- |
| 找不到 Python | 从 python.org 安装 Python 3.10+，然后重新运行 setup。 |
| Bilibili `412 Precondition Failed` | 稍等几秒后重试；helper 内部已经重试一次。 |
| YouTube 超时 | 如有代理，使用 `--proxy socks5://HOST:PORT` 重试。 |
| YouTube 要求登录或机器人验证 | 将 YouTube cookies 导出为 cookies.txt，然后用 `--cookies PATH` 传入。 |
| Spotify `KeyError: 'uri'` | 改用歌曲名搜索，或在合适场景下使用 `spotify_helper.py --use-official-api`。 |
| 元数据错误 | 用更精确的 `Artist Song` 查询重试，或添加 `--no-metadata`。 |

## 文件结构

```text
MelodyMine/
├── SKILL.md
├── README.md
├── scripts/
│   ├── melodymine_common.py   # 共享基础设施：Python/venv/pip/ffmpeg/代理 检测
│   ├── music_helper.py       # 主 setup/search/download helper
│   ├── spotify_helper.py     # 高级 spotDL 操作
│   ├── soulseek_client.py    # Soulseek P2P 搜索/下载（aioslsk）
│   ├── bili_client.py        # Bilibili WBI API 搜索（仅标准库）
│   ├── netease_client.py     # 网易云音乐 API 客户端（仅标准库）
│   ├── ytmusic_client.py     # YouTube Music API 搜索（ytmusicapi）
│   ├── mbrainz_client.py     # MusicBrainz 元数据查询（仅标准库）
│   ├── cover_client.py       # 封面下载（仅标准库）
│   └── requirements.txt
├── tests/
│   ├── test_helpers.py       # 纯函数单元测试（标准库 unittest）
│   ├── test_api_clients.py   # API 客户端模块单元测试
│   ├── test_ytmusic_client.py# YouTube Music 搜索单元测试
│   └── test_soulseek_client.py # Soulseek 客户端 helper 单元测试
└── references/
    ├── usage.md              # spotDL CLI 参考
    └── config.md             # spotDL 配置参考
```

## 免责声明

MelodyMine 仅用于**个人学习和归档**。下载受版权保护的音频可能在您所在司法管辖区违法，无论意图如何。请勿分发、分享或 monetize 下载的文件。您有责任遵守当地法律以及 Bilibili、YouTube 和 Spotify 的服务条款。

本项目：
- 不托管、存储或传输任何受版权保护的内容，
- 不绕过数字版权管理（DRM），
- 与 Bilibili、YouTube、Spotify、网易云音乐、Apple 或 MusicBrainz 无关联或代言关系。

如果您是权利持有人并认为该工具促进了侵权行为，请提交 issue。维护者将配合处理。

## 许可证

MIT。详见 `LICENSE`。
