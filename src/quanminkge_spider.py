import urllib.request
from bs4 import BeautifulSoup
import json
import os


def mkdir(path):
  '''
  创建文件夹
  '''
  folder = os.path.exists(path)
  if not folder:  # 判断是否存在文件夹如果不存在则创建为文件夹
      print("---  创建新的文件夹😀  ---")
      os.makedirs(path)  # makedirs 创建文件时如果路径不存在会创建这个路径
      print("---  OK 🚩 ---")
  else:
      print("--- ⚠️ 文件夹已存在!  ---")


# 获取目录
dir_path = os.getcwd()
# print(dir_path)
song_path = dir_path + "/download_songs/"


def get_json(url):
    # data = urllib.request.urlopen(url.decode('ASCII')).read().decode('UTF-8')  # 爬取网页的响应数据，使用utf-8重新编码
    data = urllib.request.urlopen(url).read().decode('UTF-8')  # 爬取网页的响应数据，使用utf-8重新编码
    soup = BeautifulSoup(data, "lxml")  # 返回BeautifulSoup对象，使用lxml解析器
    target_info_str = str(soup.findAll('script')[2].get_text())[18:-2]  # 找到对应我们目标标签中的json内容
    json_dic = json.loads(target_info_str)  # 将json信息转化为python字典
    # json格式化后转化为字符串
    dumped_json_data = json.dumps(json_dic, sort_keys=True, indent=4, separators=(',', ':'), ensure_ascii=False)
    file_url = json_dic['detail']['playurl']
    # 先获取用户昵称
    user_name = json_dic['detail']['nick']
    # 再获取歌曲名称
    song_name = json_dic['detail']['song_name']
    # 得到默认文件名
    file_name_normal = song_name + ".m4a"
    # 打印默认文件名
    print(file_name_normal)
    # 返回参数
    return file_url, file_name_normal


def download_song(file_url, file_name_normal):
    # 下载文件到main.py同级目录
    print("下载中")
    ua_header = {"User-Agent": "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0;"}

    request = urllib.request.Request(url=file_url, headers=ua_header)
    f = urllib.request.urlopen(request)

    mkdir(song_path)
    with open(song_path + file_name_normal, "wb") as code:
        code.write(f.read())
        print("下载成功")


def main():
    urls = [
        "https://node.kg.qq.com/play?s=qCrUWbqtXTSCdqR5&shareuid=659b9882232b348236&topsource=a0_pn201001003_z11_u765766392_l1_t1648449575__&chain_share_id=_UGWekeQ_P2Xgdme-tM5rSnxKZ_deDOmKWeHyZ1f1jM&pageId=details_of_creations",
        "https://node.kg.qq.com/play?s=plecG_pUd1WQ5p6-&shareuid=659b9882232b348236&topsource=a0_pn201001003_z11_u765766392_l1_t1648462554__&chain_share_id=_UGWekeQ_P2Xgdme-tM5rSnxKZ_deDOmKWeHyZ1f1jM&pageId=details_of_creations"
    ]
    for url_meta in urls:
        print(url_meta)
        file_url_meta, file_name_normal_meta = get_json(url_meta)
        download_song(file_url_meta, file_name_normal_meta)


if __name__ == '__main__':
    main()
