import json
import math
import os
import shutil
import time
from datetime import datetime

from pyarr.types import JsonArray, JsonObject

from applications import Applications


class Arrs(Applications):
    """Arrs class handles operations required for *arr applications."""

    def __init__(
        self,
        application_settings: tuple[str, str, str],
        current_page_file_path: str,
        title_blacklist: list[str],
        page_size: int,
        search_type: str,
        prepend_creator: bool,
        remove_wanted_on_failure: bool,
    ) -> None:
        """Initialize the class with the specified settings.

        Args:
            application_settings (tuple[str, str, str]): A tuple containing the application settings (host_url, api_key, download_dir).
            current_page_file_path (str): The file path to the current page.
            title_blacklist (list[str]): A list of titles to be blacklisted.
            page_size (int): The size of the page.
            search_type (str): The type of search to be performed.
            prepend_creator (bool): Whether to prepend the creator's name.
            remove_wanted_on_failure (bool): Whether to remove wanted items on failure.

        """
        super().__init__(self.__class__.__name__.lower(), application_settings)
        self.current_page_file_path = current_page_file_path
        self.application = self.__class__.__name__.lower()
        self.title_blacklist = title_blacklist
        self.page_size = page_size
        self.search_type = search_type
        self.prepend_creator = prepend_creator
        self.remove_wanted_on_failure = remove_wanted_on_failure

    def get_wanted(self, page: int = 1) -> JsonObject:
        """Retrieve the wanted items for the specified page.

        Args:
            page (int): The page number to retrieve. Defaults to 1.

        Returns:
            JsonObject: The wanted items for the specified page.

        """
        raise NotImplementedError(f"get_wanted must be implemented in {self.__class__.__name__}")

    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        """Retag a file with the specified release name and folder information.

        Args:
            release_name (str): The name of the release.
            filename (str): The name of the file.
            path (str): The path to the file.
            folder (dict): The folder information.

        """
        raise NotImplementedError(f"retag_file must be implemented in {self.__class__.__name__}")

    def import_downloads(self, creator_folders: list[str]) -> None:
        """Import downloads from the specified creator folders.

        Args:
            creator_folders (list[str]): A list of creator folders to import downloads from.

        """
        raise NotImplementedError(f"import_downloads must be implemented in {self.__class__.__name__}")

    def get_command(self, id: int) -> dict:
        """Retrieve the command with the specified ID.

        Args:
            id (int): The ID of the command to retrieve.

        Returns:
            dict: The command details.

        """
        raise NotImplementedError(f"get_command must be implemented in {self.__class__.__name__}")

    def is_blacklisted(self, title: str) -> bool:
        """Check if the given title is blacklisted.

        Args:
            title (str): The title to check.

        Returns:
            bool: True if the title is blacklisted, False otherwise.

        """
        for word in self.title_blacklist:
            if word != "" and word in title.lower():
                print(f"Skipping {title} due to blacklisted word: {word}")
                return True
        return False

    def get_current_pages(self) -> dict:
        """Retrieve the current pages from the file.

        Returns:
            dict: The current pages data.

        """
        if os.path.exists(self.current_page_file_path):
            try:
                with open(self.current_page_file_path) as file:
                    return json.load(file)
            except json.JSONDecodeError:
                pass
        else:
            with open(self.current_page_file_path, "w") as file:
                json.dump({"lidarr": 1, "readarr": 1}, file)

        return {"lidarr": 1, "readarr": 1}

    def update_current_page(self, data: dict) -> None:
        """Update the current page data.

        Args:
            data (dict): The data to update the current page with.

        """
        with open(self.current_page_file_path, "w") as file:
            json.dump(data, file)

    def get_wanted_records(self) -> list[JsonObject]:
        """Retrieve the wanted records based on the search type.

        Returns:
            list[JsonObject]: A list of wanted records.

        """
        wanted: JsonObject = self.get_wanted()
        total_wanted: int = wanted["totalRecords"]
        if self.search_type == "all":
            page = 1
            wanted_records: list[JsonObject] = []
            while len(wanted_records) < total_wanted:
                wanted = self.get_wanted(page)
                wanted_records.extend(wanted["records"])
                page += 1

        elif self.search_type == "incrementing_page":
            page_data = self.get_current_pages()
            page = page_data[self.application]
            wanted_records = self.get_wanted(page)["records"]
            page = 1 if page >= math.ceil(total_wanted / self.page_size) else page + 1
            page_data[self.application] = page
            self.update_current_page(page_data)

        elif self.search_type == "first_page":
            wanted_records = wanted["records"]

        else:
            raise ValueError(f"Error: [Search Settings] - search_type = {self.search_type} is not valid.")

        return wanted_records

    def grab_releases(self, slskd_instance: object, arr_instance: object, wanted_records: JsonArray, failure_file_path: str) -> tuple[int, list[dict]]:
        """Attempt to grab releases from the specified arr instance and download them using the slskd instance.

        Args:
            slskd_instance (object): The instance of the slskd client used for searching and downloading.
            arr_instance (object): The instance of the arr application (e.g., Lidarr, Readarr) from which to grab releases.
            wanted_records (JsonArray): A JSON array of records that are wanted for download.
            failure_file_path (str): The file path where failed download attempts will be logged.

        Returns:
            tuple[int, list[dict]]: A tuple containing the number of failed downloads and a list of successfully grabbed records.

        Raises:
            ValueError: If the arr instance type is not valid.

        """
        failed_downloads = 0
        records_grabbed = []
        arr_name = arr_instance.__class__.__name__.lower()
        for record in wanted_records:
            if arr_name == "lidarr":
                (query, all_tracks, creator_name, release) = self.grab_album(record)
            elif arr_name == "readarr":
                (query, creator_name, book_title) = self.grab_book(record)
            else:
                raise ValueError(f"Error: {arr_name} is not a valid arr type.")

            if query is not None:
                print(f"Searching {arr_name}: {query}")
                if arr_name == "lidarr":
                    (success, grab_list) = slskd_instance.search_and_download(query, creator_name, "", all_tracks, all_tracks[0], release)
                elif arr_name == "readarr":
                    (success, grab_list) = slskd_instance.search_and_download(query, creator_name, book_title)
                records_grabbed.extend(grab_list)
            else:
                success = False

            if arr_name == "lidarr" and not success and self.search_for_tracks:
                tracks = self.grab_tracks(release, all_tracks)
                for track in tracks:
                    query = self.grab_track(track, creator_name)
                    if query is None:
                        continue
                    print(f"Searching track: {query}")
                    (success, grab_list) = slskd_instance.search_and_download(query, creator_name, tracks, track, release)
                    records_grabbed.extend(grab_list)
                    if success:
                        break

                    if not success:
                        if self.remove_wanted_on_failure:
                            print(
                                f"ERROR: Failed to grab {arr_name}: {record['title']} for creator: {creator_name}\n"
                                'Failed item removed from wanted list and added to "failure_list.txt"',
                            )
                            record["monitored"] = False
                            arr_instance.upd_item(record)
                            timestamp = datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                            with open(failure_file_path, "a") as file:
                                file.write(f"{timestamp} - {creator_name}, {record['title']}, {record['id']}\n")
                        else:
                            print(f"ERROR: Failed to grab {arr_name}: {record['title']} for creator: {creator_name}")
                        failed_downloads += 1
            success = False
        return (failed_downloads, records_grabbed)

    # TODO: Add timeout to prevent permanent hanging
    def monitor_import_commands(self, import_commands: list[JsonObject]) -> None:
        """Monitor the import commands until all are completed.

        Args:
            import_commands (list[JsonObject]): A list of import commands to monitor.

        """
        while True:
            completed_count = 0
            for task in import_commands:
                current_task = self.get_command(task["id"])
                if current_task["status"] == "completed":
                    completed_count += 1
            if completed_count == len(import_commands):
                break
            time.sleep(2)

    def process_import_task(self, current_task: dict) -> None:
        """Process the current import task and handle any failures.

        Args:
            current_task (dict): The current task to process.

        """
        try:
            print(f"{current_task['commandName']} {current_task['message']} from: {current_task['body']['path']}")
            if "Failed" in current_task["message"]:
                self.move_failed_import(current_task["body"]["path"])
        except KeyError:
            print("Error printing arr task message. Printing full unparsed message.")
            print(current_task)

    def move_failed_import(self, src_path: str) -> None:
        """Move the failed import to the 'failed_imports' directory.

        Args:
            src_path (str): The source path of the failed import.

        """
        failed_imports_dir = f"failed_imports_{self.__class__.__name__.lower()}"
        counter = 1
        if not os.path.exists(failed_imports_dir):
            os.makedirs(failed_imports_dir)
        folder_name = os.path.basename(src_path)
        target_path = os.path.join(failed_imports_dir, folder_name)

        while os.path.exists(target_path):
            target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
            counter += 1
        if os.path.exists(folder_name) and folder_name != failed_imports_dir:
            shutil.move(folder_name, target_path)
            print(f"Failed import moved to: {target_path}")
