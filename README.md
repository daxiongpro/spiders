# 爬虫集合

本项目汇总一些爬虫，目前已经包含：全民k歌歌曲、小红书图片爬取（无水印）

## 使用方法：

### 全民k歌

* 打开 `src/quanminkge_spider.py`。
* 修改 `urls`。
* 运行程序。

```bash
python src/quanminkge_spider.py
```

> 歌曲会下载到 download_songs 文件夹内。

### 小红书

获取自己的 `cookies` ：

* 打开小红书网站的某个帖子：`https://www.xiaohongshu.com/explore/63974cc9000000001f0134b4`
* 登录小红书账号
* 游览器按 `F12`。
* 点击“网络”。
* ctrl+F 输入 `cookie`，复制随便一个包的 cookie 。

修改小红书爬虫 `urls` 和 `cookies` ：

* 打开 `src/redbook_spider.py`。
* 修改 `urls`。
* 修改自己的 `cookies`。

运行程序：

```bash
python src/redbook_spider.py
```

> 图片会下载到 `images/` 文件夹。

## 致谢：

[全民k歌](https://github.com/zzxzzk115/kgqqDownloader)
[小红书](https://github.com/littlePig-zzf/python-demo)
