import urllib.request
from bs4 import BeautifulSoup
import json
import os

# 获取目录
dir_path = os.getcwd()
# print(dir_path)
song_path = dir_path + "\\download_songs\\"
url_path = dir_path + "\\url.txt"


def get_json(url):
    data = urllib.request.urlopen(url.decode('ASCII')).read().decode('UTF-8')  # 爬取网页的响应数据，使用utf-8重新编码
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
    # f = urllib.request.urlopen(file_url, headers=ua_header)
    with open(song_path + file_name_normal, "wb") as code:
        code.write(f.read())
        print("下载成功")


def main():
    with open(url_path, "rb") as url_txt:
        urls = url_txt.read().splitlines()
        for url_meta in urls:
            print(url_meta)
            file_url_meta, file_name_normal_meta = get_json(url_meta)
            download_song(file_url_meta, file_name_normal_meta)
        # os.system("pause")


main()
