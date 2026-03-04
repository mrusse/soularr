#!/usr/bin/env python

import argparse
import math
import re
import os
import sys
import time
import shutil
import difflib
import operator
import configparser
import logging
import json
from datetime import datetime
import copy
import music_tag
import slskd_api
from pyarr import LidarrAPI
from slskd_api.apis import users


class EnvInterpolation(configparser.ExtendedInterpolation):
    """
    Interpolation which expands environment variables in values.
    Borrowed from https://stackoverflow.com/a/68068943
    """

    def before_read(self, parser, section, option, value):
        value = super().before_read(parser, section, option, value)
        return os.path.expandvars(value)


# Allows backwards compatibility for users updating an older version of Soularr
# without using the new [Logging] section in the config.ini file.
DEFAULT_LOGGING_CONF = {
    "level": "INFO",
    "format": "[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
}

# === API Clients & Logging ===
lidarr = None
slskd = None
config = None
logger = logging.getLogger("soularr")

# === Configuration Constants ===
slskd_api_key = None
lidarr_api_key = None
lidarr_download_dir = None
lidarr_disable_sync = None
slskd_download_dir = None
lidarr_host_url = None
slskd_host_url = None
stalled_timeout = None
remote_queue_timeout = None
delete_searches = None
slskd_url_base = None
ignored_users = []
search_type = None
search_source = None
download_filtering = None
use_extension_whitelist = None
extensions_whitelist = []
search_sources = []
minimum_match_ratio = None
page_size = None
remove_wanted_on_failure = None
enable_search_denylist = None
max_search_failures = None
use_most_common_tracknum = None
allow_multi_disc = None
accepted_countries = []
skip_region_check = None
accepted_formats = []
allowed_filetypes = []
lock_file_path = None
config_file_path = None
failure_file_path = None
current_page_file_path = None
denylist_file_path = None
search_blacklist = []

# === Runtime State & Caches ===
search_cache = {}
folder_cache = {}
broken_user = []


def album_match(lidarr_tracks, slskd_tracks, username, filetype):
    counted = []
    total_match = 0.0

    lidarr_album = lidarr.get_album(lidarr_tracks[0]["albumId"])
    lidarr_album_name = lidarr_album["title"]
    lidarr_artist_name = lidarr_album["artist"]["artistName"]

    for lidarr_track in lidarr_tracks:
        lidarr_filename = lidarr_track["title"] + "." + filetype.split(" ")[0]
        best_match = 0.0

        for slskd_track in slskd_tracks:
            slskd_filename = slskd_track["filename"]

            # Try to match the ratio with the exact filenames
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            # If ratio is a bad match try and split off (with " " as the separator) the garbage at the start of the slskd_filename and try again
            ratio = check_ratio(" ", ratio, lidarr_filename, slskd_filename)
            # Same but with "_" as the separator
            ratio = check_ratio("_", ratio, lidarr_filename, slskd_filename)

            # Same checks but preappend album name.
            ratio = check_ratio("", ratio, lidarr_album_name + " " + lidarr_filename, slskd_filename)
            ratio = check_ratio(" ", ratio, lidarr_album_name + " " + lidarr_filename, slskd_filename)
            ratio = check_ratio("_", ratio, lidarr_album_name + " " + lidarr_filename, slskd_filename)

            if ratio > best_match:
                best_match = ratio

        if best_match > minimum_match_ratio:
            counted.append(lidarr_filename)
            total_match += best_match

    if len(counted) == len(lidarr_tracks) and username not in ignored_users:
        logger.info(f"Found match from user: {username} for {len(counted)} tracks! Track attributes: {filetype}")
        logger.info(f"Average sequence match ratio: {total_match / len(counted)}")
        logger.info("SUCCESSFUL MATCH")
        logger.info("-------------------")
        return True

    return False


def check_ratio(separator, ratio, lidarr_filename, slskd_filename):
    if ratio < minimum_match_ratio:
        if separator != "":
            lidarr_filename_word_count = len(lidarr_filename.split()) * -1
            truncated_slskd_filename = " ".join(slskd_filename.split(separator)[lidarr_filename_word_count:])
            ratio = difflib.SequenceMatcher(None, lidarr_filename, truncated_slskd_filename).ratio()
        else:
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

        return ratio
    return ratio


def album_track_num(directory):
    files = directory["files"]
    allowed_filetypes_no_attributes = [item.split(" ")[0] for item in allowed_filetypes]
    count = 0
    index = -1
    filetype = ""
    for file in files:
        if file["filename"].split(".")[-1] in allowed_filetypes_no_attributes:
            new_index = allowed_filetypes_no_attributes.index(file["filename"].split(".")[-1])

            if index == -1:
                index = new_index
                filetype = allowed_filetypes_no_attributes[index]
            elif new_index != index:
                filetype = ""
                break

            count += 1

    return_data = {"count": count, "filetype": filetype}
    return return_data


def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:."/\\|?*]', "", folder_name)
    return valid_characters.strip()


def cancel_and_delete(files):
    for file in files:
        try:
            slskd.transfers.cancel_download(username=file["username"], id=file["id"])
        except Exception:
            logger.warning(f"Failed to cancel download {file['filename']} for {file['username']}", exc_info=True)
        delete_dir = file["file_dir"].split("\\")[-1]
        os.chdir(slskd_download_dir)

        if os.path.exists(delete_dir):
            shutil.rmtree(delete_dir)


def release_trackcount_mode(releases):
    track_count = {}

    for release in releases:
        trackcount = release["trackCount"]
        if trackcount in track_count:
            track_count[trackcount] += 1
        else:
            track_count[trackcount] = 1

    most_common_trackcount = None
    max_count = 0

    for trackcount, count in track_count.items():
        if count > max_count:
            max_count = count
            most_common_trackcount = trackcount

    return most_common_trackcount


def choose_release(artist_name, releases):
    most_common_trackcount = release_trackcount_mode(releases)

    for release in releases:
        country = release["country"][0] if release["country"] else None

        if release["format"][1] == "x" and allow_multi_disc:
            format_accepted = release["format"].split("x", 1)[1] in accepted_formats
        else:
            format_accepted = release["format"] in accepted_formats

        if use_most_common_tracknum:
            if release["trackCount"] == most_common_trackcount:
                track_count_bool = True
            else:
                track_count_bool = False
        else:
            track_count_bool = True

        if (skip_region_check or country in accepted_countries) and format_accepted and release["status"] == "Official" and track_count_bool:
            logger.info(
                ", ".join(
                    [
                        f"Selected release for {artist_name}: {release['status']}",
                        str(country),
                        release["format"],
                        f"Mediums: {release['mediumCount']}",
                        f"Tracks: {release['trackCount']}",
                        f"ID: {release['id']}",
                    ]
                )
            )

            return release

    if use_most_common_tracknum:
        for release in releases:
            if release["trackCount"] == most_common_trackcount:
                return release
        else:
            default_release = releases[0]

    else:
        default_release = releases[0]

    return default_release


def verify_filetype(file, allowed_filetype):
    current_filetype = file["filename"].split(".")[-1]
    bitdepth = None
    samplerate = None
    bitrate = None

    if "bitRate" in file:
        bitrate = file["bitRate"]
    if "sampleRate" in file:
        samplerate = file["sampleRate"]
    if "bitDepth" in file:
        bitdepth = file["bitDepth"]

    # Check if the types match up for the current files type and the current type from the config
    if current_filetype == allowed_filetype.split(" ")[0]:
        # Check if the current type from the config specifies other attributes than the filetype (bitrate etc)
        if " " in allowed_filetype:
            selected_attributes = allowed_filetype.split(" ")[1]
            # If it is a bitdepth/samplerate pair instead of a simple bitrate
            if "/" in selected_attributes:
                selected_bitdepth = selected_attributes.split("/")[0]
                try:
                    selected_samplerate = str(int(float(selected_attributes.split("/")[1]) * 1000))
                except (ValueError, IndexError):
                    logger.warning("Invalid samplerate in selected_attributes")
                    return False

                if bitdepth and samplerate:
                    if str(bitdepth) == str(selected_bitdepth) and str(samplerate) == str(selected_samplerate):
                        return True
                else:
                    return False
            # If it is a bitrate
            else:
                selected_bitrate = selected_attributes
                if bitrate:
                    if str(bitrate) == str(selected_bitrate):
                        return True
                else:
                    return False
        # If no bitrate or other info then it is a match so return true
        else:
            return True
    else:
        return False


def download_filter(allowed_filetype, directory):
    """
    Filters the directory listing from SLSKD using the filetype whitelist.
    If not using the whitelist it will only return the audio files of the allowed filetype.
    This is to prevent downloading m3u,cue,txt,jpg,etc. files that are sometimes stored in
    the same folders as the music files.
    """
    logging.debug("download_filtering")
    if download_filtering:
        whitelist = []  # Init an empty list to take just the allowed_filetype
        if use_extension_whitelist:
            whitelist = copy.deepcopy(extensions_whitelist)  # Copy the whitelist to allow us to append the allowed_filetype
        whitelist.append(allowed_filetype.split(" ")[0])
        unwanted = []
        logger.debug(f"Accepted extensions: {whitelist}")
        for file in directory["files"]:
            for extension in whitelist:
                if file["filename"].split(".")[-1].lower() == extension.lower():
                    break  # Jump out and don't add wanted files to the unwanted list
            else:
                unwanted.append(file["filename"])  # Add to list of files to remove from the wanted list
                logger.debug(f"Unwanted file: {file['filename']}")
        if len(unwanted) > 0:
            temp = []
            logger.debug(f"Unwanted Files: {unwanted}")
            for file in directory["files"]:
                if file["filename"] not in unwanted:
                    logger.debug(f"Added file to queue: {file['filename']}")
                    temp.append(file)  # Build the new list of files
            directory["files"] = temp
            for files in temp:
                logger.debug(f"File in final list: {files['filename']}")
            return directory  # Return the modified list
    return directory  # If we didn't find unwanted files or we aren't filtering just return the original list


def check_for_match(tracks, allowed_filetype, file_dirs, username):
    """
    Does the actual match checking on a single disk/album.
    """
    logger.debug(f"Current broken users {broken_user}")
    if username in broken_user:
        return False, {}, ""
    for file_dir in file_dirs:
        if username not in folder_cache:
            logger.debug(f"Add user to cache: {username}")
            folder_cache[username] = {}

        if file_dir not in folder_cache[username]:
            logger.info(f"User: {username} Folder: {file_dir} not in cache. Fetching from SLSKD")
            version = slskd.application.version()
            version_check = slskd_version_check(version)

            if not version_check:
                logger.info(f"Error checking slskd version number: {version}. Version check > 0.22.2: {version_check}. This would most likely be fixed by updating your slskd.")

            try:
                if version_check:
                    directory = slskd.users.directory(username=username, directory=file_dir)[0]
                else:
                    directory = slskd.users.directory(username=username, directory=file_dir)
            except Exception:
                logger.exception(f'Error getting directory from user: "{username}"')
                broken_user.append(username)
                logger.debug(f"Updated broken users {broken_user}")
                return False, {}, ""
            folder_cache[username][file_dir] = copy.deepcopy(directory)
        else:
            logger.info(f"User: {username} Folder: {file_dir} in cache. Using cached value")
            directory = copy.deepcopy(folder_cache[username][file_dir])

        track_num = len(tracks)
        tracks_info = album_track_num(directory)

        if tracks_info["count"] == track_num and tracks_info["filetype"] != "":
            if album_match(tracks, directory["files"], username, allowed_filetype):
                return True, directory, file_dir
            else:
                continue
    return False, {}, ""


def is_blacklisted(title: str) -> bool:
    blacklist = config.get("Search Settings", "title_blacklist", fallback="").lower().split(",")
    for word in blacklist:
        if word != "" and word in title.lower():
            logger.info(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False


def filter_list(albums):
    """
    Helper to do all the various filtering in one go and in one place. Same net effect as the previous multi-stage approach
    Just neater and easier to work on.
    """
    if enable_search_denylist:
        temp_list = []
        denylist = load_search_denylist(denylist_file_path)
        for album in albums:
            if not is_search_denylisted(denylist, album["id"], max_search_failures):
                temp_list.append(album)
            else:
                logger.info(f"Skipping denylisted album: {album['artist']['artistName']} - {album['title']} (ID: {album['id']})")
    else:
        temp_list = copy.deepcopy(albums)

    list_to_download = []
    for album in temp_list:
        if is_blacklisted(album["title"]):
            logger.info(f"Skipping blacklisted album: {album['artist']['artistName']} - {album['title']} (ID: {album['id']}")
            continue
        else:
            list_to_download.append(album)

    if len(list_to_download) > 0:
        return list_to_download
    else:
        return None


def search_for_album(album):
    album_title = album["title"]
    artist_name = album["artist"]["artistName"]
    album_id = album["id"]
    if len(album_title) == 1:  # Need to add some code to wrangle specific artist names in here.. ;)
        query = artist_name + " " + album_title
    else:
        query = artist_name + " " + album_title if config.getboolean("Search Settings", "album_prepend_artist", fallback=False) else album_title

    original_query = query
    for word in search_blacklist:
        if word:
            # Case-insensitive replacement
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            query = pattern.sub("", query)

    # Clean up double spaces
    query = " ".join(query.split())

    if query != original_query:
        logger.info(f"Filtered search query: '{original_query}' -> '{query}'")

    logger.info(f"Searching for album: {query}")
    try:
        search = slskd.searches.search_text(
            searchText=query,
            searchTimeout=config.getint("Search Settings", "search_timeout", fallback=5000),
            filterResponses=True,
            maximumPeerQueueLength=config.getint("Search Settings", "maximum_peer_queue", fallback=50),
            minimumPeerUploadSpeed=config.getint("Search Settings", "minimum_peer_upload_speed", fallback=0),
        )
    except Exception:
        logger.exception(f"Failed to perform search via SLSKD: {query}")
        return False

    # Add timeout here to increase reliability with Slskd. Sometimes it doesn't update search status fast enough. More of an issue with lots of historical searches in slskd
    time.sleep(5)
    start_time = time.time()
    while True:
        if slskd.searches.state(search["id"], False)["state"] != "InProgress":  # Added False here as we don't want the search results here. Just the state.
            break
        time.sleep(1)
        if (time.time() - start_time) > config.getint("Search Settings", "search_timeout", fallback=5000):
            logger.error("Failed to perform search via SLSKD due to timeout on search results.")
            return False

    search_results = slskd.searches.search_responses(search["id"])  # We use this API call twice. Let's just cache it locally.
    logger.info(f"Search returned {len(search_results)} results")
    if delete_searches:
        slskd.searches.delete(search["id"])

    if not len(search_results) > 0:
        return False

    if album_id not in search_cache:
        search_cache[album_id] = {}  # This is so we can check for matches we missed or if a user goes offline during our download

    for result in search_results:  # Switching to cached version. One less API call
        username = result["username"]
        if username not in search_cache[album_id]:
            # If we don't currently have a cache for a user set one up
            search_cache[album_id][username] = {}
        logger.info(f"Caching and truncating results for user: {username}")
        init_files = result["files"]  # init_files short for initial files. Before truncating
        # Search the returned files and only cache files that are of the allowed_filetypes
        for file in init_files:
            file_dir = file["filename"].rsplit("\\", 1)[0]  # split dir/filenames on \
            for allowed_filetype in allowed_filetypes:
                if verify_filetype(file, allowed_filetype):  # Check the filename for an allowed type
                    if allowed_filetype not in search_cache[album_id][username]:
                        search_cache[album_id][username][allowed_filetype] = []  # Init the cache for this allowed filetype
                    if file_dir not in search_cache[album_id][username][allowed_filetype]:
                        search_cache[album_id][username][allowed_filetype].append(file_dir)
    return True


def slskd_do_enqueue(username, files, file_dir):
    """
    Takes a list of files to download and returns a list of files that were successfully added to the download queue
    It also adds to each file the details needed to track that specific file.
    """
    downloads = []
    try:
        enqueue = slskd.transfers.enqueue(username=username, files=files)
    except Exception:
        logger.debug("Enqueue failed", exc_info=True)
        return None
    if enqueue:
        time.sleep(5)
        try:
            download_list = slskd.transfers.get_downloads(username=username)
        except Exception:
            logger.warning(f"Failed to get download status for {username} after enqueue", exc_info=True)
            return None
        for file in files:
            for directory in download_list["directories"]:
                if directory["directory"] == file_dir:
                    for slskd_file in directory["files"]:
                        if file["filename"] == slskd_file["filename"]:
                            file_details = {}
                            file_details["filename"] = file["filename"]
                            file_details["id"] = slskd_file["id"]
                            file_details["file_dir"] = file_dir
                            file_details["username"] = username
                            file_details["size"] = file["size"]
                            downloads.append(file_details)
        return downloads
    else:
        return None


def slskd_download_status(downloads):
    """
    Takes a list of files and gets the status of each file and packs it into the file object.
    """
    ok = True
    for file in downloads:
        try:
            status = slskd.transfers.get_download(file["username"], file["id"])
            file["status"] = status
        except Exception:
            logger.exception(f"Error getting download status of {file['filename']}")
            file["status"] = None
            ok = False
    return ok


def downloads_all_done(downloads):
    """
    Checks the status of all the files in an album and returns a flag if all done as well
    as returning a list of files with errors to check and how many files are in "Queued, Remotely"
    """
    all_done = True
    error_list = []
    remote_queue = 0
    for file in downloads:
        if file["status"] is not None:
            if not file["status"]["state"] == "Completed, Succeeded":
                all_done = False
            if file["status"]["state"] in [
                "Completed, Cancelled",
                "Completed, TimedOut",
                "Completed, Errored",
                "Completed, Rejected",
                "Completed, Aborted",
            ]:
                error_list.append(file)
            if file["status"]["state"] == "Queued, Remotely":
                remote_queue += 1
    if not len(error_list) > 0:
        error_list = None
    return all_done, error_list, remote_queue


def try_enqueue(all_tracks, results, allowed_filetype):
    """
    Single album match and enqueue.
    Iterates over all users and enqueues a found match
    """
    for username in results:
        if allowed_filetype not in results[username]:
            continue
        logger.debug(f"Parsing result from user: {username}")
        file_dirs = results[username][allowed_filetype]
        found, directory, file_dir = check_for_match(all_tracks, allowed_filetype, file_dirs, username)
        if found:
            directory = download_filter(allowed_filetype, directory)
            for i in range(0, len(directory["files"])):
                directory["files"][i]["filename"] = file_dir + "\\" + directory["files"][i]["filename"]
            try:
                downloads = slskd_do_enqueue(username=username, files=directory["files"], file_dir=file_dir)
                if downloads is not None:
                    return True, downloads
                else:
                    album = lidarr.get_album(all_tracks[0]["albumId"])
                    album_name = album["title"]
                    artist_name = album["artist"]["artistName"]
                    logger.info(f"Failed to enqueue download to slskd for {artist_name} - {album_name} from {username}")
            except Exception as e:
                album = lidarr.get_album(all_tracks[0]["albumId"])
                album_name = album["title"]
                artist_name = album["artist"]["artistName"]

                logger.warning(f"Exception enqueueing tracks: {e}")
                logger.info(f"Exception enqueueing download to slskd for {artist_name} - {album_name} from {username}")
    album = lidarr.get_album(all_tracks[0]["albumId"])
    album_name = album["title"]
    artist_name = album["artist"]["artistName"]
    logger.info(f"Failed to enqueue {artist_name} - {album_name}")
    return False, None


def try_multi_enqueue(release, all_tracks, results, allowed_filetype):
    """
    This is the multi-disk/media path for locating and enqueueing an album
    It does a flat search first. Then it does a split search.
    Otherwise it's basically the same as the single album search.
    """
    split_release = []
    tmp_results = copy.deepcopy(results)
    for media in release["media"]:
        disk = {}
        disk["source"] = None
        disk["tracks"] = []
        disk["disk_no"] = media["mediumNumber"]
        disk["disk_count"] = len(release["media"])
        for track in all_tracks:
            if track["mediumNumber"] == media["mediumNumber"]:
                disk["tracks"].append(track)
        split_release.append(disk)
    total = len(split_release)
    count_found = 0
    for disk in split_release:
        for username in tmp_results:
            if allowed_filetype not in tmp_results[username]:
                continue
            file_dirs = results[username][allowed_filetype]
            found, directory, file_dir = check_for_match(disk["tracks"], allowed_filetype, file_dirs, username)
            if found:
                directory = download_filter(allowed_filetype, directory)
                disk["source"] = (username, directory, file_dir)
                count_found += 1
                break
        else:
            return (
                False,
                None,
            )  # Only runs if we complete the loop without finding a source for the current disk regardless of how many other disks we located. All or nothing.
    if count_found == total:
        all_downloads = []
        enqueued = 0
        for disk in split_release:
            username, directory, file_dir = disk["source"]
            for i in range(0, len(directory["files"])):
                directory["files"][i]["filename"] = file_dir + "\\" + directory["files"][i]["filename"]
            try:
                downloads = slskd_do_enqueue(username=username, files=directory["files"], file_dir=file_dir)
                if downloads is not None:
                    for file in downloads:
                        file["disk_no"] = disk["disk_no"]
                        file["disk_count"] = disk["disk_count"]
                    all_downloads.extend(downloads)
                    enqueued += 1
                else:
                    album = lidarr.get_album(all_tracks[0]["albumId"])
                    album_name = album["title"]
                    artist_name = album["artist"]["artistName"]
                    logger.info(f"Failed to enqueue download to slskd for {artist_name} - {album_name} from {username}")
                    # Delete ALL other downloads in all_downloads list
                    if len(all_downloads) > 0:
                        cancel_and_delete(all_downloads)
                        return False, None
            except Exception:
                album = lidarr.get_album(all_tracks[0]["albumId"])
                album_name = album["title"]
                artist_name = album["artist"]["artistName"]

                logger.exception("Exception enqueueing tracks")
                logger.info(f"Exception enqueueing download to slskd for {artist_name} - {album_name} from {username}")
                # Delete all other downloads in all_downloads list
                if len(all_downloads) > 0:
                    cancel_and_delete(all_downloads)
                    return False, None
        if enqueued == total:
            return True, all_downloads
        else:
            # Delete all other downloads
            if len(all_downloads) > 0:
                cancel_and_delete(all_downloads)
            return False, None

    else:
        return False, None


def find_download(album, grab_list):
    """
    This does the main loop over search results and user directories
    It has two paths it can take. One is the "single album" path
    The other is the multi-media path.
    """
    album_id = album["id"]
    artist_name = album["artist"]["artistName"]
    artist_id = album["artistId"]
    results = search_cache[album_id]
    for allowed_filetype in allowed_filetypes:
        logger.info(f"Checking for Quality: {allowed_filetype}")
        releases = lidarr.get_album(album_id)["releases"]
        num_releases = len(releases)
        for _ in range(0, num_releases):
            if len(releases) == 0:
                break
            release = choose_release(artist_name, releases)
            releases.remove(release)
            release_id = release["id"]
            all_tracks = lidarr.get_tracks(artistId=artist_id, albumId=album_id, albumReleaseId=release_id)
            found, downloads = try_enqueue(all_tracks, results, allowed_filetype)

            if found:
                grab_list[album_id] = {}
                grab_list[album_id]["files"] = downloads
                grab_list[album_id]["filetype"] = allowed_filetype
                grab_list[album_id]["title"] = album["title"]
                grab_list[album_id]["artist"] = artist_name
                grab_list[album_id]["year"] = album["releaseDate"][0:4]
                return True
            elif len(release["media"]) > 1:
                found, downloads = try_multi_enqueue(release, all_tracks, results, allowed_filetype)
                if found:
                    grab_list[album_id] = {}
                    grab_list[album_id]["files"] = downloads
                    grab_list[album_id]["filetype"] = allowed_filetype
                    grab_list[album_id]["title"] = album["title"]
                    grab_list[album_id]["artist"] = artist_name
                    grab_list[album_id]["year"] = album["releaseDate"][0:4]
                    return True
    return False


def search_and_queue(albums):
    grab_list = {}
    failed_grab = []
    failed_search = []
    for album in albums:
        if search_for_album(album):
            if not find_download(album, grab_list):
                failed_grab.append(album)

        else:
            failed_search.append(album)
    return grab_list, failed_search, failed_grab


def process_completed_album(album_data, failed_grab):
    os.chdir(slskd_download_dir)
    import_folder_name = sanitize_folder_name(album_data["artist"] + " - " + album_data["title"] + " (" + album_data["year"] + ")")
    import_folder_fullpath = os.path.join(slskd_download_dir, import_folder_name)
    lidarr_import_fullpath = os.path.join(lidarr_download_dir, import_folder_name)
    album_data["import_folder"] = lidarr_import_fullpath
    rm_dirs = []
    moved_files_history = []
    if not os.path.exists(import_folder_fullpath):
        os.mkdir(import_folder_fullpath)
    for file in album_data["files"]:
        file_folder = file["file_dir"].split("\\")[-1]
        filename = file["filename"].split("\\")[-1]
        src_folder = os.path.join(slskd_download_dir, file_folder)
        if src_folder not in rm_dirs:
            rm_dirs.append(src_folder)  # Multi disk albums are sometimes in multiple folders. eg. CD01 CD02. So we need to clean up both
        src_file = os.path.join(src_folder, filename)
        if "disk_no" in file and "disk_count" in file and file["disk_count"] > 1:
            filename = f"Disk {file['disk_no']} - {filename}"
        dst_file = os.path.join(import_folder_fullpath, filename)
        file["import_path"] = dst_file
        try:
            shutil.move(src_file, dst_file)
            moved_files_history.append((src_file, dst_file))
        except Exception:
            logger.exception(f"Failed to move: {file['filename']} to temp location for import into Lidarr. Rolling back...")
            for src, dst in reversed(moved_files_history):
                try:
                    shutil.move(dst, src)
                except Exception:
                    logger.exception(f"Critical failure during rollback: could not move {dst} back to {src}")
            try:
                os.rmdir(import_folder_fullpath)
            except OSError:
                logger.warning(f"Could not remove temp import directory {import_folder_fullpath}")
            failed_grab.append(lidarr.get_album(album_data["album_id"]))
            return
    else:  # Only runs if all files are successfully moved
        for rm_dir in rm_dirs:
            if not rm_dir == import_folder_fullpath:
                try:
                    os.rmdir(rm_dir)
                except OSError:
                    logger.warning(f"Skipping removal of {rm_dir} because it's not empty.")
        if lidarr_disable_sync:
            logger.info(f"Sync disabled. Skipping Lidarr import of {album_data['artist']} - {album_data['title']}")
            return
        logger.info(f"Attempting Lidarr import of {album_data['artist']} - {album_data['title']}")
        for file in album_data["files"]:
            try:  # This sometimes fails. No idea why. Nor do we care. We try and that's what matters
                song = music_tag.load_file(file["import_path"])
                if "disk_no" in file:
                    song["discnumber"] = file["disk_no"]
                    song["totaldiscs"] = file["disk_count"]

                song["albumartist"] = album_data["artist"]
                song["album"] = album_data["title"]
                song.save()
            except Exception:
                logger.exception(f"Error writing tags for: {file['import_path']}")
        command = lidarr.post_command(
            name="DownloadedAlbumsScan",
            path=album_data["import_folder"],
        )  # Album all tagged up and in a correctly named folder. This should work more reliably
        logger.info(f"Starting Lidarr import for: {album_data['title']} ID: {command['id']}")

        while True:
            current_task = lidarr.get_command(command["id"])
            if current_task["status"] == "completed" or current_task["status"] == "failed":
                break
            time.sleep(2)

        try:
            logger.info(f"{current_task['commandName']} {current_task['message']} from: {current_task['body']['path']}")

            if "Failed" in current_task["message"]:
                move_failed_import(current_task["body"]["path"])
                failed_grab.append(lidarr.get_album(album_data["album_id"]))
        except Exception:
            logger.exception("Error printing lidarr task message")
            logger.error(current_task)


def monitor_downloads(grab_list, failed_grab):
    def delete_album(reason):
        cancel_and_delete(grab_list[album_id]["files"])
        logger.info(f"{reason} Album: {grab_list[album_id]['title']} Artist: {grab_list[album_id]['artist']}")
        del grab_list[album_id]
        failed_grab.append(lidarr.get_album(album_id))

    while True:
        total_albums = len(grab_list)
        # Deal with the problems.
        #    "Completed, Cancelled", Abort album as failed
        #    "Completed, TimedOut",  Abort album as failed
        #    "Completed, Errored",   Abort album as failed
        #    "Completed, Aborted",   Abort album as failed
        #    "Completed, Rejected",  Retry. Some users have a max grab count. We need to check if ALL files are Rejected first.
        # We're going to need to drop items out of the list. So we might have to resort to enumerating the keys so we don't hit issues.
        done_count = 0
        for album_id in list(grab_list.keys()):
            if slskd_download_status(grab_list[album_id]["files"]):
                album_done, problems, queued = downloads_all_done(grab_list[album_id]["files"])  # Lets check to see what status the files have
                if "count_start" not in grab_list[album_id]:
                    grab_list[album_id]["count_start"] = time.time()
                if (time.time() - grab_list[album_id]["count_start"]) >= stalled_timeout:  # Album is taking too long. Bail out regardless
                    delete_album("Timeout waiting for download of")
                    continue
                if queued == len(grab_list[album_id]["files"]):  # Shorter time out for whole albums in "Queued, Remotely"
                    if (time.time() - grab_list[album_id]["count_start"]) >= remote_queue_timeout:
                        delete_album("Timeout waiting for download of")
                        continue
                done_count += album_done
                if problems is not None:
                    logger.debug("We got problems!")
                    for file in problems:
                        logger.debug(f"Checking {file['filename']}")
                        match file["status"]["state"]:
                            case (
                                "Completed, Cancelled" | "Completed, TimedOut" | "Completed, Errored" | "Completed, Aborted"
                            ):  # Normal errors. We'll retry a few times as sometumes the error is transient
                                abort = False
                                if len(problems) == len(grab_list[album_id]["files"]):
                                    delete_album("Failed grab of")
                                    break
                                for download_file in grab_list[album_id]["files"]:
                                    if file["filename"] == download_file["filename"]:
                                        if "retry" not in download_file:
                                            download_file["retry"] = 0
                                        download_file["retry"] += 1
                                        if download_file["retry"] < 5:
                                            retry = download_file["retry"]
                                            size = file["size"]
                                            data_dict = [{"filename": file["filename"], "size": size}]
                                            logger.info(f"Download error. Requeue file: {file['filename']}")
                                            requeue = slskd_do_enqueue(
                                                file["username"],
                                                data_dict,
                                                file["file_dir"],
                                            )
                                            if requeue is not None:
                                                download_file["id"] = requeue[0]["id"]
                                                download_file["retry"] = retry
                                                time.sleep(1)
                                                _ = slskd_download_status(grab_list[album_id]["files"])  # Refresh the status of the files to prevent issues.
                                            else:
                                                delete_album("Failed grab of")
                                                abort = True  # Move to the next album so we don't block or overload a remote user
                                                break
                                        else:
                                            # Delete from album list add to failures
                                            delete_album("Failed grab of")
                                            abort = True  # As above.
                                            break
                                if abort:
                                    break
                            case "Completed, Rejected":
                                # Do a measured retry. This is often a soft failure due to grab limits. Check if any files worked then go from there.
                                # This needs a recode. But it works for now.
                                # In the recode we need to test to see if we are getting multiple albums from the same user and temper our retries based on
                                # those other album(s) completing.
                                # If we aren't in that condition we need to fall back to per file retry counts as files will also be rejected if the file is
                                # too long or too short based on the share record. This can happen when people re-tag media but don't rescan media.
                                # Also I've seen cases of single files out of a set being in the "not shared" category.
                                if len(problems) == len(grab_list[album_id]["files"]):
                                    delete_album("Failed grab of")  # They are all rejected. Usually this happens because of misconfigurations. Files appear in search but aren't shared.
                                    break
                                else:
                                    if "rejected_retries" not in grab_list[album_id]:
                                        grab_list[album_id]["rejected_retries"] = 0
                                    working_count = len(grab_list[album_id]["files"]) - len(problems)
                                    for gfile in grab_list[album_id]["files"]:
                                        if gfile["status"]["state"] in [
                                            "Completed, Succeeded",
                                            "Queued, Remotely",
                                            "Queued, Locally",
                                        ]:
                                            working_count -= 1
                                    if working_count == 0:
                                        if grab_list[album_id]["rejected_retries"] < int(len(grab_list[album_id]["files"]) * 1.2):  # Little bit of wiggle room here
                                            abort = False
                                            for gfile in grab_list[album_id]["files"]:
                                                if gfile["filename"] == file["filename"]:
                                                    size = file["size"]
                                                    data_dict = [
                                                        {
                                                            "filename": file["filename"],
                                                            "size": size,
                                                        }
                                                    ]
                                                    logger.info(f"Download error. Requeue file: {file['filename']}")
                                                    requeue = slskd_do_enqueue(
                                                        file["username"],
                                                        data_dict,
                                                        file["file_dir"],
                                                    )
                                                    if requeue is not None:
                                                        gfile["id"] = requeue[0]["id"]
                                                        grab_list[album_id]["rejected_retries"] += 1
                                                        _ = slskd_download_status(grab_list[album_id]["files"])
                                                        abort = True
                                                        break
                                                    else:
                                                        cancel_and_delete(grab_list[album_id]["files"])
                                                        logger.info(f"Failed grab of Album: {grab_list[album_id]['title']} Artist: {grab_list[album_id]['artist']}")
                                                        del grab_list[album_id]
                                                        failed_grab.append(lidarr.get_album(album_id))  # Not sure if returns an array or not
                                                        abort = True
                                                        break
                                            if abort:
                                                break
                                        else:
                                            delete_album("Failed grab of")
                                            break
                            case _:
                                logger.error(
                                    "Not sure how I got here. This shouldn't be possible for problem files!"
                                )  # This really should be impossible to reach. But is required to round out the case statement.
                else:
                    if album_done:
                        album_data = grab_list[album_id]
                        album_data["album_id"] = album_id
                        logger.info(f"Completed download of Album: {album_data['title']} Artist: {album_data['artist']}")
                        process_completed_album(album_data, failed_grab)
                        del grab_list[album_id]

            else:
                if "error_count" not in grab_list[album_id]:
                    grab_list[album_id]["error_count"] = 0
                grab_list[album_id]["error_count"] += 1
            # I dunno. slskd might be broken? Or the user deleted things? I've never seen this so I have no idea what we should do here. It most likely would mean SLSKD is down.
            # So we probably want to abort everything because cleanup would be impossible.

        if len(grab_list) < 1:  # We remove items from the grab list once they are downloaded or aborted. So when there are no grabs left, we are done!
            break

        time.sleep(5)  # Wait for things to progress and start the checks again.


def grab_most_wanted(albums):
    """
    This is the "main loop" that calls all the functions to do all the work.
    Basic flow per item is as follows:
    Perform coarse search
    Check search results for a match
    enqueue download
    After that has happened for all the downloads it then shifts to monitoring the downloads:
    Monitor download and perform retries and/or requeues.
    When all completed, call lidarr to import
    """

    grab_list, failed_search, failed_grab = search_and_queue(albums)

    total_albums = len(grab_list)
    logger.info(f"Total Downloads added: {total_albums}")
    for album_id in grab_list:
        logger.info(f"Album: {grab_list[album_id]['title']} Artist: {grab_list[album_id]['artist']}")
    logger.info(f"Failed to grab: {len(failed_grab)}")
    for album in failed_grab:
        logger.info(f"Album: {album['title']} Artist: {album['artist']['artistName']}")

    logger.info("-------------------")
    logger.info(f"Waiting for downloads... monitor at: {''.join([slskd_host_url, slskd_url_base, 'downloads'])}")

    monitor_downloads(grab_list, failed_grab)

    count = len(failed_search) + len(failed_grab)
    for album in failed_search:
        album_title = album["title"]
        artist_name = album["artist"]["artistName"]
        logger.info(f"Search failed for Album: {album_title} - Artist: {artist_name}")
    for album in failed_grab:
        album_title = album["title"]
        artist_name = album["artist"]["artistName"]
        logger.info(f"Download failed for Album: {album_title} - Artist: {artist_name}")

    return count
    # if enable_search_denylist:
    #    save_search_denylist(denylist_file_path, search_denylist)


def move_failed_import(src_path):
    failed_imports_dir = "failed_imports"

    if not os.path.exists(failed_imports_dir):
        os.makedirs(failed_imports_dir)

    folder_name = os.path.basename(src_path)
    target_path = os.path.join(failed_imports_dir, folder_name)

    counter = 1
    while os.path.exists(target_path):
        target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
        counter += 1

    if os.path.exists(folder_name):
        shutil.move(folder_name, target_path)
        logger.info(f"Failed import moved to: {target_path}")


def is_docker():
    return os.getenv("IN_DOCKER") is not None


def slskd_version_check(version, target="0.22.2"):
    version_tuple = tuple(map(int, version.split(".")[:3]))
    target_tuple = tuple(map(int, target.split(".")[:3]))
    return version_tuple > target_tuple


def setup_logging(config, var_dir):
    from logging.handlers import RotatingFileHandler

    if "Logging" in config:
        log_config = config["Logging"]
    else:
        log_config = DEFAULT_LOGGING_CONF

    level = log_config.get("level", DEFAULT_LOGGING_CONF["level"])
    fmt = log_config.get("format", DEFAULT_LOGGING_CONF["format"])
    datefmt = log_config.get("datefmt", DEFAULT_LOGGING_CONF["datefmt"])

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

    log_to_file = config.getboolean("Logging", "log_to_file", fallback=False)
    if log_to_file:
        log_filename = config.get("Logging", "log_file", fallback="soularr.log")
        log_file_path = os.path.join(var_dir, log_filename)
        max_bytes = config.getint("Logging", "max_bytes", fallback=1048576)
        backup_count = config.getint("Logging", "backup_count", fallback=3)

        file_handler = RotatingFileHandler(log_file_path, maxBytes=max_bytes, backupCount=backup_count)
        file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        logging.getLogger().addHandler(file_handler)
        logger.info(f"Logging to file: {log_file_path}")


def get_current_page(path: str, default_page=1) -> int:
    if os.path.exists(path):
        with open(path, "r") as file:
            page_string = file.read().strip()

            if page_string:
                return int(page_string)
            else:
                with open(path, "w") as file:
                    file.write(str(default_page))
                return default_page
    else:
        with open(path, "w") as file:
            file.write(str(default_page))
        return default_page


def update_current_page(path: str, page: str) -> None:
    with open(path, "w") as file:
        file.write(page)


def get_records(missing: bool) -> list:
    try:
        wanted = lidarr.get_wanted(
            page_size=page_size,
            sort_dir="ascending",
            sort_key="albums.title",
            missing=missing,
        )
    except ConnectionError as ex:
        logger.error(f"An error occurred when attempting to get records: {ex}")
        return []

    total_wanted = wanted["totalRecords"]

    wanted_records = []
    if search_type == "all":
        page = 1
        while len(wanted_records) < total_wanted:
            try:
                wanted = lidarr.get_wanted(
                    page=page,
                    page_size=page_size,
                    sort_dir="ascending",
                    sort_key="albums.title",
                    missing=missing,
                )
            except ConnectionError as ex:
                logger.error(f"Failed to grab record: {ex}")
            wanted_records.extend(wanted["records"])
            page += 1

    elif search_type == "incrementing_page":
        page = get_current_page(current_page_file_path)
        try:
            wanted_records = lidarr.get_wanted(
                page=page,
                page_size=page_size,
                sort_dir="ascending",
                sort_key="albums.title",
                missing=missing,
            )["records"]
        except ConnectionError as ex:
            logger.error(f"Failed to grab record: {ex}")
        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, str(page))

    elif search_type == "first_page":
        wanted_records = wanted["records"]

    else:
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)

        raise ValueError(f"[Search Settings] - {search_type = } is not valid")

    try:
        queued_records = lidarr.get_queue(sort_dir="ascending", sort_key="albums.title")
        total_queued = queued_records["totalRecords"]
        current_queue = queued_records["records"]

        if queued_records["pageSize"] < total_queued:
            page = 2
            while len(current_queue) < total_queued:
                try:
                    next_page = lidarr.get_queue(page=page, sort_key="albums.title", sort_dir="ascending")
                except ConnectionError as ex:
                    logger.error(f"Failed to get queue details: {ex}")
                    break
                current_queue.extend(next_page["records"])
                page += 1

        queued_album_ids = []

        for record in current_queue:
            if "albumId" in record:
                queued_album_ids.append(record["albumId"])
            else:
                logger.warning(f"Dropping entry due to missing key in keylist: [{record.keys()}]")

        wanted_records_not_queued = []
        for record in wanted_records:
            for release in record["releases"]:
                if release["albumId"] in queued_album_ids:
                    logging.info(f"Skipping record '{record['title']}' because it's already in download queue")
                    break
            else:  # This only runs if the loop is broken out of. Saves on all the boolean found= stuff
                wanted_records_not_queued.append(record)
        if len(wanted_records_not_queued) > 0:
            wanted_records = wanted_records_not_queued
        else:
            logging.info("No records wanted that arent already queued")
            wanted_records = []
    except ConnectionError as ex:
        logger.error(f"Failed to get queue details so not filtering based on queue: {ex}")

    return wanted_records


def load_search_denylist(file_path):
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except (json.JSONDecodeError, IOError) as ex:
        logger.warning(f"Error loading search denylist: {ex}. Starting with empty denylist.")
        return {}


def save_search_denylist(file_path, denylist):
    try:
        with open(file_path, "w") as file:
            json.dump(denylist, file, indent=2)
    except IOError as ex:
        logger.error(f"Error saving search denylist: {ex}")


def is_search_denylisted(denylist, album_id, max_failures):
    album_key = str(album_id)
    if album_key in denylist:
        return denylist[album_key]["failures"] >= max_failures
    return False


def update_search_denylist(denylist, album_id, success):
    album_key = str(album_id)
    current_datetime = datetime.now()
    current_datetime_str = current_datetime.strftime("%Y-%m-%dT%H:%M:%S")

    if success:
        if album_key in denylist:
            logger.info("Removing album from denylist: %s", denylist[album_key]["album_id"])
            del denylist[album_key]
    else:
        logger.info("Adding album to denylist: " + album_key)
        if album_key in denylist:
            denylist[album_key]["failures"] += 1
            denylist[album_key]["last_attempt"] = current_datetime_str
        else:
            denylist[album_key] = {
                "failures": 1,
                "last_attempt": current_datetime_str,
                "album_id": album_id,
            }


def main():
    global \
        slskd_api_key, \
        lidarr_api_key, \
        lidarr_download_dir, \
        lidarr_disable_sync, \
        slskd_download_dir, \
        lidarr_host_url, \
        slskd_host_url, \
        stalled_timeout, \
        remote_queue_timeout, \
        delete_searches, \
        slskd_url_base, \
        ignored_users, \
        search_type, \
        search_source, \
        download_filtering, \
        use_extension_whitelist, \
        extensions_whitelist, \
        search_sources, \
        minimum_match_ratio, \
        page_size, \
        remove_wanted_on_failure, \
        enable_search_denylist, \
        max_search_failures, \
        use_most_common_tracknum, \
        allow_multi_disc, \
        accepted_countries, \
        skip_region_check, \
        accepted_formats, \
        allowed_filetypes, \
        lock_file_path, \
        config_file_path, \
        failure_file_path, \
        current_page_file_path, \
        denylist_file_path, \
        search_blacklist, \
        lidarr, \
        slskd, \
        config, \
        logger, \
        search_cache, \
        folder_cache, \
        broken_user

    # Let's allow some overrides to be passed to the script
    parser = argparse.ArgumentParser(description="""Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd""")

    default_data_directory = os.getcwd()

    if is_docker():
        default_data_directory = "/data"

    parser.add_argument(
        "-c",
        "--config-dir",
        default=default_data_directory,
        const=default_data_directory,
        nargs="?",
        type=str,
        help="Config directory (default: %(default)s)",
    )

    parser.add_argument(
        "-v",
        "--var-dir",
        default=default_data_directory,
        const=default_data_directory,
        nargs="?",
        type=str,
        help="Var directory (default: %(default)s)",
    )

    parser.add_argument(
        "--no-lock-file",
        action="store_false",
        dest="lock_file",
        default=True,
        help="Disable lock file creation",
    )

    args = parser.parse_args()

    lock_file_path = os.path.join(args.var_dir, ".soularr.lock")
    config_file_path = os.path.join(args.config_dir, "config.ini")
    failure_file_path = os.path.join(args.var_dir, "failure_list.txt")
    current_page_file_path = os.path.join(args.var_dir, ".current_page.txt")
    denylist_file_path = os.path.join(args.var_dir, "search_denylist.json")

    if not is_docker() and os.path.exists(lock_file_path) and args.lock_file:
        logger.info(f"Soularr instance is already running.")
        sys.exit(1)

    try:
        if not is_docker() and args.lock_file:
            with open(lock_file_path, "w") as lock_file:
                lock_file.write("locked")

        # Disable interpolation to make storing logging formats in the config file much easier
        config = configparser.ConfigParser(interpolation=EnvInterpolation())

        if os.path.exists(config_file_path):
            config.read(config_file_path)
        else:
            if is_docker():
                logger.error(
                    'Config file does not exist! Please mount "/data" and place your "config.ini" file there. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.'
                )
                logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            else:
                logger.error(
                    "Config file does not exist! Please place it in the working directory. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else."
                )
                logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)
            sys.exit(0)

        slskd_api_key = config["Slskd"]["api_key"]
        lidarr_api_key = config["Lidarr"]["api_key"]

        lidarr_download_dir = config["Lidarr"]["download_dir"]
        lidarr_disable_sync = config.getboolean("Lidarr", "disable_sync", fallback=False)

        slskd_download_dir = config["Slskd"]["download_dir"]

        lidarr_host_url = config["Lidarr"]["host_url"]
        slskd_host_url = config["Slskd"]["host_url"]

        stalled_timeout = config.getint("Slskd", "stalled_timeout", fallback=3600)
        remote_queue_timeout = config.getint("Slskd", "remote_queue_timeout", fallback=300)

        delete_searches = config.getboolean("Slskd", "delete_searches", fallback=True)

        slskd_url_base = config.get("Slskd", "url_base", fallback="/")

        ignored_users = config.get("Search Settings", "ignored_users", fallback="").split(",")
        search_blacklist = config.get("Search Settings", "search_blacklist", fallback="").split(",")
        search_blacklist = [word.strip() for word in search_blacklist if word.strip()]
        search_type = config.get("Search Settings", "search_type", fallback="first_page").lower().strip()
        search_source = config.get("Search Settings", "search_source", fallback="missing").lower().strip()

        download_filtering = config.getboolean("Download Settings", "download_filtering", fallback=False)
        use_extension_whitelist = config.getboolean("Download Settings", "use_extension_whitelist", fallback=False)
        extensions_whitelist = config.get("Download Settings", "extensions_whitelist", fallback="txt,nfo,jpg").split(",")

        search_sources = [search_source]
        if search_sources[0] == "all":
            search_sources = ["missing", "cutoff_unmet"]

        minimum_match_ratio = config.getfloat("Search Settings", "minimum_filename_match_ratio", fallback=0.5)
        page_size = config.getint("Search Settings", "number_of_albums_to_grab", fallback=10)
        remove_wanted_on_failure = config.getboolean("Search Settings", "remove_wanted_on_failure", fallback=True)
        enable_search_denylist = config.getboolean("Search Settings", "enable_search_denylist", fallback=False)
        max_search_failures = config.getint("Search Settings", "max_search_failures", fallback=3)

        use_most_common_tracknum = config.getboolean("Release Settings", "use_most_common_tracknum", fallback=True)
        allow_multi_disc = config.getboolean("Release Settings", "allow_multi_disc", fallback=True)

        default_accepted_countries = "Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada"
        default_accepted_formats = "CD,Digital Media,Vinyl"
        accepted_countries = config.get("Release Settings", "accepted_countries", fallback=default_accepted_countries).split(",")
        skip_region_check = config.getboolean("Release Settings", "skip_region_check", fallback=False)
        accepted_formats = config.get("Release Settings", "accepted_formats", fallback=default_accepted_formats).split(",")

        raw_filetypes = config.get("Search Settings", "allowed_filetypes", fallback="flac,mp3")

        if "," in raw_filetypes:
            allowed_filetypes = raw_filetypes.split(",")
        else:
            allowed_filetypes = [raw_filetypes]

        setup_logging(config, args.var_dir)

        # Init directory cache. The wide search returns all the data we need. This prevents us from hammering the users on the Soulseek network
        search_cache = {}
        folder_cache = {}
        broken_user = []

        slskd = slskd_api.SlskdClient(host=slskd_host_url, api_key=slskd_api_key, url_base=slskd_url_base)
        lidarr = LidarrAPI(lidarr_host_url, lidarr_api_key)
        wanted_records = []
        try:
            for source in search_sources:
                logging.debug(f"Getting records from {source}")
                missing = source == "missing"
                wanted_records.extend(get_records(missing))
        except ValueError as ex:
            logger.error(f"An error occurred: {ex}")
            logger.error("Exiting...")
            sys.exit(0)

        if len(wanted_records) > 0:
            try:
                filtered = filter_list(wanted_records)
                if filtered is not None:
                    failed = grab_most_wanted(filtered)
                else:
                    failed = 0
                    logger.info("No releases wanted that aren't on the deny list and/or blacklisted")
            except Exception:
                logger.exception("Fatal error! Exiting...")

                if os.path.exists(lock_file_path) and not is_docker():
                    os.remove(lock_file_path)
                sys.exit(0)
            if failed == 0:
                logger.info("Soularr finished. Exiting...")
                slskd.transfers.remove_completed_downloads()
            else:
                if remove_wanted_on_failure:
                    logger.info(f'{failed}: releases failed to find a match in the search results. View "failure_list.txt" for list of failed albums.')
                else:
                    logger.info(f"{failed}: releases failed to find a match in the search results and are still wanted.")
                slskd.transfers.remove_completed_downloads()
        else:
            logger.info("No releases wanted. Exiting...")

    finally:
        # Remove the lock file after activity is done
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)


if __name__ == "__main__":
    main()
