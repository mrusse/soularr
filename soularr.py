#!/usr/bin/env python

import difflib
import json
import math
import os
import re
import shutil
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from typing import Any

import music_tag
import slskd_api
from pyarr import LidarrAPI
from requests import HTTPError

from argparser import SoularrArgParser
from config import SoularrConfig
from soularr_types import (GrabItem, Record, Release, SlskDirectory,
                           SlskdSearch, SlskFileEntry, SlskFileInfo,
                           SlskUserUploadInfo, Track, map_raw_record_to_record,
                           map_raw_slskd_dir_to_dir, map_raw_track_to_track,
                           map_raw_user_upload_info_to_user_upload_info)
from utils import (ALL, CUTOFF_UNMET, MISSING, is_docker, logger,
                   setup_logging, slskd_version_check)


class Soularr:
    def __init__(self, lidarr: LidarrAPI, slskd: slskd_api.SlskdClient, arg_parser: SoularrArgParser, soularr_config: SoularrConfig) -> None:
        self.arg_parser = arg_parser
        self.soularr_config = soularr_config
        self.lidarr = lidarr
        self.slskd = slskd

        self.ignored_users = self.soularr_config.get_ignored_users()
        
        self.grab_list: list[GrabItem] = []

    def album_match(self, lidarr_tracks: list[Track], slskd_tracks: list[SlskFileEntry], username: str, filetype: str):
        counted = []
        total_match = 0.0

        lidarr_album = self.get_lidarr_album(lidarr_tracks[0].albumId)
        lidarr_album_name = lidarr_album.title

        for lidarr_track in lidarr_tracks:
            lidarr_filename = lidarr_track.title + "." + filetype.split(" ")[0]
            best_match = 0.0

            for slskd_track in slskd_tracks:
                slskd_filename = slskd_track.filename

                #Try to match the ratio with the exact filenames
                ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

                #If ratio is a bad match try and split off (with " " as the separator) the garbage at the start of the slskd_filename and try again
                ratio = self.check_ratio(" ", ratio, lidarr_filename, slskd_filename)
                #Same but with "_" as the separator
                ratio = self.check_ratio("_", ratio, lidarr_filename, slskd_filename)

                #Same checks but preappend album name.
                ratio = self.check_ratio("", ratio, lidarr_album_name + " " + lidarr_filename, slskd_filename)
                ratio = self.check_ratio(" ", ratio, lidarr_album_name + " " + lidarr_filename, slskd_filename)
                ratio = self.check_ratio("_", ratio, lidarr_album_name + " " + lidarr_filename, slskd_filename)

                if ratio > best_match:
                    best_match = ratio

            if best_match > self.soularr_config.get_minimum_match_ratio():
                counted.append(lidarr_filename)
                total_match += best_match

        if len(counted) == len(lidarr_tracks) and username not in self.ignored_users:
            logger.info(f"Found match for '{lidarr_album_name}' from user '{username}' for {len(counted)} tracks! Track attributes: {filetype}")
            logger.info(f"Average sequence match ratio: {total_match/len(counted)}")
            logger.info("SUCCESSFUL MATCH")
            logger.info("-------------------")
            return True
        logger.info(f"Only found {len(counted)} matching tracks out of {len(lidarr_tracks)} for user '{username}' with track attributes: {filetype}")
        return False


    def check_ratio(self, separator, ratio, lidarr_filename, slskd_filename):
        if ratio < self.soularr_config.get_minimum_match_ratio():
            if separator != "":
                lidarr_filename_word_count = len(lidarr_filename.split()) * -1
                truncated_slskd_filename = " ".join(slskd_filename.split(separator)[lidarr_filename_word_count:])
                ratio = difflib.SequenceMatcher(None, lidarr_filename, truncated_slskd_filename).ratio()
            else:
                ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            return ratio
        return ratio


    def album_track_num(self, directory: SlskDirectory):
        files = directory.files
        # e.g. ["flac 24/192", "flac 16/44.1", "flac", "mp3 320", "mp3"] -> ["flac","mp3"]
        allowed_filetypes_no_attributes = list(set(item.split(" ")[0] for item in self.soularr_config.get_allowed_filetypes()))
        count = 0
        index = -1
        filetype = ""
        for file in files:
            if file.filename.split(".")[-1] in allowed_filetypes_no_attributes:
                new_index = allowed_filetypes_no_attributes.index(file.filename.split(".")[-1])

                if index == -1:
                    index = new_index
                    filetype = allowed_filetypes_no_attributes[index]
                elif new_index != index:
                    filetype = ""
                    break

                count += 1

        return_data =	{
            "count": count,
            "filetype": filetype
        }
        return return_data


    def sanitize_folder_name(self, folder_name):
        valid_characters = re.sub(r'[<>:."/\\|?*]', '', folder_name)
        return valid_characters.strip()


    def cancel_and_delete(self, delete_dir, username, files):
        for file in files:
            self.slskd.transfers.cancel_download(username = username, id = file['id'])

        os.chdir(self.soularr_config.get_slskd_download_dir())

        if os.path.exists(delete_dir):
            shutil.rmtree(delete_dir)


    def release_trackcount_mode(self, releases):
        track_count = {}

        for release in releases:
            trackcount = release.trackCount
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


    def choose_release(self, album_id, artist_name):
        album = self.get_lidarr_album(album_id)
        releases = album.releases
        most_common_trackcount = self.release_trackcount_mode(releases)

        for release in releases:
            country = release.country[0] if release.country else None

            if release.format[1] == 'x' and self.soularr_config.get_allow_multi_disc():
                format_accepted = release.format.split("x", 1)[1] in self.soularr_config.get_accepted_formats()
            else:
                format_accepted = release.format in self.soularr_config.get_accepted_formats()

            if self.soularr_config.get_use_most_common_tracknum():
                if release.trackCount == most_common_trackcount:
                    track_count_bool = True
                else:
                    track_count_bool = False
            else:
                track_count_bool = True

            if ((self.soularr_config.get_skip_region_check() or country in self.soularr_config.get_accepted_countries())
                and format_accepted
                and release.status == "Official"
                and track_count_bool):

                logger.info(", ".join([
                    f"Selected release for {artist_name}: {release.status}",
                    str(country),
                    release.format,
                    f"Mediums: {release.mediumCount}",
                    f"Tracks: {release.trackCount}",
                    f"ID: {release.id}",
                ]))

                return release

        if self.soularr_config.get_use_most_common_tracknum():
            for release in releases:
                if release.trackCount == most_common_trackcount:
                    default_release = release
        else:
            default_release = releases[0]

        return default_release


    def verify_filetype(self, file: SlskFileInfo, allowed_filetype: str) -> bool:
        current_filetype = file.filename.split(".")[-1]
        bitdepth = None
        samplerate = None
        bitrate = None

        if file.bitRate:
            bitrate = file.bitRate
        if file.sampleRate:
            samplerate = file.sampleRate
        if file.bitDepth:
            bitdepth = file.bitDepth

        #Check if the types match up for the current files type and the current type from the config
        if current_filetype != allowed_filetype.split(" ")[0]:
            return False
        
        #Check if the current type from the config specifies other attributes than the filetype (bitrate etc)
        if " " not in allowed_filetype:
            #If no bitrate or other info then it is a match so return true
            return True
        
        selected_attributes = allowed_filetype.split(" ")[1]
        #If it is a bitdepth/samplerate pair instead of a simple bitrate
        if "/" in selected_attributes:
            selected_bitdepth = selected_attributes.split("/")[0]
            try:
                selected_samplerate = str(int(float(selected_attributes.split("/")[1]) * 1000))
            except (ValueError, IndexError):
                logger.warning("Invalid samplerate in selected_attributes")
                return False

            if bitdepth and samplerate and str(bitdepth) == str(selected_bitdepth) and str(samplerate) == str(selected_samplerate):
                return True
            else:
                return False
        #If it is a bitrate
        else:
            selected_bitrate = selected_attributes
            if bitrate and str(bitrate) == str(selected_bitrate):
                return True
            else:
                return False


    def search_and_download(self, grab_list: list[GrabItem], query: str, tracks: list[Track], track: Track, artist_name: str, release: Release):
        raw_search = self.slskd.searches.search_text(searchText = query,
                                            searchTimeout = self.soularr_config.get_search_timeout(),
                                            filterResponses = True,
                                            maximumPeerQueueLength = self.soularr_config.get_maximum_peer_queue(),
                                            minimumPeerUploadSpeed = self.soularr_config.get_minimum_peer_upload_speed())
        search = SlskdSearch(**raw_search)

        track_num = len(tracks)

        while True:
            if self.slskd.searches.state(search.id)['state'] != 'InProgress':
                break
            time.sleep(1)

        # map search results to SlskUserUploadInfo dataclass
        search_responses = self.get_slskd_search_responses(search.id)
        logger.info(f"Search returned {len(search_responses)} results")

        for allowed_filetype in self.soularr_config.get_allowed_filetypes():
            logger.info(f"Searching for matches with selected attribute: {allowed_filetype}")

            for result in self.get_slskd_search_responses(search.id):
                username = result.username
                logger.info(f"Parsing result from user '{username}' with {result.fileCount} file(s)")
                files = result.files

                for file in files:
                    logger.debug(f"Checking file '{file.filename}' from user '{username}'")
                    if self.verify_filetype(file, allowed_filetype):

                        file_dir = file.filename.rsplit("\\",1)[0]
                        
                        try:
                            raw_slskd_directory = self.slskd.users.directory(username = username, directory = file_dir)
                            # version is > 0.22.2 returns a list with the single directory, <= 0.22.2 returns a single directory object
                            if isinstance(raw_slskd_directory, list) and len(raw_slskd_directory) > 0:
                                slskd_directory = raw_slskd_directory[0]
                                directory = map_raw_slskd_dir_to_dir(slskd_directory)
                            elif not isinstance(raw_slskd_directory, list):
                                slskd_directory = raw_slskd_directory
                                directory = map_raw_slskd_dir_to_dir(slskd_directory)
                            else:
                                logger.info(f"No directory info found for user: \"{username}\" and directory: \"{file_dir}\"")
                                continue
                        except HTTPError as error:
                            if error.response.status_code == 500:
                                logger.info(f"Error getting directory from user \"{username}\", inspect error in Slskd server: {error}")
                            continue
                        except Exception as error:
                            logger.info(f"Error getting directory from user \"{username}\": {error}")
                            logger.info(traceback.format_exc())
                            continue

                        tracks_info = self.album_track_num(directory)

                        if tracks_info['count'] == track_num and tracks_info['filetype'] != "" and self.album_match(tracks, directory.files, username, allowed_filetype):
                            for i in range(0, len(directory.files)):
                                directory.files[i].filename = file_dir + "\\" + directory.files[i].filename

                            folder_data = GrabItem(
                                artist_name=artist_name,
                                release=release,
                                dir=file_dir.split("\\")[-1],
                                discnumber=track.mediumNumber,
                                username=username,
                                directory=directory,
                            )
                            logger.debug(f"Adding folder to grab list: {asdict(folder_data)}")
                            self.grab_list.append(folder_data)

                            try:
                                self.slskd.transfers.enqueue(username = username, files = [asdict(file) for file in directory.files])
                                # Delete the search from SLSKD DB
                                if self.soularr_config.get_delete_searches():
                                    self.slskd.searches.delete(search.id)
                                return True
                            except Exception:
                                logger.warning(f"Error enqueueing tracks! Adding {username} to ignored users list.")
                                downloads = self.get_slskd_transfer_downloads(username)
                                if downloads is None:
                                    continue

                                for cancel_directory in downloads["directories"]:
                                    if cancel_directory["directory"] == directory.name:
                                        self.cancel_and_delete(file_dir.split("\\")[-1], username, cancel_directory["files"])
                                        self.grab_list.remove(folder_data)
                                        self.ignored_users.append(username)
                                continue
                        else:
                            logger.debug(f"Track count or album match failed for user '{username}'. Expected {track_num} tracks, found {tracks_info['count']} tracks with filetype '{tracks_info['filetype']}'")

        # Delete the search from SLSKD DB
        if self.soularr_config.get_delete_searches():
            self.slskd.searches.delete(search.id)
        return False


    def is_blacklisted(self, title: str) -> bool:
        blacklist = self.soularr_config.get_title_blacklist()
        for word in blacklist:
            if word != '' and word in title.lower():
                logger.info(f"Skipping {title} due to blacklisted word: {word}")
                return True
        return False


    def grab_most_wanted(self, albums: list[Record]) -> int:
        failed_searches = 0
        success = False
        search_denylist = {}

        is_search_denylist_enabled = self.soularr_config.get_enable_search_denylist()

        if is_search_denylist_enabled:
            search_denylist = self.load_search_denylist()

        for album in albums:
            logger.info(f"Processing album '{album.title}' by artist '{album.artist.artistName}'")
            artist_name = album.artist.artistName
            artist_id = album.artistId
            album_id = album.id
            album_title = album.title

            if is_search_denylist_enabled and self.is_search_denylisted(search_denylist, album_id, self.soularr_config.get_max_search_failures()):
                logger.info(f"Skipping denylisted album: {artist_name} - {album_title} (ID: {album_id})")
                continue

            release = self.choose_release(album_id, artist_name)

            release_id = release.id
            raw_all_tracks = self.lidarr.get_tracks(artistId = artist_id, albumId = album_id, albumReleaseId = release_id)
            all_tracks = [map_raw_track_to_track(track) for track in raw_all_tracks]

            #TODO: Right now if search_for_tracks is False. Multi disc albums will never be downloaded so we need to loop through media in releases even for albums
            if len(release.media) == 1:
                album = self.get_lidarr_album(album_id)
                album_title = album.title
                if self.is_blacklisted(album_title):
                    continue

                if len(album_title) == 1:
                    query = artist_name + " " + album_title
                else:
                    query = artist_name + " " + album_title if self.soularr_config.get_album_prepend_artist() else album_title

                logger.info(f"Searching album with single release: {query}")
                success = self.search_and_download(self.grab_list, query, all_tracks, all_tracks[0], artist_name, release)

            if not success and self.soularr_config.get_search_for_tracks():
                logger.info(f"Album search failed, searching individual tracks for album '{album_title}'")
                for media in release.media:
                    # Only consider tracks from the current release media
                    media_tracks = [track for track in all_tracks if track.mediumNumber == media.mediumNumber]

                    logger.info(f"Searching tracks under media '{media.mediumNumber}' with {len(media_tracks)} tracks for album '{album_title}'")

                    for track in media_tracks:
                        if self.is_blacklisted(track.title):
                            continue

                        if len(track.title) == 1:
                            query = artist_name + " " + track.title
                        else:
                            query = artist_name + " " + track.title if self.soularr_config.get_track_prepend_artist() else track.title

                        logger.info(f"Searching track: {query}")
                        success = self.search_and_download(self.grab_list, query, media_tracks, track, artist_name, release)

                        if success:
                            break

            if is_search_denylist_enabled:
                self.update_search_denylist(search_denylist, album_id, album.title, success)

            if not success:
                if self.soularr_config.get_remove_wanted_on_failure():
                    logger.error(f"Failed to find match for: {album_title} from artist: {artist_name}."
                        + ' Album removed from wanted list and added to "failure_list.txt"')

                    album.monitored = False
                    self.lidarr.upd_album(asdict(album))

                    current_datetime = datetime.now()
                    current_datetime_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")

                    failure_string = current_datetime_str + " - " + artist_name + ", " + album_title + ", " + str(album_id) + "\n"

                    with open(self.arg_parser.get_failure_file_path(), "a") as file:
                        file.write(failure_string)
                else:
                    logger.error(f"Failed to find match for '{album_title}' from artist '{artist_name}'")

                failed_searches += 1

            success = False

        logger.info("Downloads added:")
        downloads = self.slskd.transfers.get_all_downloads()

        for download in downloads:
            username = download['username']
            for dir in download['directories']:
                logger.info(f"Username: {username} Directory: {dir['directory']}")
        logger.info("-------------------")
        logger.info(f"Waiting for downloads (timeout {self.soularr_config.get_stalled_timeout()}s)... monitor at: {''.join([self.soularr_config.get_slskd_host_url(), self.soularr_config.get_slskd_url_base(), 'downloads'])}")

        time_count = 0

        while True:
            unfinished = 0
            for artist_folder in list(self.grab_list):
                username, dir = artist_folder.username, artist_folder.directory

                downloads = self.get_slskd_transfer_downloads(username)
                if downloads is None:
                    continue

                for directory in downloads["directories"]:
                    if directory["directory"] == dir.name:
                        # Generate list of errored or failed downloads
                        errored_files = [file for file in directory["files"] if file["state"] in [
                            'Completed, Cancelled',
                            'Completed, TimedOut',
                            'Completed, Errored',
                            'Completed, Rejected',
                        ]]
                        # Generate list of downloads still pending
                        pending_files = [file for file in directory["files"] if not 'Completed' in file["state"]]

                        # If we have errored files, cancel and remove ALL files so we can retry next time
                        if len(errored_files) > 0:
                            logger.error(f"FAILED: Username: {username} Directory: {dir.name}")
                            self.cancel_and_delete(artist_folder.dir, artist_folder.username, directory["files"])
                            self.grab_list.remove(artist_folder)
                        elif len(pending_files) > 0:
                            unfinished += 1

            if unfinished == 0:
                logger.info("All tracks finished downloading!")
                time.sleep(5)
                break

            time_count += 10

            if(time_count > self.soularr_config.get_stalled_timeout()):
                logger.info("Stall timeout reached! Removing stuck downloads...")
                if downloads is None or not isinstance(downloads, dict):
                    continue

                for directory in downloads.get("directories", []):
                    if directory["directory"] == dir.name:
                        #TODO: This does not seem to account for directories where the whole dir is stuck as queued.
                        #Either it needs to account for those or maybe soularr should just force clear out the downloads screen when it exits.
                        pending_files = [file for file in directory["files"] if not 'Completed' in file["state"]]

                        if len(pending_files) > 0:
                            logger.error(f"Removing Stalled Download: Username: {username} Directory: {dir.name}")
                            self.cancel_and_delete(artist_folder.dir, artist_folder.username, directory["files"])
                            self.grab_list.remove(artist_folder)

                time.sleep(5)
                break

            time.sleep(10)

        slskd_download_dir = self.soularr_config.get_slskd_download_dir()
        os.chdir(slskd_download_dir)

        commands = []
        self.grab_list.sort(key=lambda grab_item: grab_item.artist_name)

        for artist_folder in self.grab_list:
            artist_name = artist_folder.artist_name
            artist_name_sanitized = self.sanitize_folder_name(artist_name)
            logger.info(f"Tagging and moving files for artist '{artist_name}'")

            folder = artist_folder.dir

            if artist_folder.release.mediumCount > 1:
                for filename in os.listdir(folder):
                    artist_folder_id = artist_folder.release.albumId
                    album = self.get_lidarr_album(artist_folder_id)
                    album_name = album.title

                    if filename.split(".")[-1] in self.soularr_config.get_allowed_filetypes():
                        song = music_tag.load_file(os.path.join(folder,filename))
                        if song is None:
                            logger.warning(f"Unable to load file for tagging: {os.path.join(folder,filename)}")
                            continue
                        song['artist'] = artist_name
                        song['albumartist'] = artist_name
                        song['album'] = album_name
                        song['discnumber'] = artist_folder.discnumber
                        song.save()
                        logger.info(f"Tagged file '{os.path.join(folder, filename)}' with artist '{artist_name}', album '{album_name}', discnumber '{artist_folder.discnumber}'")

                    new_dir = os.path.join(artist_name_sanitized, self.sanitize_folder_name(album_name))

                    if not os.path.exists(artist_name_sanitized):
                        logger.info(f"Artist directory did not exist, creating: {artist_name_sanitized}")
                        os.mkdir(artist_name_sanitized)
                    if not os.path.exists(new_dir):
                        logger.info(f"Album directory did not exist, creating: {new_dir}")
                        os.mkdir(new_dir)

                    if os.path.exists(os.path.join(folder,filename)) and not os.path.exists(os.path.join(new_dir,filename)):
                        logger.info(f"Moving file '{os.path.join(folder, filename)}' to '{new_dir}'")
                        shutil.move(os.path.join(folder,filename), new_dir)

                if os.path.exists(folder):
                    logger.info(f"Completed transition, deleting forlder '{folder}'")
                    shutil.rmtree(folder)

            elif os.path.exists(folder):
                logger.info(f"Moving files from '{os.path.join(slskd_download_dir, folder)}' to '{os.path.join(slskd_download_dir, artist_name_sanitized)}'")
                shutil.move(folder, artist_name_sanitized)
            else:
                logger.warning(f"Folder '{os.path.join(slskd_download_dir, folder)}' does not exist, cannot move to '{artist_name_sanitized}'")

        if self.soularr_config.get_lidarr_disable_sync():
            return failed_searches

        artist_folders = next(os.walk('.'))[1]
        artist_folders = [folder for folder in artist_folders if folder != 'failed_imports']

        for artist_folder in artist_folders:
            download_dir = os.path.join(self.soularr_config.get_lidarr_download_dir(), artist_folder)
            logger.info(f"Starting Lidarr import for '{artist_folder}', setting import path to {download_dir}")
            command = self.post_lidarr_command(download_dir=download_dir)
            commands.append(command)
            logger.info(f"Lidarr import in progress for '{artist_folder}' ID: {command['id']}")

        while True:
            completed_count = 0
            for task in commands:
                current_task = self.get_lidarr_command(task['id'])
                if not current_task:
                    continue
                if current_task['status'] == 'completed' or current_task['status'] == 'failed':
                    completed_count += 1
            if completed_count == len(commands):
                break
            time.sleep(2)

        for task in commands:
            current_task = self.get_lidarr_command(task['id'])
            if not current_task:
                continue
            try:
                logger.info(f"{current_task['commandName']} {current_task['message']} from: {current_task['body']['path']}")

                if "Failed" in current_task['message']:
                    self.move_failed_import(current_task['body']['path'], search_denylist)
            except:
                logger.error("Error printing lidarr task message. Printing full unparsed message.")
                logger.error(current_task)

        if is_search_denylist_enabled:
            self.save_search_denylist(self.arg_parser.get_denylist_file_path(), search_denylist)

        return failed_searches

    def move_failed_import(self, src_path, denylist):
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
            logger.info(f"Failed import to Lidarr. Moved '{folder_name}' to '{target_path}'")


    def get_current_page(self, path: str, default_page=1) -> int:
        """
        Reads the current page number from a file. If the file does not exist or is empty,
        it creates the file with the default page number of 1 and returns that.

        Used for Lidarr Wanted page tracking in 'incrementing_page' search mode.
        """
        if os.path.exists(path):
            with open(path, 'r') as file:
                page_string = file.read().strip()

                if page_string:
                    return int(page_string)
                else:
                    with open(path, 'w') as file:
                        file.write(str(default_page))
                    return default_page
        else:
            with open(path, 'w') as file:
                file.write(str(default_page))
            return default_page


    def update_current_page(self, path: str, page: int) -> None:
        with open(path, 'w') as file:
                file.write(str(page))


    def get_records(self, missing: bool) -> list[Any]:
        """
        Retrieves records from Lidarr based on the specified search type and missing status.
        """
        page_size = self.soularr_config.get_page_size()
        current_page_file_path = self.arg_parser.get_current_page_file_path()
        lock_file_path = self.arg_parser.get_lock_file_path()
        try:
            wanted = self.lidarr.get_wanted(page_size=page_size, sort_dir='ascending',sort_key='albums.title', missing=missing)
        except ConnectionError as ex:
            logger.error(f"An error occurred when attempting to get records: {ex}")
            return []
        
        logger.debug(f"Records in 'Wanted': {wanted}")

        total_wanted = wanted['totalRecords']

        wanted_records = []
        search_type = self.soularr_config.get_search_type()
        if search_type == ALL:
            page = 1
            while len(wanted_records) < total_wanted:
                try:
                    wanted = self.lidarr.get_wanted(page=page, page_size=page_size, sort_dir='ascending',sort_key='albums.title', missing=missing)
                except ConnectionError as ex:
                    logger.error(f"Failed to grab record: {ex}")
                wanted_records.extend(wanted['records'])
                page += 1

        elif search_type == 'incrementing_page':
            page = self.get_current_page(current_page_file_path)
            try:
                wanted_records = self.lidarr.get_wanted(page=page, page_size=page_size, sort_dir='ascending',sort_key='albums.title', missing=missing)['records']
            except ConnectionError as ex:
                logger.error(f"Failed to grab record: {ex}")
            page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
            self.update_current_page(current_page_file_path, page)

        elif search_type == 'first_page':
            wanted_records = wanted['records']

        else:
            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)

            raise ValueError(f'[Search Settings] - {search_type = } is not valid')

        return wanted_records
    
    def get_queued_records(self) -> list[Any]:
        page_size = self.soularr_config.get_page_size()
        current_page_file_path = self.arg_parser.get_current_page_file_path()
        lock_file_path = self.arg_parser.get_lock_file_path()
        try:
            queued = self.lidarr.get_queue(page_size=page_size, sort_dir='ascending',sort_key='albums.title')
        except ConnectionError as ex:
            logger.error(f"An error occurred when attempting to get records: {ex}")
            return []
        
        logger.debug(f"Records in 'Queued': {queued}")

        total_queued = queued['totalRecords']

        queued_records = []
        search_type = self.soularr_config.get_search_type()
        if search_type == ALL:
            page = 1
            while len(queued_records) < total_queued:
                try:
                    queued = self.lidarr.get_queue(page=page, page_size=page_size, sort_dir='ascending', sort_key='albums.title')
                except ConnectionError as ex:
                    logger.error(f"Failed to queued grab record: {ex}")
                queued_records.extend(queued['records'])
                page += 1

        elif search_type == 'incrementing_page':
            page = self.get_current_page(current_page_file_path)
            try:
                queued_records = self.lidarr.get_queue(page=page, page_size=page_size, sort_dir='ascending', sort_key='albums.title')['records']
            except ConnectionError as ex:
                logger.error(f"Failed to grab queued record: {ex}")
            page = 1 if page >= math.ceil(total_queued / page_size) else page + 1
            self.update_current_page(current_page_file_path, page)

        elif search_type == 'first_page':
            queued_records = queued['records']

        else:
            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)

            raise ValueError(f'[Search Settings] - {search_type = } is not valid')

        return queued_records


    def load_search_denylist(self):
        file_path = self.arg_parser.get_denylist_file_path()
        if not os.path.exists(file_path):
            return {}

        try:
            with open(file_path, 'r') as file:
                return json.load(file)
        except (json.JSONDecodeError, IOError) as ex:
            logger.warning(f"Error loading search denylist: {ex}. Starting with empty denylist.")
            return {}


    def save_search_denylist(self, file_path, denylist):
        try:
            with open(file_path, 'w') as file:
                json.dump(denylist, file, indent=2)
        except IOError as ex:
            logger.error(f"Error saving search denylist: {ex}")


    def is_search_denylisted(self, denylist, album_id, max_failures):
        album_key = str(album_id)
        if album_key in denylist:
            return denylist[album_key]['failures'] >= max_failures
        return False


    def update_search_denylist(self, denylist: dict[str, Any], album_id: int, album_name: str, success: bool):
        album_key = str(album_id)
        current_datetime = datetime.now()
        current_datetime_str = current_datetime.strftime("%Y-%m-%dT%H:%M:%S")

        if success:
            if album_key in denylist:
                logger.info("Removing album from denylist: " + denylist[album_key]['album_id'])
                del denylist[album_key]
        else:
            logger.info("Adding album to denylist: " + album_key)
            if album_key in denylist:
                denylist[album_key]['failures'] += 1
                denylist[album_key]['last_attempt'] = current_datetime_str
            else:
                denylist[album_key] = {
                    'failures': 1,
                    'last_attempt': current_datetime_str,
                    'album_id': album_key,
                    'album_name': album_name,
                }

    def get_lidarr_album(self, album_id) -> Record:
        raw_albums = self.lidarr.get_album(album_id)
        if isinstance(raw_albums, list) and len(raw_albums) > 1:
            raw_album = raw_albums[0]
        else:
            raw_album: Any = raw_albums
        return map_raw_record_to_record(raw_album)
    
    def get_slskd_search_responses(self, search_id) -> list[SlskUserUploadInfo]:
        raw_responses = self.slskd.searches.search_responses(search_id)
        return [map_raw_user_upload_info_to_user_upload_info(response) for response in raw_responses]
    
    def get_slskd_transfer_downloads(self, username) -> dict[Any, Any] | None:
        """
        Get slskd downloads.

        Sample response:
        {
            "username": "lordskh",
            "directories": [
                {
                "directory": "Music\\My Chemical Romance\\2002 - I Brought You My Bullets, You Brought Me Your Love\\Disc 01",
                "fileCount": 11,
                "files": [
                    {
                    "id": "8ce133e7-5b46-419d-aeec-a9399e0c16f9",
                    "username": "lordskh",
                    "direction": "Download",
                    "filename": "Music\\My Chemical Romance\\2002 - I Brought You My Bullets, You Brought Me Your Love\\Disc 01\\01 - Romance.flac",
                    "size": 43522195,
                    "startOffset": 0,
                    "state": "Completed, Succeeded",
                    "stateDescription": "Completed, Succeeded",
                    "requestedAt": "2025-10-24T16:03:44.7924523",
                    "enqueuedAt": "2025-10-24T16:04:52.3134599",
                    "startedAt": "2025-10-24T16:04:52.5322361Z",
                    "endedAt": "2025-10-24T16:06:05.1723836Z",
                    "bytesTransferred": 43522195,
                    "averageSpeed": 599147.9436354393,
                    "bytesRemaining": 0,
                    "elapsedTime": "00:01:12.6401475",
                    "percentComplete": 100,
                    "remainingTime": "00:00:00"
                    },
                    ...
                ]
                }
            ]
        }
        """
        try:
            return self.slskd.transfers.get_downloads(username)
        except Exception as error:
            logger.info(f"Error getting downloads from user: \"{username}\": {error}")
            logger.info(traceback.format_exc())
            return None

    def get_lidarr_command(self, command_id: int) -> dict[Any, Any] | None:
        """
        Retrieves a Lidarr command by its ID.

        Sample response:
        {
            "name": "DownloadedAlbumsScan",
            "commandName": "Downloaded Albums Scan",
            "message": "Failed to import",
            "body": {
                "path": "/media/slskd/complete/Fading Lights (2023)",
                "importMode": "auto",
                "requiresDiskAccess": true,
                "isLongRunning": true,
                "sendUpdatesToClient": true,
                "updateScheduledTask": true,
                "isExclusive": false,
                "isTypeExclusive": false,
                "name": "DownloadedAlbumsScan",
                "trigger": "manual",
                "suppressMessages": true
            },
            "priority": "normal",
            "status": "completed",
            "result": "unsuccessful",
            "queued": "2025-10-24T15:34:03Z",
            "started": "2025-10-24T15:34:03Z",
            "ended": "2025-10-24T15:34:03Z",
            "duration": "00:00:00.0087083",
            "trigger": "manual",
            "stateChangeTime": "2025-10-24T15:34:03Z",
            "sendUpdatesToClient": true,
            "updateScheduledTask": true,
            "id": 608743
        }
        """
        try:
            return self.lidarr.get_command(command_id)
        except Exception as error:
            logger.info(f"Error getting lidarr command ID: \"{command_id}\": {error}")
            logger.info(traceback.format_exc())
            return None
        
    def post_lidarr_command(self, download_dir: str):
        """
        Post a command to Lidarr

        Sample response:
        {
            "name": "DownloadedAlbumsScan",
            "commandName": "Downloaded Albums Scan",
            "body": {
                "path": "/media/slskd/complete/My Chemical Romance",
                "importMode": "auto",
                "requiresDiskAccess": true,
                "isLongRunning": true,
                "sendUpdatesToClient": true,
                "updateScheduledTask": true,
                "isExclusive": false,
                "isTypeExclusive": false,
                "name": "DownloadedAlbumsScan",
                "trigger": "manual",
                "suppressMessages": true
            },
            "priority": "normal",
            "status": "queued",
            "result": "unknown",
            "queued": "2025-10-24T16:40:51Z",
            "trigger": "manual",
            "sendUpdatesToClient": true,
            "updateScheduledTask": true,
            "id": 608868
        }
        """
        return self.lidarr.post_command(name = 'DownloadedAlbumsScan', path = download_dir)