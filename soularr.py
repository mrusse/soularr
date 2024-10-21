import configparser
import operator
import os
import re
import shutil
import sys
import traceback

import lidarr
import readarr
import slskd


class Soularr:
    """Soularr class handles the configuration, initialization, and execution of arr instances to download and manage media files using Slskd."""

    def __init__(self) -> None:
        """Initialize the Soularr instance, sets up configurations, starts the search and download process."""
        try:
            self.config = configparser.ConfigParser()
            self.lock_file_path: str = "" if self.is_docker() else os.path.join(os.getcwd(), ".soularr.lock")
            self.config_file_path: str = os.path.join(os.getcwd(), "/data/config.ini") if self.is_docker() else os.path.join(os.getcwd(), "config.ini")
            self.failure_file_path: str = (
                os.path.join(os.getcwd(), "/data/failure_list.txt") if self.is_docker() else os.path.join(os.getcwd(), "failure_list.txt")
            )
            self.current_page_file_path: str = (
                os.path.join(os.getcwd(), "/data/.current_page.json") if self.is_docker() else os.path.join(os.getcwd(), ".current_page.json")
            )
            self.check_duplicate_instances()
            self.create_lock_file()
            self.check_config_file(self.config_file_path)
            try:
                self.lidarr_settings = self.config["Lidarr"]
                is_lidarr_enabled = self.lidarr_settings.getboolean("enabled", True)
            except KeyError:
                is_lidarr_enabled = False
                print("Lidarr settings not found in config file.")
            try:
                self.readarr_settings = self.config["Readarr"]
                is_readarr_enabled = self.readarr_settings.getboolean("enabled", True)
            except KeyError:
                is_readarr_enabled = False
                print("Readarr settings not found in config file.")
            self.slskd_settings = self.config["Slskd"]
            self.search_settings = self.config["Search Settings"]
            self.release_settings = self.config["Release Settings"]
            self.remove_wanted_on_failure = self.search_settings.getboolean("remove_wanted_on_failure", True)

            self.slskd_instance = slskd.Slskd(
                (self.slskd_settings.get("host_url"), self.slskd_settings.get("api_key"), self.slskd_settings.get("download_dir")),
                self.search_settings.getint("search_timeout", 5000),
                self.search_settings.getint("maximum_peer_queue", 50),
                self.search_settings.getint("minimum_peer_upload_speed", 0),
                self.search_settings.get("allowed_filetypes", "flac,mp3").split(","),
                self.search_settings.get("readarr_allowed_filetypes", "epub,mobi").split(","),
                self.search_settings.get("ignored_users").split(","),
                self.remove_wanted_on_failure,
            )

            if is_lidarr_enabled:
                self.lidarr_instance = lidarr.Lidarr(
                    (self.lidarr_settings.get("host_url"), self.lidarr_settings.get("api_key"), self.lidarr_settings.get("download_dir")),
                    self.current_page_file_path,
                    self.release_settings.get("accepted_countries", "Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada").split(","),
                    self.release_settings.get("accepted_formats", "CD,Digital Media,Vinyl").split(","),
                    self.search_settings.get("title_blacklist").split(","),
                    self.release_settings.getboolean("use_most_common_tracknum", True),
                    self.release_settings.getboolean("allow_multi_disc", True),
                    self.search_settings.getint("number_of_albums_to_grab", 10),
                    self.search_settings.get("search_type", "incrementing_page").lower().strip(),
                    self.search_settings.getboolean("album_prepend_artist", False),
                    self.search_settings.getboolean("search_for_tracks", True),
                    self.remove_wanted_on_failure,
                )
                self.lidarr_wanted_records = self.process_wanted_records(self.lidarr_instance)

            if is_readarr_enabled:
                self.readarr_instance = readarr.Readarr(
                    (self.readarr_settings.get("host_url"), self.readarr_settings.get("api_key"), self.readarr_settings.get("download_dir")),
                    self.current_page_file_path,
                    self.search_settings.get("readarr_title_blacklist", "").split(","),
                    self.search_settings.getint("number_of_books_to_grab", 10),
                    self.search_settings.get("search_type", "incrementing_page").lower().strip(),
                    self.search_settings.getboolean("book_prepend_author", False),
                    self.remove_wanted_on_failure,
                )
                self.readarr_wanted_records = self.process_wanted_records(self.readarr_instance)

            if not getattr(self, "lidarr_wanted_records", None) and not getattr(self, "readarr_wanted_records", None):
                print("No releases wanted. Exiting...")

        except Exception:
            print(f"{traceback.format_exc()}\n Fatal error! Exiting...")
        finally:
            self.remove_lock_file()

    def is_docker(self) -> bool:
        """Check if the application is running inside a Docker container.

        Returns:
            bool: True if the application is running inside a Docker container, False otherwise.

        """
        return os.getenv("IN_DOCKER") is not None

    def check_config_file(self, path: str) -> None:
        """Check if the configuration file exists and read it, otherwise print an error message and quit.

        Args:
            path (str): The path to the configuration file.

        """
        if os.path.exists(path):
            self.config.read(path)
        else:
            if self.is_docker():
                print('Config file does not exist! Please mount "/data" and place your "config.ini" file there.')
            else:
                print("Config file does not exist! Please place it in the working directory.")
            print("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            self.remove_lock_file()

    def check_duplicate_instances(self) -> None:
        """Check an instance of Soularr is already running, quit if so."""
        if os.path.exists(self.lock_file_path) and not self.is_docker():
            print("Soularr instance is already running.")
            sys.exit(1)

    def create_lock_file(self) -> None:
        """Create a lock file to prevent duplicate instances."""
        if not self.is_docker():
            with open(self.lock_file_path, "w") as lock_file:
                lock_file.write("locked")

    def remove_lock_file(self) -> None:
        """Remove the lock file to allow new instances to run."""
        if os.path.exists(self.lock_file_path) and not self.is_docker():
            os.remove(self.lock_file_path)
        sys.exit(0)

    def sanitize_folder_name(self, folder_name: str) -> str:
        """Sanitize the folder name by removing invalid characters.

        Args:
            folder_name (str): The folder name to sanitize.

        Returns:
            str: The sanitized folder name.

        """
        valid_characters = re.sub(r'[<>:."/\\|?*]', "", folder_name)
        return valid_characters.strip()

    def process_wanted_records(self, arr_instance: object) -> list[dict]:
        """Process the wanted records for the given arr instance.

        Args:
            arr_instance (object): The arr instance to process wanted records for.

        Returns:
            list[dict]: A list of wanted records.

        """
        wanted_records = arr_instance.get_wanted_records()
        if len(wanted_records) > 0:
            (failed_downloads, grab_list) = arr_instance.grab_releases(self.slskd_instance, arr_instance, wanted_records, self.failure_file_path)
            grab_list.sort(key=operator.itemgetter("creator"))
            if len(grab_list) > 0:
                self.slskd_instance.print_all_downloads()
                print(f"-------------------\nWaiting for downloads... monitor at: {self.slskd_instance.host_url}/downloads")
                self.slskd_instance.monitor_downloads(grab_list)
                os.chdir(self.slskd_instance.download_dir)
                self.move_downloads(grab_list, arr_instance.__class__.__name__.lower())
                arr_instance.import_downloads(next(os.walk("."))[1])
                self.handle_downloads(failed_downloads)
            else:
                print("No suitable releases found for downloading.")
        return wanted_records

    def handle_downloads(self, failed_downloads: int) -> None:
        """Handle the downloads and print the status of failed downloads.

        Args:
            failed_downloads (int): The number of failed downloads.

        """
        if failed_downloads == 0:
            print("Solarr finished. Exiting...")
        else:
            e = (
                f'{failed_downloads}: releases failed and were removed from wanted list. View "failure_list.txt" for list of failed operations.'
                if self.remove_wanted_on_failure
                else f"{failed_downloads}: releases failed while downloading and are still wanted."
            )
            print(e)
        self.slskd_instance.slskd.transfers.remove_completed_downloads()

    def move_downloads(self, grab_list: list[dict], arr_type: str) -> None:
        """Move the downloaded files to their respective directories.

        Args:
            grab_list (list[dict]): List of downloaded items.
            arr_type (str): Type of arr instance (e.g., 'lidarr').

        """
        for folder in grab_list:
            creator = folder["creator"]
            dir = folder["dir"]
            if arr_type == "lidarr" and folder["release"]["mediumCount"] > 1:
                for filename in os.listdir(dir):
                    name = self.lidarr_instance.get_album(albumIds=folder["release"]["albumId"])["title"]
                    path = os.path.join(dir, filename)
                    self.lidarr_instance.retag_file(name, filename, path, folder)
                    new_dir = os.path.join(creator, self.sanitize_folder_name(name))

                    if not os.path.exists(creator):
                        os.mkdir(creator)
                    if not os.path.exists(new_dir):
                        os.mkdir(new_dir)
                    if os.path.exists(new_dir) and os.path.exists(path):
                        shutil.move(path, new_dir)
                shutil.rmtree(dir)
            elif os.path.exists(creator) and os.path.exists(dir):
                shutil.move(dir, creator)


if __name__ == "__main__":
    soularr = Soularr()
