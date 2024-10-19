import operator
import os
import re
import shutil
import sys
import configparser
import traceback

import lidarr
# import readarr
import slskd

class Soularr:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.lock_file_path: str = "" if self.is_docker() else os.path.join(os.getcwd(), ".soularr.lock")
        self.config_file_path: str = os.path.join(os.getcwd(), "/data/config.ini") if self.is_docker() else os.path.join(os.getcwd(), "config.ini")
        self.failure_file_path: str = os.path.join(os.getcwd(), "/data/failure_list.txt") if self.is_docker() else os.path.join(os.getcwd(), "failure_list.txt")
        self.current_page_file_path: str = os.path.join(os.getcwd(), "/data/.current_page.json") if self.is_docker() else os.path.join(os.getcwd(), ".current_page.json")
        self.check_duplicate_instances()
        self.create_lock_file()
        self.check_config_file(self.config_file_path)
        self.lidarr_settings = self.config["Lidarr"]
        is_lidarr_enabled = self.lidarr_settings.getboolean("enabled", True)
        self.readarr_settings = self.config["Readarr"]
        is_readarr_enabled = self.readarr_settings.getboolean("enabled", False)
        self.slskd_settings = self.config["Slskd"]
        self.search_settings = self.config["Search Settings"]
        self.release_settings = self.config["Release Settings"]
        self.remove_wanted_on_failure = self.search_settings.getboolean('remove_wanted_on_failure', True)

        self.slskd_instance = slskd.Slskd(
            self.slskd_settings.get("host_url"),
            self.slskd_settings.get("api_key"),
            self.slskd_settings.get("download_dir"),
            self.search_settings.getint("search_timeout", 5000),
            self.search_settings.getint("maximum_peer_queue", 50),
            self.search_settings.getint("minimum_peer_upload_speed", 0),
            self.search_settings.get("allowed_filetypes", "flac,mp3").split(","),
            self.search_settings.get("ignored_users").split(","),
            self.search_settings.get("title_blacklist").split(","),
            self.search_settings.get("search_type", "incrementing_page").lower().strip()
        )

        if is_lidarr_enabled:
            self.lidarr_instance = lidarr.Lidarr(
                self.lidarr_settings.get("host_url"),
                self.lidarr_settings.get("api_key"),
                self.lidarr_settings.get("download_dir"),
                self.release_settings.get("accepted_countries", "Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada").split(","),
                self.release_settings.get("accepted_formats", "CD,Digital Media,Vinyl").split(","),
                self.release_settings.getboolean("use_most_common_tracknum", True),
                self.release_settings.getboolean("allow_multi_disc", True),
                self.release_settings.getint("number_of_albums_to_grab", 10),
                self.search_settings.getboolean("album_prepend_artist", False),
                self.search_settings.getboolean("search_for_tracks", True)
            )
            self.lidarr_wanted_records = self.lidarr_instance.get_wanted_records()
            if len(self.lidarr_wanted_records) > 0:
                failed_downloads = self.lidarr_instance.grab_releases(self.slskd_instance, self.lidarr_wanted_records, self.failure_file_path)
                # TODO: can abstract
                self.slskd_instance.print_all_downloads()
                print(f"-------------------\nWaiting for downloads... monitor at: {self.slskd_instance.host_url}/downloads")
                grab_list: list[dict] = self.slskd_instance.monitor_downloads(self.lidarr_wanted_records)
                os.chdir(self.slskd_instance.download_dir)
                self.move_downloads(grab_list.sort(key=operator.itemgetter('creator')), self.lidarr_instance)
                self.lidarr_instance.import_downloads(next(os.walk('.'))[1])
                soularr.handle_downloads(failed_downloads)

        if is_readarr_enabled:
            pass
            # TODO
            # self.readarr_instance = readarr.Readarr()
            # self.readarr_wanted_records = self.readarr_instance.get_wanted_records()
            # if len(self.readarr_wanted_records) > 0:
                # 
            
        if not getattr(self, 'lidarr_wanted_records', None) and not getattr(self, 'readarr_wanted_records', None):
            print("No releases wanted. Exiting...")

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

    def create_lock_file(self) -> None:
        if not self.is_docker():
            with open(self.lock_file_path, "w") as lock_file:
                lock_file.write("locked")

    def remove_lock_file(self) -> None:
        if os.path.exists(self.lock_file_path) and not self.is_docker():
            os.remove(self.lock_file_path)
        sys.exit(0)
    
    def sanitize_folder_name(folder_name: str) -> str:
        valid_characters = re.sub(r'[<>:."/\\|?*]', '', folder_name)
        return valid_characters.strip()

    def handle_downloads(self, failed_downloads: int) -> None:
        if failed_downloads == 0:
            print("Solarr finished. Exiting...")
        else:
            e = f"{failed_downloads}: releases failed and were removed from wanted list. View \"failure_list.txt\" for list of failed albums." if self.remove_wanted_on_failure else f"{failed_downloads}: releases failed while downloading and are still wanted."
            print(e)
        self.slskd_instance.slskd.transfers.remove_completed_downloads()

    def move_downloads(self, grab_list: list[dict], arr_instance: object):
        for folder in grab_list:
            creator = folder['creator']
            dir = folder['dir']

            if folder['release']['mediumCount'] > 1:
                for filename in os.listdir(dir):
                    name = arr_instance.get_title(folder['release'])
                    arr_instance.retag_file(name, filename, os.path.join(dir, filename), folder)
                    new_dir = os.path.join(creator, self.sanitize_folder_name(name))

                    if not os.path.exists(creator):
                        os.mkdir(creator)
                    if not os.path.exists(new_dir):    
                        os.mkdir(new_dir)

                    shutil.move(os.path.join(dir, filename), new_dir)
                shutil.rmtree(dir)
            else:
                shutil.move(dir, creator)

if __name__ == "__main__":
    try:
        soularr = Soularr()
    except Exception:
        print(f"{traceback.format_exc()}\n Fatal error! Exiting...")
    finally:
        soularr.remove_lock_file()