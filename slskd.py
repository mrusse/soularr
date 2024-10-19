import difflib
import os
import shutil
import time
from pyarr.types import JsonArray, JsonObject
from applications import Applications

class Slskd(Applications):
    def __init__(
            self,
            api_key: str,
            host_url: str,
            download_dir: str,
            search_timeout: int,
            maximum_peer_queue: int,
            minimum_peer_upload_speed: int,
            allowed_filetypes: list[str],
            ignored_users: list[str],
            title_blacklist: list[str],
            remove_wanted_on_failure: bool,
            search_type: str,
        ) -> None:
        super().__init__(api_key, host_url, download_dir)
        self.search_timeout = search_timeout
        self.maximum_peer_queue = maximum_peer_queue
        self.minimum_peer_upload_speed = minimum_peer_upload_speed
        self.allowed_filetypes = allowed_filetypes
        self.ignored_users = ignored_users
        self.title_blacklist = title_blacklist
        self.remove_wanted_on_failure = remove_wanted_on_failure
        self.search_type = search_type

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

    def process_search_results(self, search: dict, tracks: JsonArray, track: JsonObject, artist_name: str, release: JsonObject) -> list[dict]:
        grab_list: list[dict] = []
        results = self.slskd.searches.search_responses(search['id'])
        print(f"Search returned {len(results)} results")
        for result in results:
            username: str = result['username']
            print(f"Parsing result from user: {username}")
            for file in result['files']:
                if file['filename'].split(".")[-1] in self.allowed_filetypes:
                    file_dir = file['filename'].rsplit("\\", 1)[0]
                    try:
                        directory = self.slskd.users.directory(username=username, directory=file_dir)
                    except:
                        continue
                    tracks_info = self.get_track_info(directory['files'])
                    if tracks_info['count'] == len(tracks) and tracks_info['filetype'] != "" and self.is_album_match(tracks, directory['files'], username, tracks_info['filetype']):
                        folder_data = self.get_folder_data(directory, file_dir, artist_name, release, username, track)
                        grab_list.append(folder_data)
        return grab_list    
    
    def get_folder_data(self, directory: dict, file_dir: str, creator: str, release: JsonObject, username: str, track: JsonObject = None) -> dict:
        directory['files'] = [{**file, 'filename': f"{file_dir}\\{file['filename']}"} for file in directory['files']]
        folder_data = {
            "creator": creator,
            "release": release,
            "dir": file_dir.split("\\")[-1],
            "username": username,
            "directory": directory,
        }
        if track:
            folder_data['discnumber'] = track['mediumNumber']
        return folder_data
    
    def enqueue_files(self, grab_list: list[dict]) -> bool:
        for folder_data in grab_list:
            try:
                self.slskd.transfers.enqueue(username=folder_data['username'], files=folder_data['directory']['files'])
                return True
            except Exception:
                self.ignored_users.append(folder_data['username'])
                grab_list.remove(folder_data)
                print(f"Error enqueueing tracks! Adding {folder_data['username']} to ignored users list.")
                continue
        return False


    def print_all_downloads(self):
        downloads = self.slskd.transfers.get_all_downloads()
        print("Downloads added: ")
        for download in downloads:
            username = download['username']
            for dir in download['directories']:
                print(f"Username: {username} Directory: {dir['directory']}")


    def monitor_downloads(self, grab_list: list[dict]) -> list[dict]:
        while True:
            unfinished = 0
            for folder in grab_list:
                username, dir = folder['username'], folder['directory']
                downloads = self.slskd.transfers.get_downloads(username)
                unfinished += self.process_folder(username, dir, folder, grab_list, downloads)
            if unfinished == 0:
                print("All tracks finished downloading!")
                time.sleep(5)
                return grab_list
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

    def get_errored_files(files: list[dict]) -> list[dict]:
        return [file for file in files if file["state"] in [
            'Completed, Cancelled',
            'Completed, TimedOut',
            'Completed, Errored',
            'Completed, Rejected',
        ]]


    def get_pending_files(files: list[dict]) -> bool:
        return [file for file in files if not 'Completed' in file["state"]]


    def search_and_download(self, query: str, tracks: JsonArray, track: JsonObject, artist_name: str, release: JsonObject) -> bool:
        search = self.initiate_search(query)
        self.wait_for_search_completion(search)
        grab_list: list[dict] = self.process_search_results(search, tracks, track, artist_name, release)
        return self.enqueue_files(grab_list)
    
    def move_failed_import(src_path: str) -> None:
        failed_imports_dir = "failed_imports"
        counter = 1
        if not os.path.exists(failed_imports_dir):
            os.makedirs(failed_imports_dir)
        folder_name = os.path.basename(src_path)
        target_path = os.path.join(failed_imports_dir, folder_name)
        
        while os.path.exists(target_path):
            target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
            counter += 1
        
        shutil.move(folder_name, target_path)
        print(f"Failed import moved to: {target_path}")
