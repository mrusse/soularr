import difflib
import os
import shutil
import time
from pyarr.types import JsonArray, JsonObject
from applications import Applications

class Slskd(Applications):
    def __init__(
            self,
            host_url: str,
            api_key: str,
            download_dir: str,
            search_timeout: int,
            maximum_peer_queue: int,
            minimum_peer_upload_speed: int,
            allowed_filetypes: list[str],
            readarr_allowed_filetypes: list[str],
            ignored_users: list[str],
            remove_wanted_on_failure: bool,
        ) -> None:
        super().__init__('slskd', host_url, api_key, download_dir)
        self.search_timeout = search_timeout
        self.maximum_peer_queue = maximum_peer_queue
        self.minimum_peer_upload_speed = minimum_peer_upload_speed
        self.allowed_filetypes = allowed_filetypes
        self.readarr_allowed_filetypes = readarr_allowed_filetypes
        self.ignored_users = ignored_users
        self.remove_wanted_on_failure = remove_wanted_on_failure

    def get_tracks_info(self, files: dict) -> dict:
        count = 0
        index = -1
        filetype = ""
        for file in files:
            if(file['filename'].split(".")[-1] in self.allowed_filetypes):
                new_index = self.allowed_filetypes.index(file['filename'].split(".")[-1])
                if index == -1:
                    index = new_index
                    filetype = self.allowed_filetypes[index]
                elif new_index != index:
                    filetype = ""
                    break
                count += 1
        return { "count": count, "filetype": filetype }
    
    def is_lidarr_track_in_slskd_tracks(self, lidarr_track: JsonObject, slskd_tracks: dict, filetype: str) -> tuple[bool, float]:
        lidarr_filename: str = lidarr_track['title'] + filetype
        best_match: float = 0.0
        for slskd_track in slskd_tracks:
            slskd_filename: str = slskd_track['filename']
            ratio: float = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            #If ratio is a bad match try and split off the garbage at the start of the slskd_filename and try again
            if ratio < 0.5:
                lidarr_filename_word_count: int = len(lidarr_filename.split()) * -1
                truncated_slskd_filename: str = " ".join(slskd_filename.split()[lidarr_filename_word_count:])
                ratio = difflib.SequenceMatcher(None, lidarr_filename, truncated_slskd_filename).ratio()
            if ratio > best_match:
                best_match = ratio
        return best_match > 0.5, best_match

    # TODO : Make this generic, to handle readarr too
    def is_album_match(self, lidarr_tracks: JsonArray, slskd_tracks: dict, username: str, filetype: str) -> bool:
        counted: list[str] = []
        total_match: float = 0.0
        for lidarr_track in lidarr_tracks:
            is_match, best_match = self.is_lidarr_track_in_slskd_tracks(lidarr_track, slskd_tracks, filetype)
            if is_match:
                counted.append(lidarr_track['title'])
                total_match += best_match
        if len(counted) == len(lidarr_tracks) and username not in self.ignored_users:
            print(f"\nFound match from user: {username} for {len(counted)} tracks! \nAverage sequence match ratio: {total_match/len(counted)} \nSUCCESSFUL MATCH \n-------------------")
            return True
        return False

    def cancel_and_delete(self, delete_dir: str, username: str, files: dict) -> None:
        for file in files:
            self.slskd.transfers.cancel_download(username = username, id = file['id'])
        os.chdir(self.download_dir)
        if os.path.exists(delete_dir):
            shutil.rmtree(delete_dir)

    def initiate_search(self, query: str) -> dict:
        return self.slskd.searches.search_text(
            searchText = query,
            searchTimeout = self.search_timeout,
            filterResponses = True,
            maximumPeerQueueLength = self.maximum_peer_queue,
            minimumPeerUploadSpeed = self.minimum_peer_upload_speed
        )
    
    def wait_for_search_completion(self, search: dict) -> None:
        while True:
            if self.slskd.searches.state(search['id'])['state'] != 'InProgress':
                break
            time.sleep(1)

    def process_search_results(self, search: dict, creator_name: str, tracks: JsonArray, track: JsonObject, release: JsonObject) -> tuple[bool, list[dict]]:
        grab_list: list[dict] = []
        results = self.slskd.searches.search_responses(search['id'])
        is_lidarr_search = tracks is not None and track is not None and release is not None
        print(f"Search returned {len(results)} results")
        for result in results:
            username: str = result['username']
            print(f"Parsing result from user: {username}")
            for file in result['files']:
                filetype = file['filename'].split(".")[-1]
                file_dir = file['filename'].rsplit("\\", 1)[0]
                if is_lidarr_search and filetype in self.allowed_filetypes:
                    directory = self.get_user_directory(username, file_dir)
                    if directory is None:
                        continue
                    tracks_info = self.get_tracks_info(directory['files'])
                    if tracks_info['count'] == len(tracks) and tracks_info['filetype'] != "":
                        if self.is_album_match(tracks, directory['files'], username, tracks_info['filetype']):
                            folder_data = self.get_folder_data(directory, file_dir, creator_name, username, release, track)
                            grab_list.append(folder_data)
                            is_successful = self.enqueue_files(grab_list, folder_data)
                            if is_successful:
                                return (is_successful, grab_list)
                elif not is_lidarr_search and filetype in self.readarr_allowed_filetypes:
                    directory = self.get_user_directory(username, file_dir)
                    if directory is None:
                        continue
                    folder_data = self.get_folder_data(directory, file_dir, creator_name, username)
                    grab_list.append(folder_data)
                    is_successful = self.enqueue_files(grab_list, folder_data)
                    if is_successful:
                        return (is_successful, grab_list)
        return (False, grab_list)
    
    def get_user_directory(self, username: str, directory: str) -> dict:
        try:
            return self.slskd.users.directory(username=username, directory=directory)
        except:
            return None
    
    def get_folder_data(self, directory: dict, file_dir: str, creator: str, username: str, release: JsonObject = None, track: JsonObject = None) -> dict:
        directory['files'] = [{**file, 'filename': f"{file_dir}\\{file['filename']}"} for file in directory['files']]
        folder_data = {
            "creator": creator,
            "dir": file_dir.split("\\")[-1],
            "username": username,
            "directory": directory,
        }
        if track and release:
            folder_data['discnumber'] = track['mediumNumber']
            folder_data['release'] = release
        return folder_data
    
    def enqueue_files(self, grab_list: list[dict], folder_data: dict) -> bool:
        try:
            self.slskd.transfers.enqueue(username=folder_data['username'], files=folder_data['directory']['files'])
            return True
        except Exception:
            self.ignored_users.append(folder_data['username'])
            grab_list.remove(folder_data)
            print(f"Error enqueueing tracks! Adding {folder_data['username']} to ignored users list.")
        return False


    def print_all_downloads(self):
        downloads = self.slskd.transfers.get_all_downloads()
        print("Downloads added: ")
        for download in downloads:
            username = download['username']
            for dir in download['directories']:
                print(f"Username: {username} Directory: {dir['directory']}")


    def monitor_downloads(self, grab_list: list[dict]) -> None:
        while True:
            unfinished = 0
            for folder in grab_list:
                username, dir = folder['username'], folder['directory']
                downloads = self.slskd.transfers.get_downloads(username)
                unfinished += self.process_folder(username, dir, folder, grab_list, downloads)
            if unfinished == 0:
                print("All items finished downloading!")
                time.sleep(5)
                break
            time.sleep(10)


    def process_folder(self, username: str, dir: str, folder: dict, grab_list: list[dict], downloads: dict) -> int:
        unfinished = 0
        for directory in downloads["directories"]:
            if directory["directory"] == dir["name"]:
                errored_files = self.get_errored_files(directory["files"])
                pending_files = self.get_pending_files(directory["files"])
                if len(errored_files) > 0:
                    print(f"FAILED: Username: {username} Directory: {dir}")
                    self.cancel_and_delete(folder['dir'], folder['username'], directory["files"])
                    grab_list.remove(folder)
                elif len(pending_files) > 0:
                    unfinished += 1
        return unfinished

    def get_errored_files(self, files: list[dict]) -> list[dict]:
        return [file for file in files if file["state"] in [
            'Completed, Cancelled',
            'Completed, TimedOut',
            'Completed, Errored',
            'Completed, Rejected',
        ]]


    def get_pending_files(self, files: list[dict]) -> bool:
        return [file for file in files if not 'Completed' in file["state"]]

    def search_and_download(self, query: str, creator_name: str, tracks: JsonArray = [], track: JsonObject = None, release: JsonObject = None) -> tuple[bool, list[dict]]:
        search = self.initiate_search(query)
        self.wait_for_search_completion(search)
        return self.process_search_results(search, creator_name, tracks, track, release)
