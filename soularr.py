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
import traceback
import configparser
import logging
import json
from datetime import datetime

import music_tag
import slskd_api
from pyarr import LidarrAPI


class EnvInterpolation(configparser.ExtendedInterpolation):
    """
    Interpolation which expands environment variables in values.
    Borrowed from https://stackoverflow.com/a/68068943
    """

    def before_read(self, parser, section, option, value):
        value = super().before_read(parser, section, option, value)
        return os.path.expandvars(value)

logger = logging.getLogger('soularr')
#Allows backwards compatibility for users updating an older version of Soularr
#without using the new [Logging] section in the config.ini file.
DEFAULT_LOGGING_CONF = {
    'level': 'INFO',
    'format': '[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s',
    'datefmt': '%Y-%m-%dT%H:%M:%S%z',
}

def album_match(lidarr_tracks, slskd_tracks, username, filetype):
    counted = []
    total_match = 0.0

    lidarr_album = lidarr.get_album(lidarr_tracks[0]['albumId'])
    lidarr_album_name = lidarr_album['title']
    lidarr_artist_name = lidarr_album['artist']['artistName']

    for lidarr_track in lidarr_tracks:
        lidarr_filename = lidarr_track['title'] + "." + filetype.split(" ")[0]
        best_match = 0.0

        for slskd_track in slskd_tracks:
            slskd_filename = slskd_track['filename']

            #Try to match the ratio with the exact filenames
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            #If ratio is a bad match try and split off (with " " as the separator) the garbage at the start of the slskd_filename and try again
            ratio = check_ratio(" ", ratio, lidarr_filename, slskd_filename)
            #Same but with "_" as the separator
            ratio = check_ratio("_", ratio, lidarr_filename, slskd_filename)

            #Same checks but preappend album name.
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
        logger.info(f"Average sequence match ratio: {total_match/len(counted)}")
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
    files = directory['files']
    allowed_filetypes_no_attributes = [item.split(" ")[0] for item in allowed_filetypes]
    count = 0
    index = -1
    filetype = ""
    for file in files:
        if file['filename'].split(".")[-1] in allowed_filetypes_no_attributes:
            new_index = allowed_filetypes_no_attributes.index(file['filename'].split(".")[-1])

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


def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:."/\\|?*]', '', folder_name)
    return valid_characters.strip()


def cancel_and_delete(delete_dir, username, files):
    for file in files:
        slskd.transfers.cancel_download(username = username, id = file['id'])

    os.chdir(slskd_download_dir)

    if os.path.exists(delete_dir):
        shutil.rmtree(delete_dir)


def release_trackcount_mode(releases):
    track_count = {}

    for release in releases:
        trackcount = release['trackCount']
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


def choose_release(album_id, artist_name):
    releases = lidarr.get_album(album_id)['releases']
    most_common_trackcount = release_trackcount_mode(releases)

    for release in releases:
        country = release['country'][0] if release['country'] else None

        if release['format'][1] == 'x' and allow_multi_disc:
            format_accepted = release['format'].split("x", 1)[1] in accepted_formats
        else:
            format_accepted = release['format'] in accepted_formats

        if use_most_common_tracknum:
            if release['trackCount'] == most_common_trackcount:
                track_count_bool = True
            else:
                track_count_bool = False
        else:
            track_count_bool = True

        if ((skip_region_check or country in accepted_countries)
            and format_accepted
            and release['status'] == "Official"
            and track_count_bool):

            logger.info(", ".join([
                f"Selected release for {artist_name}: {release['status']}",
                str(country),
                release['format'],
                f"Mediums: {release['mediumCount']}",
                f"Tracks: {release['trackCount']}",
                f"ID: {release['id']}",
            ]))

            return release

    if use_most_common_tracknum:
        for release in releases:
            if release['trackCount'] == most_common_trackcount:
                default_release = release
    else:
        default_release = releases[0]

    return default_release


def verify_filetype(file,allowed_filetype):
    current_filetype = file['filename'].split(".")[-1]
    bitdepth = None
    samplerate = None
    bitrate = None

    if 'bitRate' in file:
        bitrate = file['bitRate']
    if 'sampleRate' in file:
        samplerate = file['sampleRate']
    if 'bitDepth' in file:
        bitdepth = file['bitDepth']

    #Check if the types match up for the current files type and the current type from the config
    if current_filetype == allowed_filetype.split(" ")[0]:
        #Check if the current type from the config specifies other attributes than the filetype (bitrate etc)
        if " " in allowed_filetype:
            selected_attributes = allowed_filetype.split(" ")[1]
            #If it is a bitdepth/samplerate pair instead of a simple bitrate
            if "/" in selected_attributes:
                selected_bitdepth = selected_attributes.split("/")[0]
                try:
                    selected_samplerate = str(int(float(selected_attributes.split("/")[1]) * 1000))
                except (ValueError, IndexError):
                    logger.warning("Invalid samplerate in selected_attributes")
                    return False

                if bitdepth and samplerate:
                    if str(bitdepth) == str(selected_bitdepth)and str(samplerate) == str(selected_samplerate):
                        return True
                else:
                    return False
            #If it is a bitrate
            else:
                selected_bitrate = selected_attributes
                if bitrate:
                    if str(bitrate) == str(selected_bitrate):
                        return True
                else:
                    return False
        #If no bitrate or other info then it is a match so return true
        else:
            return True
    else:
        return False


def search_and_download(grab_list, query, tracks, track, artist_name, release):
    search = slskd.searches.search_text(searchText = query,
                                        searchTimeout = config.getint('Search Settings', 'search_timeout', fallback=5000),
                                        filterResponses = True,
                                        maximumPeerQueueLength = config.getint('Search Settings', 'maximum_peer_queue', fallback=50),
                                        minimumPeerUploadSpeed = config.getint('Search Settings', 'minimum_peer_upload_speed', fallback=0))

    track_num = len(tracks)
    #Add timeout here to increase reliability with Slskd. Sometimes it doesn't update search status fast enough. More of an issue with lots of historical searches in slskd
    time.sleep(5)

    while True:
        if slskd.searches.state(search['id'])['state'] != 'InProgress':
            break
        time.sleep(1)

    logger.info(f"Search returned {len(slskd.searches.search_responses(search['id']))} results")

    #Init directory cache. The wide search returns all the data we need. This prevents us from hammering the users on the Soulseek network 
    dir_cache = {}

    for result in slskd.searches.search_responses(search['id']):
        username = result['username']
        if username not in dir_cache:
            #If we don't currently have a cache for a user set one up
            dir_cache[username] = {}
        logger.info(f"Caching and truncating results for user: {username}")
        init_files = result['files'] #init_files short for initial files. Before truncating
        #Search the returned files and only cache files that are of the allowed_filetypes
        for file in init_files:
            file_dir = file['filename'].rsplit('\\',1)[0] #split dir/filenames on \
            for allowed_filetype in allowed_filetypes:
                if verify_filetype(file,allowed_filetype):  #Check the filename for an allowed type
                    if allowed_filetype not in dir_cache[username]:
                        dir_cache[username][allowed_filetype] = [] #Init the cache for this allowed filetype
                    if file_dir not in dir_cache[username][allowed_filetype]:
                        dir_cache[username][allowed_filetype].append(file_dir)

    for allowed_filetype in allowed_filetypes:
        logger.info(f"Searching for matches with selected attributes: {allowed_filetype}")

        for username in dir_cache:
            if not allowed_filetype in dir_cache[username]:
                continue
            logger.info(f"Parsing result from user: {username}")

            for file_dir in dir_cache[username][allowed_filetype]:


                try:
                    version = slskd.application.version()
                    version_check = slskd_version_check(version)
                except:
                    logger.info(f"Error checking slskd version number: {version}. Version check > 0.22.2: {version_check}. This would most likely be fixed by updating your slskd.")
                    continue
                    
                try:
                    if version_check:
                        directory = slskd.users.directory(username = username, directory = file_dir)[0]
                    else:
                        directory = slskd.users.directory(username = username, directory = file_dir)
                except Exception:
                    logger.info(f"Error getting directory from user: \"{username}\"\n{traceback.format_exc()}")
                    continue

                tracks_info = album_track_num(directory)

                if tracks_info['count'] == track_num and tracks_info['filetype'] != "":
                    if album_match(tracks, directory['files'], username, allowed_filetype):
                        for i in range(0,len(directory['files'])):
                            directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']

                        folder_data = {
                            "artist_name": artist_name,
                            "release": release,
                            "dir": file_dir.split("\\")[-1],
                            "discnumber": track['mediumNumber'],
                            "username": username,
                            "directory": directory,
                        }
                        grab_list.append(folder_data)

                        try:
                            slskd.transfers.enqueue(username = username, files = directory['files'])
                            # Delete the search from SLSKD DB
                            if delete_searches:
                                slskd.searches.delete(search['id'])
                            return True
                        except Exception:
                            logger.warning(f"Error enqueueing tracks! Adding {username} to ignored users list.")
                            downloads = slskd.transfers.get_downloads(username)

                            for cancel_directory in downloads["directories"]:
                                if cancel_directory["directory"] == directory["name"]:
                                    cancel_and_delete(file_dir.split("\\")[-1], username, cancel_directory["files"])
                                    grab_list.remove(folder_data)
                                    ignored_users.append(username)
                            continue

    # Delete the search from SLSKD DB
    if delete_searches:
        slskd.searches.delete(search['id'])
    return False


def is_blacklisted(title: str) -> bool:
    blacklist = config.get('Search Settings', 'title_blacklist', fallback='').lower().split(",")
    for word in blacklist:
        if word != '' and word in title.lower():
            logger.info(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False


def grab_most_wanted(albums):
    grab_list = []
    failed_searches = 0
    success = False
    search_denylist = {}

    if enable_search_denylist:
        search_denylist = load_search_denylist(denylist_file_path)

    for album in albums:
        artist_name = album['artist']['artistName']
        artist_id = album['artistId']
        album_id = album['id']

        if enable_search_denylist and is_search_denylisted(search_denylist, album_id, max_search_failures):
            logger.info(f"Skipping denylisted album: {artist_name} - {album['title']} (ID: {album_id})")
            continue

        release = choose_release(album_id, artist_name)

        release_id = release['id']
        all_tracks = lidarr.get_tracks(artistId = artist_id, albumId = album_id, albumReleaseId = release_id)

        #TODO: Right now if search_for_tracks is False. Multi disc albums will never be downloaded so we need to loop through media in releases even for albums
        if len(release['media']) == 1:
            album_title = lidarr.get_album(album_id)['title']
            if is_blacklisted(album_title):
                continue

            if len(album_title) == 1:
                query = artist_name + " " + album_title
            else:
                query = artist_name + " " + album_title if config.getboolean('Search Settings', 'album_prepend_artist', fallback=False) else album_title

            logger.info(f"Searching album: {query}")
            success = search_and_download(grab_list, query, all_tracks, all_tracks[0], artist_name, release)

        if not success and config.getboolean('Search Settings', 'search_for_tracks', fallback=True):
            for media in release['media']:
                tracks = []
                for track in all_tracks:
                    if track['mediumNumber'] == media['mediumNumber']:
                        tracks.append(track)

                for track in tracks:
                    if is_blacklisted(track['title']):
                        continue

                    if len(track['title']) == 1:
                        query = artist_name + " " + track['title']
                    else:
                        query = artist_name + " " + track['title'] if config.getboolean('Search Settings', 'track_prepend_artist', fallback=True) else track['title']

                    logger.info(f"Searching track: {query}")
                    success = search_and_download(grab_list, query, tracks, track, artist_name, release)

                    if success:
                        break

        if enable_search_denylist:
            update_search_denylist(search_denylist, album_id, success)

        if not success:
            if remove_wanted_on_failure:
                logger.error(f"Failed to find match for: {album['title']} from artist: {artist_name}."
                    + ' Album removed from wanted list and added to "failure_list.txt"')

                album['monitored'] = False
                lidarr.upd_album(album)

                current_datetime = datetime.now()
                current_datetime_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")

                failure_string = current_datetime_str + " - " + artist_name + ", " + album['title'] + ", " + str(album_id) + "\n"

                with open(failure_file_path, "a") as file:
                    file.write(failure_string)
            else:
                logger.error(f"Failed to find match for: {album['title']} from artist: {artist_name}")

            failed_searches += 1

        success = False

    logger.info("Downloads added:")
    downloads = slskd.transfers.get_all_downloads()

    for download in downloads:
        username = download['username']
        for dir in download['directories']:
            logger.info(f"Username: {username} Directory: {dir['directory']}")
    logger.info("-------------------")
    logger.info(f"Waiting for downloads... monitor at: {''.join([slskd_host_url, slskd_url_base, 'downloads'])}")

    time_count = 0

    while True:
        unfinished = 0
        for artist_folder in list(grab_list):
            username, dir = artist_folder['username'], artist_folder['directory']
            
            try:
                downloads = slskd.transfers.get_downloads(username)
            except Exception:
                logger.info(f"Error getting directory from user: \"{username}\"\n{traceback.format_exc()}")
                continue

            for directory in downloads["directories"]:
                if directory["directory"] == dir["name"]:
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
                        logger.error(f"FAILED: Username: {username} Directory: {dir['name']}")
                        cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                        grab_list.remove(artist_folder)
                    elif len(pending_files) > 0:
                        unfinished += 1

        if unfinished == 0:
            logger.info("All tracks finished downloading!")
            time.sleep(5)
            break

        time_count += 10

        if(time_count > stalled_timeout):
            logger.info("Stall timeout reached! Removing stuck downloads...")

            for directory in downloads["directories"]:
                if directory["directory"] == dir["name"]:
                    #TODO: This does not seem to account for directories where the whole dir is stuck as queued.
                    #Either it needs to account for those or maybe soularr should just force clear out the downloads screen when it exits.
                    pending_files = [file for file in directory["files"] if not 'Completed' in file["state"]]

                    if len(pending_files) > 0:
                        logger.error(f"Removing Stalled Download: Username: {username} Directory: {dir['name']}")
                        cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                        grab_list.remove(artist_folder)

            logger.info("All tracks finished downloading!")
            time.sleep(5)
            break

        time.sleep(10)

    os.chdir(slskd_download_dir)
    commands = []
    grab_list.sort(key=operator.itemgetter('artist_name'))

    for artist_folder in grab_list:
        artist_name = artist_folder['artist_name']
        artist_name_sanitized = sanitize_folder_name(artist_name)

        folder = artist_folder['dir']

        if artist_folder['release']['mediumCount'] > 1:
            for filename in os.listdir(folder):
                album_name = lidarr.get_album(albumIds = artist_folder['release']['albumId'])['title']

                if filename.split(".")[-1] in allowed_filetypes:
                    song = music_tag.load_file(os.path.join(folder,filename))
                    if song is not None:
                        song['artist'] = artist_name
                        song['albumartist'] = artist_name
                        song['album'] = album_name
                        song['discnumber'] = artist_folder['discnumber']
                        song.save()

                new_dir = os.path.join(artist_name_sanitized,sanitize_folder_name(album_name))

                if not os.path.exists(artist_name_sanitized):
                    os.mkdir(artist_name_sanitized)
                if not os.path.exists(new_dir):
                    os.mkdir(new_dir)

                if os.path.exists(os.path.join(folder,filename)) and not os.path.exists(os.path.join(new_dir,filename)):
                    shutil.move(os.path.join(folder,filename),new_dir)

            if os.path.exists(folder):
                shutil.rmtree(folder)

        elif os.path.exists(folder):
            shutil.move(folder,artist_name_sanitized)

    if lidarr_disable_sync:
        return failed_searches

    artist_folders = next(os.walk('.'))[1]
    artist_folders = [folder for folder in artist_folders if folder != 'failed_imports']

    for artist_folder in artist_folders:
        download_dir = os.path.join(lidarr_download_dir,artist_folder)
        command = lidarr.post_command(name = 'DownloadedAlbumsScan', path = download_dir)
        commands.append(command)
        logger.info(f"Starting Lidarr import for: {artist_folder} ID: {command['id']}")

    while True:
        completed_count = 0
        for task in commands:
            current_task = lidarr.get_command(task['id'])
            if current_task['status'] == 'completed' or current_task['status'] == 'failed':
                completed_count += 1
        if completed_count == len(commands):
            break
        time.sleep(2)

    for task in commands:
        current_task = lidarr.get_command(task['id'])
        try:
            logger.info(f"{current_task['commandName']} {current_task['message']} from: {current_task['body']['path']}")

            if "Failed" in current_task['message']:
                move_failed_import(current_task['body']['path'])
        except:
            logger.error("Error printing lidarr task message. Printing full unparsed message.")
            logger.error(current_task)

    if enable_search_denylist:
        save_search_denylist(denylist_file_path, search_denylist)

    return failed_searches


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
    return os.getenv('IN_DOCKER') is not None

def slskd_version_check(version, target="0.22.2"):
    version_tuple = tuple(map(int, version.split('.')[:3]))
    target_tuple = tuple(map(int, target.split('.')[:3]))
    return version_tuple > target_tuple

def setup_logging(config):
    if 'Logging' in config:
        log_config = config['Logging']
    else:
        log_config = DEFAULT_LOGGING_CONF
    logging.basicConfig(**log_config)   # type: ignore


def get_current_page(path: str, default_page=1) -> int:
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


def update_current_page(path: str, page: int) -> None:
    with open(path, 'w') as file:
            file.write(page)


def get_records(missing: bool) -> list:
    try:
        wanted = lidarr.get_wanted(page_size=page_size, sort_dir='ascending',sort_key='albums.title', missing=missing)
    except ConnectionError as ex:
        logger.error(f"An error occurred when attempting to get records: {ex}")
        return []

    total_wanted = wanted['totalRecords']

    wanted_records = []
    if search_type == 'all':
        page = 1
        while len(wanted_records) < total_wanted:
            try:
                wanted = lidarr.get_wanted(page=page, page_size=page_size, sort_dir='ascending',sort_key='albums.title', missing=missing)
            except ConnectionError as ex:
                logger.error(f"Failed to grab record: {ex}")
            wanted_records.extend(wanted['records'])
            page += 1

    elif search_type == 'incrementing_page':
        page = get_current_page(current_page_file_path)
        try:
            wanted_records = lidarr.get_wanted(page=page, page_size=page_size, sort_dir='ascending',sort_key='albums.title', missing=missing)['records']
        except ConnectionError as ex:
            logger.error(f"Failed to grab record: {ex}")
        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, str(page))

    elif search_type == 'first_page':
        wanted_records = wanted['records']

    else:
        if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)

        raise ValueError(f'[Search Settings] - {search_type = } is not valid')

    return wanted_records


def load_search_denylist(file_path):
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except (json.JSONDecodeError, IOError) as ex:
        logger.warning(f"Error loading search denylist: {ex}. Starting with empty denylist.")
        return {}


def save_search_denylist(file_path, denylist):
    try:
        with open(file_path, 'w') as file:
            json.dump(denylist, file, indent=2)
    except IOError as ex:
        logger.error(f"Error saving search denylist: {ex}")


def is_search_denylisted(denylist, album_id, max_failures):
    album_key = str(album_id)
    if album_key in denylist:
        return denylist[album_key]['failures'] >= max_failures
    return False


def update_search_denylist(denylist, album_id, success):
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
                'album_id': album_id
            }


# Let's allow some overrides to be passed to the script
parser = argparse.ArgumentParser(
    description="""Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd"""
)

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
            logger.error('Config file does not exist! Please mount "/data" and place your "config.ini" file there. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.')
            logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
        else:
            logger.error("Config file does not exist! Please place it in the working directory. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.")
            logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        sys.exit(0)

    slskd_api_key = config['Slskd']['api_key']
    lidarr_api_key = config['Lidarr']['api_key']

    lidarr_download_dir = config['Lidarr']['download_dir']
    lidarr_disable_sync = config.getboolean('Lidarr', 'disable_sync', fallback=False)

    slskd_download_dir = config['Slskd']['download_dir']

    lidarr_host_url = config['Lidarr']['host_url']
    slskd_host_url = config['Slskd']['host_url']

    stalled_timeout = config.getint('Slskd', 'stalled_timeout', fallback=3600)

    delete_searches = config.getboolean('Slskd', 'delete_searches', fallback=True)

    slskd_url_base = config.get('Slskd', 'url_base', fallback='/')

    ignored_users = config.get('Search Settings', 'ignored_users', fallback='').split(",")
    search_type = config.get('Search Settings', 'search_type', fallback='first_page').lower().strip()
    search_source = config.get('Search Settings', 'search_source', fallback='missing').lower().strip()

    search_sources = [search_source]
    if search_sources[0] == 'all':
        search_sources = ['missing', 'cutoff_unmet']

    minimum_match_ratio = config.getfloat('Search Settings', 'minimum_filename_match_ratio', fallback=0.5)
    page_size = config.getint('Search Settings', 'number_of_albums_to_grab', fallback=10)
    remove_wanted_on_failure = config.getboolean('Search Settings', 'remove_wanted_on_failure', fallback=True)
    enable_search_denylist = config.getboolean('Search Settings', 'enable_search_denylist', fallback=False)
    max_search_failures = config.getint('Search Settings', 'max_search_failures', fallback=3)

    use_most_common_tracknum = config.getboolean('Release Settings', 'use_most_common_tracknum', fallback=True)
    allow_multi_disc = config.getboolean('Release Settings', 'allow_multi_disc', fallback=True)

    default_accepted_countries = "Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada"
    default_accepted_formats = "CD,Digital Media,Vinyl"
    accepted_countries = config.get('Release Settings', 'accepted_countries', fallback=default_accepted_countries).split(",")
    skip_region_check = config.getboolean('Release Settings', 'skip_region_check', fallback=False)
    accepted_formats = config.get('Release Settings', 'accepted_formats', fallback=default_accepted_formats).split(",")

    raw_filetypes = config.get('Search Settings', 'allowed_filetypes', fallback='flac,mp3')

    if "," in raw_filetypes:
        allowed_filetypes = raw_filetypes.split(",")
    else:
        allowed_filetypes = [raw_filetypes]

    setup_logging(config)

    slskd = slskd_api.SlskdClient(host=slskd_host_url, api_key=slskd_api_key, url_base=slskd_url_base)
    lidarr = LidarrAPI(lidarr_host_url, lidarr_api_key)
    wanted_records = []
    try:
        for source in search_sources:
            logging.debug(f'Getting records from {source}')
            missing = source == 'missing'
            wanted_records.extend(get_records(missing))
    except ValueError as ex:
        logger.error(f'An error occurred: {ex}')
        logger.error('Exiting...')
        sys.exit(0)

    if len(wanted_records) > 0:
        try:
            failed = grab_most_wanted(wanted_records)
        except Exception:
            logger.error(traceback.format_exc())
            logger.error("\n Fatal error! Exiting...")

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
