import difflib
import os
import shutil
import time

from pyarr.types import JsonArray, JsonObject

from applications import Applications


class Slskd(Applications):
    """Slskd class handles the interaction with the Soulseek client, managing searches, downloads, and processing of results."""

    def __init__(
        self,
        application_settings: tuple[str, str, str],
        search_timeout: int,
        maximum_peer_queue: int,
        minimum_peer_upload_speed: int,
        allowed_filetypes: list[str],
        readarr_allowed_filetypes: list[str],
        ignored_users: list[str],
        remove_wanted_on_failure: bool,
    ) -> None:
        """Initialize the Slskd class with the given settings.

        Args:
            application_settings (tuple[str, str, str]): A tuple containing the application settings (host_url, api_key, download_dir).
            search_timeout (int): The search timeout value.
            maximum_peer_queue (int): The maximum peer queue length.
            minimum_peer_upload_speed (int): The minimum peer upload speed.
            allowed_filetypes (list[str]): A list of allowed filetypes for Lidarr.
            readarr_allowed_filetypes (list[str]): A list of allowed filetypes for Readarr.
            ignored_users (list[str]): A list of ignored users.
            remove_wanted_on_failure (bool): Whether to remove wanted items on failure.

        """
        super().__init__(application_settings)
        self.search_timeout = search_timeout
        self.maximum_peer_queue = maximum_peer_queue
        self.minimum_peer_upload_speed = minimum_peer_upload_speed
        self.allowed_filetypes = allowed_filetypes
        self.readarr_allowed_filetypes = readarr_allowed_filetypes
        self.ignored_users = ignored_users
        self.remove_wanted_on_failure = remove_wanted_on_failure

    def get_tracks_info(self, files: dict) -> dict:
        """Get information about the tracks in the given files.

        Args:
            files (dict): A dictionary containing file information.

        Returns:
            dict: A dictionary with the count of valid tracks and the common filetype.

        """
        count = 0
        index = -1
        filetype = ""
        for file in files:
            if file["filename"].split(".")[-1] in self.allowed_filetypes:
                new_index = self.allowed_filetypes.index(file["filename"].split(".")[-1])
                if index == -1:
                    index = new_index
                    filetype = self.allowed_filetypes[index]
                elif new_index != index:
                    filetype = ""
                    break
                count += 1
        return {"count": count, "filetype": filetype}

    def is_lidarr_track_in_slskd_tracks(self, lidarr_track: JsonObject, slskd_tracks: dict, filetype: str) -> tuple[bool, float]:
        """Check if a Lidarr track is present in the Soulseek tracks.

        Args:
            lidarr_track (JsonObject): The Lidarr track to check.
            slskd_tracks (dict): The Soulseek tracks to compare against.
            filetype (str): The filetype of the tracks.

        Returns:
            tuple[bool, float]: A tuple containing a boolean indicating if a match was found and the best match ratio.

        """
        lidarr_filename: str = lidarr_track["title"] + filetype
        best_match: float = 0.0
        MATCH_THRESHOLD = 0.5

        for slskd_track in slskd_tracks:
            slskd_filename: str = slskd_track["filename"]
            ratio: float = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            # If ratio is a bad match try and split off the garbage at the start of the slskd_filename and try again
            if ratio < MATCH_THRESHOLD:
                lidarr_filename_word_count: int = len(lidarr_filename.split()) * -1
                truncated_slskd_filename: str = " ".join(slskd_filename.split()[lidarr_filename_word_count:])
                ratio = difflib.SequenceMatcher(None, lidarr_filename, truncated_slskd_filename).ratio()
            best_match = max(ratio, best_match)
        return best_match > MATCH_THRESHOLD, best_match

    def is_album_match(self, lidarr_tracks: JsonArray, slskd_tracks: dict, username: str, filetype: str) -> bool:
        """Check if an album matches between Lidarr tracks and Soulseek tracks.

        Args:
            lidarr_tracks (JsonArray): The Lidarr tracks to check.
            slskd_tracks (dict): The Soulseek tracks to compare against.
            username (str): The username of the Soulseek user.
            filetype (str): The filetype of the tracks.

        Returns:
            bool: True if an album match is found, False otherwise.

        """
        counted: list[str] = []
        total_match: float = 0.0
        for lidarr_track in lidarr_tracks:
            is_match, best_match = self.is_lidarr_track_in_slskd_tracks(lidarr_track, slskd_tracks, filetype)
            if is_match:
                counted.append(lidarr_track["title"])
                total_match += best_match
        if len(counted) == len(lidarr_tracks) and username not in self.ignored_users:
            print(
                f"\nFound match from user: {username} for {len(counted)} tracks! "
                f"\nAverage sequence match ratio: {total_match/len(counted)} "
                f"\nSUCCESSFUL MATCH \n-------------------",
            )
            return True
        return False

    def cancel_and_delete(self, delete_dir: str, username: str, files: dict) -> None:
        """Cancel and delete the specified downloads.

        Args:
            delete_dir (str): The directory to delete.
            username (str): The username associated with the downloads.
            files (dict): A dictionary containing file information.

        """
        for file in files:
            self.slskd.transfers.cancel_download(username=username, id=file["id"])
        os.chdir(self.download_dir)
        if os.path.exists(delete_dir):
            shutil.rmtree(delete_dir)

    def initiate_search(self, query: str) -> dict:
        """Initiate a search with the given query.

        Args:
            query (str): The search query.

        Returns:
            dict: The search results.

        """
        return self.slskd.searches.search_text(
            searchText=query,
            searchTimeout=self.search_timeout,
            filterResponses=True,
            maximumPeerQueueLength=self.maximum_peer_queue,
            minimumPeerUploadSpeed=self.minimum_peer_upload_speed,
        )

    def wait_for_search_completion(self, search: dict) -> None:
        """Wait for the search to complete.

        Args:
            search (dict): The search dictionary containing search details.

        """
        while True:
            if self.slskd.searches.state(search["id"])["state"] != "InProgress":
                break
            time.sleep(1)

    def process_search_results(self, search: dict, creator_name: str, tracks: JsonArray, track: JsonObject, release: JsonObject) -> tuple[bool, list[dict]]:
        """Process the search results and attempt to enqueue files for download.

        Args:
            search (dict): The search dictionary containing search details.
            creator_name (str): The name of the creator (artist or author).
            tracks (JsonArray): A JSON array of tracks (for Lidarr searches).
            track (JsonObject): A JSON object representing a single track (for Lidarr searches).
            release (JsonObject): A JSON object representing the release (for Lidarr searches).

        Returns:
            tuple[bool, list[dict]]: A tuple containing a boolean indicating success and a list of dictionaries with folder data.

        Raises:
            ValueError: If the search type is not recognized.

        """
        grab_list: list[dict] = []
        results = self.slskd.searches.search_responses(search["id"])
        is_lidarr_search = tracks is not None and track is not None and release is not None
        print(f"Search returned {len(results)} results")
        for result in results:
            username: str = result["username"]
            print(f"Parsing result from user: {username}")
            for file in result["files"]:
                filetype = file["filename"].split(".")[-1]
                file_dir = file["filename"].rsplit("\\", 1)[0]
                if is_lidarr_search and filetype in self.allowed_filetypes:
                    directory = self.get_user_directory(username, file_dir)
                    if directory is None:
                        continue
                    tracks_info = self.get_tracks_info(directory["files"])
                    if tracks_info["count"] == len(tracks) and tracks_info["filetype"] != "":
                        if self.is_album_match(tracks, directory["files"], username, tracks_info["filetype"]):
                            folder_data = self.get_folder_data(directory, file_dir, creator_name, username, release, track)
                            grab_list.append(folder_data)
                            is_successful = self.enqueue_files(grab_list, folder_data)
                            if is_successful:
                                return (is_successful, grab_list)
                elif not is_lidarr_search and filetype in self.readarr_allowed_filetypes:
                    directory = self.get_user_directory(username, file_dir)
                    if directory is None:
                        continue
                    folder_data = self.get_folder_data(is_lidarr_search, directory, file_dir, creator_name, username)
                    grab_list.append(folder_data)
                    is_successful = self.enqueue_files(grab_list, folder_data)
                    if is_successful:
                        return (is_successful, grab_list)
        return (False, grab_list)

    def get_user_directory(self, username: str, directory: str) -> dict:
        """Retrieve the directory information for a given user.

        Args:
            username (str): The username of the Soulseek user.
            directory (str): The directory path to retrieve.

        Returns:
            dict: The directory information if available, otherwise None.

        """
        try:
            return self.slskd.users.directory(username=username, directory=directory)
        except:
            return None

    def get_folder_data(
        self, is_lidarr_search: bool, directory: dict, file_dir: str, creator: str, username: str, release: JsonObject = None, track: JsonObject = None,
    ) -> dict:
        """Retrieve folder data for the given search type and directory.

        Args:
            is_lidarr_search (bool): Indicates if the search is for Lidarr.
            directory (dict): The directory information.
            file_dir (str): The file directory path.
            creator (str): The creator's name.
            username (str): The username of the Soulseek user.
            release (JsonObject, optional): The release information for Lidarr searches. Defaults to None.
            track (JsonObject, optional): The track information for Lidarr searches. Defaults to None.

        Returns:
            dict: The folder data.

        """
        wanted_files = []
        for file in directory["files"]:
            filetype = file["filename"].split(".")[-1]
            if (filetype in self.allowed_filetypes and is_lidarr_search) or (filetype in self.readarr_allowed_filetypes and not is_lidarr_search):
                wanted_files.append({**file, "filename": f"{file_dir}\\{file['filename']}"})
        directory["files"] = wanted_files
        folder_data = {
            "creator": creator,
            "dir": file_dir.split("\\")[-1],
            "username": username,
            "directory": directory,
        }
        if is_lidarr_search:
            folder_data["discnumber"] = track["mediumNumber"]
            folder_data["release"] = release
        return folder_data

    def enqueue_files(self, grab_list: list[dict], folder_data: dict) -> bool:
        """Enqueue files for download.

        Args:
            grab_list (list[dict]): The list of folders to grab.
            folder_data (dict): The folder data containing user and directory information.

        Returns:
            bool: True if the files were successfully enqueued, False otherwise.

        """
        try:
            return self.slskd.transfers.enqueue(username=folder_data["username"], files=folder_data["directory"]["files"])
        except Exception:
            self.ignored_users.append(folder_data["username"])
            grab_list.remove(folder_data)
            print(f"Error enqueueing tracks! Adding {folder_data['username']} to ignored users list.")
        return False

    def print_all_downloads(self) -> None:
        """Print all current downloads."""
        downloads = self.slskd.transfers.get_all_downloads()
        print("Downloads added: ")
        for download in downloads:
            username = download["username"]
            for dir in download["directories"]:
                print(f"Username: {username} Directory: {dir['directory']}")

    # TODO: Add timeout to prevent permanent hanging
    def monitor_downloads(self, grab_list: list[dict]) -> None:
        """Monitor the progress of downloads and handle completion or errors.

        Args:
            grab_list (list[dict]): A list of dictionaries containing folder data for downloads.

        """
        while True:
            unfinished = 0
            for folder in grab_list:
                username, dir = folder["username"], folder["directory"]
                downloads = self.slskd.transfers.get_downloads(username)
                unfinished += self.process_folder(username, dir, folder, grab_list, downloads)
            if unfinished == 0:
                print("All items finished downloading!")
                time.sleep(5)
                break
            time.sleep(10)

    def process_folder(self, username: str, dir: str, folder: dict, grab_list: list[dict], downloads: dict) -> int:
        """Process a folder to check for unfinished downloads and handle errors.

        Args:
            username (str): The username associated with the downloads.
            dir (str): The directory name.
            folder (dict): The folder data containing user and directory information.
            grab_list (list[dict]): A list of dictionaries containing folder data for downloads.
            downloads (dict): The downloads dictionary containing download details.

        Returns:
            int: The number of unfinished downloads.

        """
        unfinished = 0
        for directory in downloads["directories"]:
            if directory["directory"] == dir["name"]:
                errored_files = self.get_errored_files(directory["files"])
                pending_files = self.get_pending_files(directory["files"])
                if len(errored_files) > 0:
                    print(f"FAILED: Username: {username} Directory: {dir}")
                    self.cancel_and_delete(folder["dir"], folder["username"], directory["files"])
                    grab_list.remove(folder)
                elif len(pending_files) > 0:
                    unfinished += 1
        return unfinished

    def get_errored_files(self, files: list[dict]) -> list[dict]:
        """Retrieve the list of errored files.

        Args:
            files (list[dict]): The list of files to check.

        Returns:
            list[dict]: A list of files that have errored states.

        """
        return [
            file
            for file in files
            if file["state"]
            in [
                "Completed, Cancelled",
                "Completed, TimedOut",
                "Completed, Errored",
                "Completed, Rejected",
            ]
        ]

    def get_pending_files(self, files: list[dict]) -> bool:
        """Retrieve the list of pending files.

        Args:
            files (list[dict]): The list of files to check.

        Returns:
            list[dict]: A list of files that are still pending.

        """
        return [file for file in files if "Completed" not in file["state"]]

    def search_and_download(
        self, query: str, creator_name: str, tracks: JsonArray = None, track: JsonObject = None, release: JsonObject = None,
    ) -> tuple[bool, list[dict]]:
        """Search for tracks and download them.

        Args:
            query (str): The search query.
            creator_name (str): The name of the creator (artist or author).
            tracks (JsonArray, optional): A JSON array of tracks (for Lidarr searches). Defaults to [].
            track (JsonObject, optional): A JSON object representing a single track (for Lidarr searches). Defaults to None.
            release (JsonObject, optional): A JSON object representing the release (for Lidarr searches). Defaults to None.

        Returns:
            tuple[bool, list[dict]]: A tuple containing a boolean indicating success and a list of dictionaries with folder data.

        """
        if tracks is None:
            tracks = []
        search = self.initiate_search(query)
        self.wait_for_search_completion(search)
        return self.process_search_results(search, creator_name, tracks, track, release)
