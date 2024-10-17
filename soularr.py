import os
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

        if is_readarr_enabled:
            # self.readarr_instance = readarr.Readarr()
            pass

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
    
    def handle_downloads(self, failed_downloads: int) -> None:
        if failed_downloads == 0:
            print("Solarr finished. Exiting...")
        else:
            e = f"{failed_downloads}: releases failed and were removed from wanted list. View \"failure_list.txt\" for list of failed albums." if self.remove_wanted_on_failure else f"{failed_downloads}: releases failed while downloading and are still wanted."
            print(e)
        self.slskd_instance.slskd.transfers.remove_completed_downloads()

if __name__ == "__main__":
    try:
        soularr = Soularr()
        if len(soularr.lidarr_wanted_records) > 0:
            failed_downloads = soularr.lidarr_instance.grab_releases(soularr.slskd_instance, soularr.lidarr_wanted_records, soularr.failure_file_path)
            soularr.slskd_instance.print_all_downloads()
            print(f"-------------------\nWaiting for downloads... monitor at: {soularr.slskd_instance.host_url}/downloads")
            soularr.slskd_instance.monitor_downloads(soularr.lidarr_wanted_records)


            soularr.handle_downloads(failed_downloads)
        if len(soularr.readarr_wanted_records) > 0:
            failed_downloads = soularr.readarr_instance.grab_releases(soularr.readarr_wanted_records)
            soularr.handle_downloads(failed_downloads)
        if len(soularr.lidarr_wanted_records) == 0 and len(soularr.readarr_wanted_records) == 0:
            print("No releases wanted. Exiting...")
    except Exception:
        print(f"{traceback.format_exc()}\n Fatal error! Exiting...")
    finally:
        soularr.remove_lock_file()