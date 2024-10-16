import difflib
import os
import sys
import configparser
from pyarr.types import JsonArray, JsonObject

import lidarr
# import readarr
import slskd

class Soularr:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.lock_file_path: str = "" if self.is_docker() else os.path.join(os.getcwd(), ".soularr.lock")
        self.config_file_path: str = os.path.join(os.getcwd(), "/data/config.ini") if self.is_docker() else os.path.join(os.getcwd(), "config.ini")
        self.failure_file_path: str = os.path.join(os.getcwd(), "/data/failure_list.txt") if self.is_docker() else os.path.join(os.getcwd(), "failure_list.txt")
        self.current_page_file_path: str = os.path.join(os.getcwd(), "/data/.current_page.txt") if self.is_docker() else os.path.join(os.getcwd(), ".current_page.txt")
        self.check_duplicate_instances()
        self.check_config_file(self.config_file_path)
        self.lidarr_settings = self.config["Lidarr"]
        self.readarr_settings = self.config["Readarr"]
        self.slskd_settings = self.config["Slskd"]
        self.search_settings = self.config["Search Settings"]
        self.release_settings = self.config["Release Settings"]



    def is_docker() -> bool:
        return os.getenv('IN_DOCKER') is not None

    def check_config_file(self, path: str) -> None:
        if os.path.exists(path):
            self.config.read(path)
        else:
            if self.is_docker():
                print("Config file does not exist! Please mount \"/data\" and place your \"config.ini\" file there.")
            else:
                print("Config file does not exist! Please place it in the working directory.")
            print("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            if os.path.exists(self.lock_file_path) and not self.is_docker():
                os.remove(self.lock_file_path)
            sys.exit(0)

    def check_duplicate_instances(self) -> None:
        if os.path.exists(self.lock_file_path) and not self.is_docker():
            print("Soularr instance is already running.")
            sys.exit(1)
    


if __name__ == "__main__":
    soularr = Soularr()
    lidarr.Lidarr(
        soularr.lidarr_settings.get("host_url"),
        soularr.lidarr_settings.get("api_key"),
        soularr.lidarr_settings.get("download_dir"),
        soularr.release_settings.get("accepted_countries"),
        soularr.release_settings.get("accepted_formats"),
        soularr.release_settings.get("use_most_common_tracknum"),
        soularr.release_settings.get("allow_multi_disc")
    )
    slskd.Slskd(
        soularr.slskd_settings.get("host_url"),
        soularr.slskd_settings.get("api_key"),
        soularr.slskd_settings.get("download_dir"),
        soularr.search_settings.get("search_timeout"),
        soularr.search_settings.get("maximum_peer_queue"),
        soularr.search_settings.get("minimum_peer_upload_speed"),
        soularr.search_settings.get("allowed_filetypes"),
        soularr.search_settings.get("ignored_users"),
        soularr.search_settings.get("title_blacklist")
    )
    