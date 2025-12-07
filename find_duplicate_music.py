import os
import time
import json
from collections import defaultdict
from dataclasses import dataclass, asdict

import mutagen
import mutagen.wave

"""Config
Args:
    BASE_PATH: 查找该路径下的全部文件，默认为程序运行目录

    IGNORE_PATH: 需要忽略的目录列表（相对路径）

    IGNORE_MUSIC: 需要忽略的特定音乐标题列表

    COMPARE_LEVEL: 文件比较模式
        basic: 同时对比标题title和艺术家artist
            允许相同标题但不同艺术家的音乐文件存在
        strict: 仅比较标题(title)
            音乐标题相同即视为重复文件，不考虑艺术家artist

    SEARCH_NOT_TITLE_MUSIC (bool): 是否扫描非标准标题的音乐文件
        True: 包含没有标题元数据的音乐文件在扫描范围内(设定为None)
        False: 忽略没有标题元数据的音乐文件

    SAVE_DUPLICATE_DATA (bool): 是否保存检测到的重复音乐数据到文件
        True: 将重复数据写入文件
        False: 仅在控制台显示信息

    DATA_FILE_NAME: 重复数据存储的文件名

    SAVE_CACHE_FILE: 是否缓存数据信息(用于提高后续扫描效率)

    CACHE_FILE_NAME: 缓存数据存储的文件名

    SHOW_DUPLICATE_MUSIC_PATH (bool): 是否在输出中显示重复音乐的具体路径
        True: 显示音乐文件所在地完整路径
        False: 仅显示音乐标题
"""
BASE_PATH = os.path.abspath(os.path.dirname(__file__))
IGNORE_PATH = []
IGNORE_MUSIC = []
# basic or strict
COMPARE_LEVEL = "basic"
# COMPARE_LEVEL = "strict"
SEARCH_NOT_TITLE_MUSIC = True
SAVE_DUPLICATE_DATA = True
DATA_FILE_NAME = "duplicate_music.txt"
SAVE_CACHE_FILE = True
CACHE_FILE_NAME = "file_info.json"
SHOW_DUPLICATE_MUSIC_PATH = True

# init
STRICT_MODE: int = {"basic": 0, "strict": 1}.get(COMPARE_LEVEL.lower(), 1)
IGNORE_PATH: list[str] = [os.path.join(BASE_PATH, ignore) for ignore in IGNORE_PATH]
DATA_FILE_NAME: str = os.path.join(BASE_PATH, DATA_FILE_NAME)
CACHE_FILE_NAME: str = os.path.join(BASE_PATH, CACHE_FILE_NAME)
error_keys: list[str] = list()
file_info_cache: dict[str, dict[str, str | list[str]]] = dict()  # 文件缓存数据
file_info_dict: dict[str, dict[str, str | list[str]]] = dict()  # 运行缓存数据
title_and_path_dict: dict[str, list[str | tuple[list[str], str]]] = defaultdict(list)  # 音乐路径数据
duplicate_music: dict[str, list] = dict()  # 查重用

if os.path.exists(CACHE_FILE_NAME):
    with open(CACHE_FILE_NAME, "r", encoding="utf-8") as f:
        try:
            file_info_cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            print("Loadding cache fail, rebuild start")
            file_info_cache = file_info_cache


@dataclass
class FileInfo:
    file_path: str  # 文件路径
    file_name: str  # 文件名
    file_size_byte: int  # 字节
    file_size: str  # 文件大小
    creation_time: str  # 创建时间
    last_modified_time: str  # 最后修改时间
    last_access_time: str  # 最后访问时间
    music_title: str | None = None  # 音乐标题
    music_artist: list | None = None  # 音乐艺术家
    music_album: list | None = None # 音乐专辑

    @classmethod
    def get_file_info(cls, file_path: str) -> "FileInfo":
        try:
            file_stat = os.stat(file_path)

            return cls(
                file_path=file_path,
                file_name=os.path.basename(file_path),
                file_size_byte=file_stat.st_size,
                file_size=f"{file_stat.st_size / (1024 * 1024):.2f}MB",
                creation_time=time.ctime(file_stat.st_ctime),
                last_modified_time=time.ctime(file_stat.st_mtime),
                last_access_time=time.ctime(file_stat.st_atime),
            )

        except OSError:
            print(f"{file_path} get_file_info error")
            error_keys.append(file_path)
            return cls(*[file_path, file_path, 0, "0", "0", "0", "0"])

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __eq__(self, data) -> bool:
        if isinstance(data, dict):
            # 仅对比文件基础属性
            compare_keys = [
                "file_path",
                "file_name",
                "file_size_byte",
                "creation_time",
                "last_modified_time",
            ]

            for k in compare_keys:
                if getattr(self, k) != data.get(k):
                    return False
            return True

        else:
            return super().__eq__(data)


for root, dirs, files in os.walk(BASE_PATH):
    if root in IGNORE_PATH:
        # 清空dirs列表中止遍历子目录
        dirs[:] = []

    for file in files:
        file_path = os.path.join(root, file)
        file_info = FileInfo.get_file_info(file_path)

        if (cache_info := file_info_cache.get(file_path)) == file_info:
            if (
                (music_title :=  cache_info["music_title"])
                or cache_info["music_artist"]
                or cache_info["music_album"]
            ):
                music_title = music_title if music_title else None
                title_and_path_dict[music_title].append(
                    file_path
                    if STRICT_MODE
                    else (cache_info["music_artist"], file_path)
                )
            file_info_dict[file_path] = cache_info
            print(f"Get from cache: {file_path}")

        else:
            try:
                if (audio_info := mutagen.File(file_path)):
                    audio_info_keys_set = set(audio_info.keys())

                    # 处理一般音乐文件数据(flac等)
                    if bool(audio_info_keys_set & {"title", "artist", "album"}):
                        music_title = audio_info.get("title")
                        if music_title:
                            music_title = music_title[0]
                        music_artist = audio_info.get("artist")
                        music_album = audio_info.get("album")

                    # 处理ID3音乐文件数据(wav, mp3等)
                    if bool(audio_info_keys_set & {"TIT2", "TPE1", "TALB"}):
                        music_title = (
                            title.text[0] if (title := audio_info.get("TIT2")) else None
                        )
                        music_artist = (
                            artist.text[0] if (artist := audio_info.get("TPE1")) else None
                        )
                        music_album = (
                            album.text[0] if (album := audio_info.get("TALB")) else None
                        )

                    file_info.update(
                        music_title=music_title,
                        music_artist=music_artist,
                        music_album=music_album,
                    )

                    title_and_path_dict[music_title].append(
                        file_path
                        if STRICT_MODE
                        else (music_artist, file_path)
                    )

            except (KeyError, TypeError, AttributeError, mutagen.wave.error):
                print(f"Build file info error: {file_path}")
                error_keys.append(file_path)

            finally:
                file_info_dict[file_path] = asdict(file_info)
                print(f"Build file info: {file_path}")

# 处理重复信息
for title, path in title_and_path_dict.items():
    path_info: list[str | tuple[list, str]]
    if len(path_info := path) > 1 and title not in IGNORE_MUSIC:
        if STRICT_MODE:
            if title or SEARCH_NOT_TITLE_MUSIC:
                duplicate_music[title] = path_info
        else:
            temp_info_dict: dict[str, list] = defaultdict(list)
            for artist, p in path_info:
                artist = ", ".join(artist) if artist else None
                temp_info_dict[artist].append(p)
                if len(path_info := temp_info_dict[artist]) > 1:
                    if not(title or SEARCH_NOT_TITLE_MUSIC):
                        break
                    # basic模式下当音乐标题重复时才显示艺术家信息
                    if title in duplicate_music.keys():
                        duplicate_music[f"{temp_artist} - {title}"] = duplicate_music[title]
                        duplicate_music.pop(title)
                        duplicate_music[f"{artist} - {title}"] = path_info
                    else:
                        duplicate_music[title] = path_info
                        temp_artist = artist

duplicate_data: str = "\n".join(
    [
        f"{title}\n" + "\n".join([path for path in v]) + "\n"
        for title, v in duplicate_music.items()
    ]
    if SHOW_DUPLICATE_MUSIC_PATH
    else [title for title, _ in duplicate_music.items()]
)
print(duplicate_data)

if SAVE_DUPLICATE_DATA:
    with open(DATA_FILE_NAME, "w+", encoding="utf-8") as f:
        if duplicate_music:
            f.write(duplicate_data)

if SAVE_CACHE_FILE:
    with open(CACHE_FILE_NAME, "w+", encoding="utf-8") as f:
        json.dump(file_info_dict, f, ensure_ascii=False)
