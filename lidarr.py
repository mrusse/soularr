import os

import music_tag
from pyarr.types import JsonArray, JsonObject

from arrs import Arrs


class Lidarr(Arrs):
    """Lidarr class for managing music albums and tracks."""

    def __init__(
            self,
            application_settings: tuple[str, str, str],
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
            remove_wanted_on_failure: bool,
        ) -> None:
        """Initialize the Lidarr class with the given settings.

        Args:
            application_settings (tuple[str, str, str]): A tuple containing the application settings (host_url, api_key, download_dir).
            current_page_file_path (str): The file path to the current page.
            accepted_countries (list[str]): A list of accepted countries.
            accepted_formats (list[str]): A list of accepted formats.
            title_blacklist (list[str]): A list of titles to be blacklisted.
            use_most_common_tracknum (bool): Whether to use the most common track number.
            allow_multi_disc (bool): Whether to allow multi-disc albums.
            number_of_albums_to_grab (int): The number of albums to grab.
            search_type (str): The type of search to be performed.
            album_prepend_artist (bool): Whether to prepend the artist's name to the album title.
            search_for_tracks (bool): Whether to search for tracks.
            remove_wanted_on_failure (bool): Whether to remove wanted items on failure

        """
        super().__init__(application_settings, current_page_file_path, title_blacklist, number_of_albums_to_grab, search_type, album_prepend_artist, remove_wanted_on_failure)
        self.accepted_countries = accepted_countries
        self.accepted_formats = accepted_formats
        self.use_most_common_tracknum = use_most_common_tracknum
        self.allow_multi_disc = allow_multi_disc
        self.search_for_tracks = search_for_tracks

    def get_wanted(self, page: int = 1) -> JsonObject:
        """Retrieve the list of wanted albums.

        Args:
            page (int, optional): The page number to retrieve. Defaults to 1.

        Returns:
            JsonObject: The JSON object containing the list of wanted albums.

        """
        return self.lidarr.get_wanted(page=page, page_size=self.page_size, sort_dir="ascending",sort_key="albums.title")

    def get_command(self, id: int) -> dict:
        """Retrieve the command with the specified ID.

        Args:
            id (int): The ID of the command to retrieve.

        Returns:
            dict: The command details.

        """
        return self.lidarr.get_command(id)

    def release_track_count_mode(self, releases: JsonArray) -> int:
        """Determine the most common track count in the given releases.

        Args:
            releases (JsonArray): The array of release objects.

        Returns:
            int: The most common track count.

        """
        track_counts: dict = {}
        max_count: int = 0
        most_common_track_count: int = -1

        for release in releases:
            track_count = release["trackCount"]
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
        """Check if the format indicates a multi-disc album.

        Args:
            format (str): The format string to check.

        Returns:
            bool: True if the format indicates a multi-disc album, False otherwise.

        """
        return format[1] == "x"

    def choose_release(self: object, album_id: str, artist_name: str) -> JsonObject:
        """Choose the best release for the given album and artist.

        Args:
            album_id (str): The ID of the album.
            artist_name (str): The name of the artist.

        Returns:
            JsonObject: The chosen release object.

        """
        releases: JsonArray = self.lidarr.get_album(album_id)["releases"]
        most_common_trackcount = self.release_track_count_mode(releases)

        for release in releases:
            format: str = release["format"].split("x", 1)[1] if (self.allow_multi_disc and self.is_multi_disc(release["format"])) else release["format"]
            country: str | None = release["country"][0] if release["country"] else None
            track_count: bool = release["trackCount"] == most_common_trackcount if self.use_most_common_tracknum else True

            if (country in self.accepted_countries and format in self.accepted_formats and release["status"] == "Official" and track_count):
                print(f"Selected release for {artist_name}: {release['status']}, {country}, "
                      f"{release['format']}, Mediums: {release['mediumCount']}, "
                      f"Tracks: {release['trackCount']}, ID: {release['id']}")
                return release

        if self.use_most_common_tracknum:
            for release in releases:
                if release["trackCount"] == most_common_trackcount:
                    default_release = release
        else:
            default_release = releases[0]
        return default_release

    def grab_album(self, record: JsonObject) -> tuple[str, JsonArray, str, JsonObject]:
        """Grab the album details and tracks for the given record.

        Args:
            record (JsonObject): The JSON object containing the record details.

        Returns:
            tuple[str, JsonArray, str, JsonObject]: A tuple containing the query string, all tracks, artist name, and release object.

        """
        artist_name = record["artist"]["artistName"]
        artist_id = record["artistId"]
        album_id = record["id"]
        release = self.choose_release(album_id, artist_name)
        release_id = release["id"]
        all_tracks = self.lidarr.get_tracks(artistId = artist_id, albumId = album_id, albumReleaseId = release_id)

        # TODO: Right now if search_for_tracks is False. Multi disc albums will never be downloaded so we need to loop through media in releases even for albums
        if len(release["media"]) == 1:
            album_title = self.lidarr.get_album(album_id)["title"]
            if self.is_blacklisted(album_title):
                return (None, [], artist_name, release)
            query = f"{artist_name} {album_title}" if self.prepend_creator or len(album_title) == 1 else album_title
        else:
            return (None, [], artist_name, release)
        return (query, all_tracks, artist_name, release)

    def grab_tracks(self, release: JsonObject, all_tracks: JsonArray) -> JsonArray:
        """Grab the tracks for the given release.

        Args:
            release (JsonObject): The JSON object containing the release details.
            all_tracks (JsonArray): The array of all track objects.

        Returns:
            JsonArray: The array of grabbed track objects.

        """
        for media in release["media"]:
            tracks: JsonArray = []
            for track in all_tracks:
                if track["mediumNumber"] == media["mediumNumber"]:
                    tracks.append(track)
        return tracks

    def grab_track(self, track: JsonObject, artist_name: str) -> str:
        """Grab the track query string for the given track and artist.

        Args:
            track (JsonObject): The JSON object containing the track details.
            artist_name (str): The name of the artist.

        Returns:
            str: The query string for the track.

        """
        if self.is_blacklisted(track["title"]):
            return None
        return f"{artist_name} {track['title']}" if self.prepend_creator or len(track["title"]) == 1 else track["title"]

    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        """Retag the music file with the given release and folder details.

        Args:
            release_name (str): The name of the release.
            filename (str): The name of the file.
            path (str): The path to the file.
            folder (dict): The folder details containing creator and disc number.

        """
        creator = folder["creator"]
        if filename.split(".")[-1] in self.accepted_formats:
            song = music_tag.load_file(path)
            song["artist"] = creator
            song["albumartist"] = creator
            song["album"] = release_name
            song["discnumber"] = folder["discnumber"]
            song.save()

    def import_downloads(self, creator_folders: list[str]) -> None:
        """Import downloaded albums for the given creator folders.

        Args:
            creator_folders (list[str]): A list of creator folder names to import.

        """
        import_commands = []
        for creator_folder in creator_folders:
            task = self.lidarr.post_command(name = "DownloadedAlbumsScan", path = os.path.join(self.download_dir, creator_folder))
            import_commands.append(task)
            print(f"Starting Lidarr import for: {creator_folder} ID: {task['id']}")
        self.monitor_import_commands(import_commands)
        for task in import_commands:
            self.process_import_task(self.lidarr.get_command(task["id"]))
