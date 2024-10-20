from datetime import datetime
import os
import music_tag
from arrs import Arrs
from pyarr.types import JsonArray, JsonObject

class Lidarr(Arrs):
    def __init__(
            self,
            host_url: str,
            api_key: str,
            download_dir: str,
            current_page_file_path: str,
            accepted_countries: list[str],
            accepted_formats: list[str],
            title_blacklist: list[str],
            use_most_common_tracknum: bool,
            allow_multi_disc: bool,
            number_of_albums_to_grab: int,
            search_type: str,
            album_prepend_artist: bool,
            search_for_tracks: bool,
            remove_wanted_on_failure: bool
        ) -> None:
        super().__init__('lidarr', host_url, api_key, download_dir, current_page_file_path, accepted_formats, accepted_countries, title_blacklist, number_of_albums_to_grab, search_type, album_prepend_artist, remove_wanted_on_failure)
        self.use_most_common_tracknum = use_most_common_tracknum
        self.allow_multi_disc = allow_multi_disc
        self.search_for_tracks = search_for_tracks

    def get_wanted(self, page: int = 1) -> JsonObject:
        return self.lidarr.get_wanted(page=page, page_size=self.page_size, sort_dir='ascending',sort_key='albums.title')
    
    def get_title(self, release: JsonObject) -> str:
        return self.lidarr.get_album(albumIds = release['albumId'])['title']

    def release_track_count_mode(self, releases: JsonArray) -> int:
        track_counts: dict = {}
        max_count: int = 0
        most_common_track_count: int = -1

        for release in releases:
            track_count = release['trackCount']
            if track_count in track_counts:
                track_counts[track_count] += 1
            else:
                track_counts[track_count] = 1

        for track_count, count in track_counts.items():
            if count > max_count:
                max_count = count
                most_common_track_count = track_count

        return most_common_track_count
    
    def is_multi_disc(self, format: str) -> bool:
        return format[1] == 'x'

    def choose_release(self: object, album_id: str, artist_name: str) -> JsonObject:
        releases: JsonArray = self.lidarr.get_album(album_id)['releases']
        most_common_trackcount = self.release_track_count_mode(releases)

        for release in releases:
            format: str = release['format'].split("x", 1)[1] if (self.allow_multi_disc and self.is_multi_disc(release['format'])) else release['format']
            country: str | None = release['country'][0] if release['country'] else None
            format_accepted: bool =  self.is_format_accepted(format)
            track_count: bool = release['trackCount'] == most_common_trackcount if self.use_most_common_tracknum else True

            if (country in self.accepted_countries and format_accepted and release['status'] == "Official" and track_count):
                print(f"Selected release for {artist_name}: {release['status']}, {country}, {release['format']}, Mediums: {release['mediumCount']}, Tracks: {release['trackCount']}, ID: {release['id']}")
                return release

        if self.use_most_common_tracknum:
            for release in releases:
                if release['trackCount'] == most_common_trackcount:
                    default_release = release
        else:
            default_release = releases[0]
        return default_release
    
    def grab_album(self, record: JsonObject) -> tuple[str, JsonArray, str, JsonObject]:
        artist_name = record['artist']['artistName']
        artist_id = record['artistId']
        album_id = record['id']
        release = self.choose_release(album_id, artist_name)
        release_id = release['id']
        all_tracks = self.lidarr.get_tracks(artistId = artist_id, albumId = album_id, albumReleaseId = release_id)

        # TODO: Right now if search_for_tracks is False. Multi disc albums will never be downloaded so we need to loop through media in releases even for albums
        if len(release['media']) == 1:
            album_title = self.lidarr.get_album(album_id)['title']
            if self.is_blacklisted(album_title):
                return (None, [], artist_name, release)
            query = f"{artist_name} {album_title}" if self.prepend_creator or len(album_title) == 1 else album_title
        return (query, all_tracks, artist_name, release)

    def grab_releases(self, slskd_instance: object, wanted_records: JsonArray, failure_file_path: str) -> int:
        failed_downloads = 0
        for record in wanted_records:
            (query, all_tracks, artist_name, release) = self.grab_album(record)
            if query is None:
                continue
            print(f"Searching album: {query}")
            success = slskd_instance.search_and_download(query, all_tracks, all_tracks[0], artist_name, release)

            if not success and self.search_for_tracks:
                for media in release['media']:
                    tracks = []
                    for track in all_tracks:
                        if track['mediumNumber'] == media['mediumNumber']:
                            tracks.append(track)
                    for track in tracks:
                        if self.is_blacklisted(track['title']):
                            continue
                        query = f"{artist_name} {track['title']}" if self.prepend_creator or len(track['title']) == 1 else track['title']
                        print(f"Searching track: {query}")
                        success = slskd_instance.search_and_download(query, tracks, track, artist_name, release)
                        if success:
                            break

                    if not success:
                        if self.remove_wanted_on_failure:
                            print(f"ERROR: Failed to grab album: {record['title']} for artist: {artist_name}\n Failed album removed from wanted list and added to \"failure_list.txt\"")
                            record['monitored'] = False
                            self.lidarr.upd_album(record)
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            with open(failure_file_path, "a") as file:
                                file.write(f"{timestamp} - {artist_name}, {record['title']}, {record['id']}\n")
                        else:
                            print(f"ERROR: Failed to grab album: {record['title']} for artist: {artist_name}")
                        failed_downloads += 1
            success = False
        return failed_downloads
    
    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        creator = folder['creator']
        if filename.split(".")[-1] in self.accepted_formats:
            song = music_tag.load_file(path)
            song['artist'] = creator
            song['albumartist'] = creator
            song['album'] = release_name
            song['discnumber'] = folder['discnumber']
            song.save()

    def import_downloads(self, creator_folders: list[str]) -> None:
        import_commands = []
        for creator_folder in creator_folders:
            task = self.lidarr.post_command(name = 'DownloadedAlbumsScan', path = os.path.join(self.download_dir, creator_folder))
            import_commands.append(task)
            print(f"Starting Lidarr import for: {creator_folder} ID: {task['id']}")

        while True:
            completed_count = 0
            for task in import_commands:
                current_task = self.lidarr.get_command(task['id'])
                if current_task['status'] == 'completed':
                    completed_count += 1
            if completed_count == len(import_commands):
                break

        for task in import_commands:
            current_task = self.lidarr.get_command(task['id'])
            try:
                print(f"{current_task['commandName']} {current_task['message']} from: {current_task['body']['path']}")
            except:
                print("Error printing lidarr task message. Printing full unparsed message.")
                print(current_task)