import operator
import time
import music_tag
from pyarr import LidarrAPI
from pyarr.types import JsonArray, JsonObject

class Lidarr:
    def __init__(self: object, host_url: str, api_key: str, download_dir: str, accepted_countries: list[str], accepted_formats: list[str], use_most_common_tracknum: bool, allow_multi_disc: bool) -> None:
        self.lidarr = LidarrAPI(host_url, api_key)
        self.download_dir = download_dir
        self.accepted_countries = accepted_countries
        self.accepted_formats = accepted_formats
        self.use_most_common_tracknum = use_most_common_tracknum
        self.allow_multi_disc = allow_multi_disc



    def release_track_count_mode(releases: JsonArray) -> int | None:
        track_counts: dict = {}
        max_count: int = 0
        most_common_track_count: int | None = None

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
    
    def is_multi_disc(format: str) -> bool:
        return format[1] == 'x'
    
    def is_format_accepted(self: object, format: str) -> bool:
        return format in self.accepted_formats

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