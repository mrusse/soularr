import os
import sys
import configparser

import lidarr
# import readarr
import slskd

class Soularr:
    def __init__(self):
        if not self.is_docker():
            with open(self.lock_file_path, "w") as lock_file:
                lock_file.write("locked")

        self.config = configparser.ConfigParser()
        self.lock_file_path: str = "" if self.is_docker() else os.path.join(os.getcwd(), ".soularr.lock")
        self.config_file_path: str = os.path.join(os.getcwd(), "/data/config.ini") if self.is_docker() else os.path.join(os.getcwd(), "config.ini")
        self.failure_file_path: str = os.path.join(os.getcwd(), "/data/failure_list.txt") if self.is_docker() else os.path.join(os.getcwd(), "failure_list.txt")
        self.current_page_file_path: str = os.path.join(os.getcwd(), "/data/.current_page.json") if self.is_docker() else os.path.join(os.getcwd(), ".current_page.json")
        self.check_duplicate_instances()
        self.check_config_file(self.config_file_path)
        self.lidarr_settings = self.config["Lidarr"]
        self.readarr_settings = self.config["Readarr"]
        self.slskd_settings = self.config["Slskd"]
        self.search_settings = self.config["Search Settings"]
        self.release_settings = self.config["Release Settings"]
        self.remove_wanted_on_failure = self.search_settings.getboolean('remove_wanted_on_failure', True)




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
        soularr.release_settings.get("accepted_countries", "Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada").split(","),
        soularr.release_settings.get("accepted_formats", "CD,Digital Media,Vinyl").split(","),
        soularr.release_settings.getboolean("use_most_common_tracknum", True),
        soularr.release_settings.getboolean("allow_multi_disc", True),
        soularr.release_settings.getint("number_of_albums_to_grab", 10)
    )
    slskd.Slskd(
        soularr.slskd_settings.get("host_url"),
        soularr.slskd_settings.get("api_key"),
        soularr.slskd_settings.get("download_dir"),
        soularr.search_settings.getint("search_timeout", 5000),
        soularr.search_settings.getint("maximum_peer_queue", 50),
        soularr.search_settings.getint("minimum_peer_upload_speed", 0),
        soularr.search_settings.get("allowed_filetypes", "flac,mp3").split(","),
        soularr.search_settings.get("ignored_users").split(","),
        soularr.search_settings.get("title_blacklist").split(","),
        soularr.search_settings.get("search_type", "incrementing_page").lower().strip()
    )