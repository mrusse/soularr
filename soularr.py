#!/usr/bin/env python

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
from datetime import datetime

import music_tag
import slskd_api
from pyarr import LidarrAPI

def album_match(lidarr_tracks, slskd_tracks, username, filetype):
    counted = []
    mp3 = False
    total_match = 0.0

    for lidarr_track in lidarr_tracks:
        lidarr_filename = lidarr_track['title'] + filetype
        best_match = 0.0

        for slskd_track in slskd_tracks:
            slskd_filename = slskd_track['filename']
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            #If ratio is a bad match try and split off the garbage at the start of the slskd_filename and try again
            if ratio < 0.5:
                lidarr_filename_word_count = len(lidarr_filename.split()) * -1
                truncated_slskd_filename = " ".join(slskd_filename.split()[lidarr_filename_word_count:])
                ratio = difflib.SequenceMatcher(None, lidarr_filename, truncated_slskd_filename).ratio()

            if ratio > best_match:
                best_match = ratio

        if best_match > 0.5:
            counted.append(lidarr_filename)
            total_match += best_match

    if len(counted) == len(lidarr_tracks) and not mp3 and username not in ignored_users:
        print("\nFound match from user: " + username +" for " + str(len(counted)) + " tracks!")
        print("Average sequence match ratio: " + str(total_match/len(counted)))
        print("SUCCESSFUL MATCH \n-------------------")
        return True

    return False

def album_track_num(directory):
    files = directory['files']
    count = 0
    index = -1
    filetype = ""
    for file in files:
        if file['filename'].split(".")[-1] in allowed_filetypes:
            new_index = allowed_filetypes.index(file['filename'].split(".")[-1])

            if index == -1:
                index = new_index
                filetype = allowed_filetypes[index]
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

        if (country in accepted_countries
            and format_accepted
            and release['status'] == "Official"
            and track_count_bool):

            print("Selected release for "
                  + artist_name + ": "
                  + release['status'] + ", "
                  + country + ", "
                  + release['format']
                  + ", Mediums: " + str(release['mediumCount'])
                  + ", Tracks: " + str(release['trackCount'])
                  + ", ID: " + str(release['id']))

            return release

    if use_most_common_tracknum:
        for release in releases:
            if release['trackCount'] == most_common_trackcount:
                default_release = release
    else:
        default_release = releases[0]

    return default_release

def search_and_download(grab_list, querry, tracks, track, artist_name, release):
    search = slskd.searches.search_text(searchText = querry,
                                        searchTimeout = search_settings['search_timeout'],
                                        filterResponses = True,
                                        maximumPeerQueueLength = search_settings['maximum_peer_queue'],
                                        minimumPeerUploadSpeed = search_settings['minimum_peer_upload_speed'])

    track_num = len(tracks)

    while True:
        if slskd.searches.state(search['id'])['state'] != 'InProgress':
            break
        time.sleep(1)

    print("Search returned " + str(len(slskd.searches.search_responses(search['id']))) + " results")

    for result in slskd.searches.search_responses(search['id']):
        username = result['username']
        print("Parsing result from user: " + username)
        files = result['files']

        for file in files:
            if file['filename'].split(".")[-1] in allowed_filetypes:
                file_dir = file['filename'].rsplit("\\",1)[0]

                try:
                    directory = slskd.users.directory(username = username, directory = file_dir)
                except:
                    continue

                tracks_info = album_track_num(directory)

                if tracks_info['count'] == track_num and tracks_info['filetype'] != "":
                    if album_match(tracks, directory['files'], username, tracks_info['filetype']):
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
                            slskd.searches.delete(search['id'])
                            return True
                        except Exception:
                            ignored_users.append(username)
                            grab_list.remove(folder_data)
                            print("Error enqueueing tracks! Adding " + username + " to ignored users list.")
                            #print(traceback.format_exc())
                            continue

    # Delete the search from SLSKD DB
    slskd.searches.delete(search['id'])
    return False

def is_blacklisted(title: str) -> bool:
    blacklist = search_settings.get('title_blacklist', '').lower().split(",")
    for word in blacklist:
        if word != '' and word in title.lower():
            print(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False

def grab_most_wanted(albums):
    grab_list = []
    failed_download = 0
    success = False

    for album in albums:
        artist_name = album['artist']['artistName']
        artist_id = album['artistId']
        album_id = album['id']

        release = choose_release(album_id, artist_name)

        release_id = release['id']
        all_tracks = lidarr.get_tracks(artistId = artist_id, albumId = album_id, albumReleaseId = release_id)

        #TODO: Right now if search_for_tracks is False. Multi disc albums will never be downloaded so we need to loop through media in releases even for albums
        if len(release['media']) == 1:
            album_title = lidarr.get_album(album_id)['title']
            if is_blacklisted(album_title):
                continue

            if len(album_title) == 1:
                querry = artist_name + " " + album_title
            else:
                querry = artist_name + " " + album_title if search_settings.getboolean('album_prepend_artist', False) else album_title

            print("Searching album: " + querry)
            success = search_and_download(grab_list, querry, all_tracks, all_tracks[0], artist_name, release)

        if not success and search_settings.getboolean('search_for_tracks', True):
            for media in release['media']:
                tracks = []
                for track in all_tracks:
                    if track['mediumNumber'] == media['mediumNumber']:
                        tracks.append(track)

                for track in tracks:
                    if is_blacklisted(track['title']):
                        continue

                    if len(track['title']) == 1:
                        querry = artist_name + " " + track['title']
                    else:
                        querry = artist_name + " " + track['title'] if search_settings.getboolean('track_prepend_artist', True) else track['title']
                        
                    print("Searching track: " + querry)
                    success = search_and_download(grab_list, querry, tracks, track, artist_name, release)

                    if success:
                        break

                if not success:
                    if remove_wanted_on_failure:
                        print("ERROR: Failed to grab album: " + album['title'] + " for artist: " + artist_name + 
                              ". Failed album removed from wanted list and added to \"failure_list.txt\"")

                        album['monitored'] = False
                        lidarr.upd_album(album)
                        
                        current_datetime = datetime.now()
                        current_datetime_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")

                        failure_string = current_datetime_str + " - " + artist_name + ", " + album['title'] + ", " + str(album_id) + "\n"

                        with open(failure_file_path, "a") as file:
                            file.write(failure_string)
                    else:
                        print("ERROR: Failed to grab album: " + album['title'] + " for artist: " + artist_name)
                    
                    failed_download += 1

        success = False

    print("Downloads added: ")
    downloads = slskd.transfers.get_all_downloads()

    for download in downloads:
        username = download['username']
        for dir in download['directories']:
            print("Username: " + username + " Directory: " + dir['directory'])

    print("-------------------")
    print("Waiting for downloads... monitor at: " + slskd_host_url + "/downloads")

    while True:
        unfinished = 0
        for artist_folder in list(grab_list):
            username, dir = artist_folder['username'], artist_folder['directory']
            downloads = slskd.transfers.get_downloads(username)

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
                        print(f"FAILED: Username: {username} Directory: {dir['name']}")
                        cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                        grab_list.remove(artist_folder)
                    elif len(pending_files) > 0:
                        unfinished += 1

        if unfinished == 0:
            print("All tracks finished downloading!")
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

                if os.path.exists(os.path.join(folder,filename)):
                    shutil.move(os.path.join(folder,filename),new_dir)

            if os.path.exists(folder):        
                shutil.rmtree(folder)

        elif os.path.exists(folder):
            shutil.move(folder,artist_name_sanitized)

    artist_folders = next(os.walk('.'))[1]
    artist_folders = [folder for folder in artist_folders if folder != 'failed_imports']

    for artist_folder in artist_folders:
        download_dir = os.path.join(lidarr_download_dir,artist_folder)
        command = lidarr.post_command(name = 'DownloadedAlbumsScan', path = download_dir)
        commands.append(command)
        print("Starting Lidarr import for: " + artist_folder + " ID: " + str(command['id']))

    while True:
        completed_count = 0
        for task in commands:
            current_task = lidarr.get_command(task['id'])
            if current_task['status'] == 'completed':
                completed_count += 1
        if completed_count == len(commands):
            break

    for task in commands:
        current_task = lidarr.get_command(task['id'])
        try:
            print(current_task['commandName'] + " " + current_task['message'] + " from: " + current_task['body']['path'])

            if "Failed" in current_task['message']:
                move_failed_import(current_task['body']['path'])
        except:
            print("Error printing lidarr task message. Printing full unparsed message.")
            print(current_task)

    return failed_download

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
    
    shutil.move(folder_name, target_path)
    print("Failed import moved to: " + target_path)

def is_docker():
    return os.getenv('IN_DOCKER') is not None

if is_docker():
    lock_file_path = ""
    config_file_path = os.path.join(os.getcwd(), "/data/config.ini")
    failure_file_path = os.path.join(os.getcwd(), "/data/failure_list.txt")
    current_page_file_path = os.path.join(os.getcwd(), "/data/.current_page.txt")
else:
    lock_file_path = os.path.join(os.getcwd(), ".soularr.lock")
    config_file_path = os.path.join(os.getcwd(), "config.ini")
    failure_file_path = os.path.join(os.getcwd(), "failure_list.txt")
    current_page_file_path = os.path.join(os.getcwd(), ".current_page.txt")
    
if os.path.exists(lock_file_path) and not is_docker():
    print(f"Soularr instance is already running.")
    sys.exit(1)

try:
    if not is_docker():
        with open(lock_file_path, "w") as lock_file:
            lock_file.write("locked")

    config = configparser.ConfigParser()


    if os.path.exists(config_file_path):
        config.read(config_file_path)
    else:
        if is_docker():
            print("Config file does not exist! Please mount \"/data\" and place your \"config.ini\" file there.")
            print("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
        else:
            print("Config file does not exist! Please place it in the working directory.")
            print("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        sys.exit(0)
 
    slskd_api_key = config['Slskd']['api_key']
    lidarr_api_key = config['Lidarr']['api_key']

    lidarr_download_dir = config['Lidarr']['download_dir']

    slskd_download_dir = config['Slskd']['download_dir']

    lidarr_host_url = config['Lidarr']['host_url']
    slskd_host_url = config['Slskd']['host_url']

    search_settings = config['Search Settings']
    ignored_users = search_settings['ignored_users'].split(",")
    search_type = search_settings.get('search_type', 'first_page').lower().strip()
    page_size = search_settings.getint('number_of_albums_to_grab', 10)
    remove_wanted_on_failure = search_settings.getboolean('remove_wanted_on_failure', True)

    release_settings = config['Release Settings']
    use_most_common_tracknum = release_settings.getboolean('use_most_common_tracknum')
    allow_multi_disc = release_settings.getboolean('allow_multi_disc')

    accepted_countries = release_settings['accepted_countries'].split(",")
    accepted_formats = release_settings['accepted_formats'].split(",")

    raw_filetypes = search_settings['allowed_filetypes']

    if "," in raw_filetypes:
        allowed_filetypes = raw_filetypes.split(",")
    else:
        allowed_filetypes = [raw_filetypes]

    slskd = slskd_api.SlskdClient(slskd_host_url, slskd_api_key, '/')
    lidarr = LidarrAPI(lidarr_host_url, lidarr_api_key)

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

    wanted = lidarr.get_wanted(page_size=page_size, sort_dir='ascending',sort_key='albums.title')
    total_wanted = wanted['totalRecords']

    if search_type == 'all':
        page = 1
        wanted_records = []

        while len(wanted_records) < total_wanted:
            wanted = lidarr.get_wanted(page=page, page_size=page_size, sort_dir='ascending',sort_key='albums.title')
            wanted_records.extend(wanted['records'])
            page += 1

    elif search_type == 'incrementing_page':
        page = get_current_page(current_page_file_path)
        wanted_records = lidarr.get_wanted(page=page, page_size=page_size, sort_dir='ascending',sort_key='albums.title')['records']
        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, str(page))

    elif search_type == 'first_page':
        wanted_records = wanted['records']

    else:
        print(f'Error: [Search Settings] - search_type = {search_type} is not valid. Exiting...')

        if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)

        sys.exit(0)

    if len(wanted_records) > 0:
        try:
            failed = grab_most_wanted(wanted_records)
        except Exception:
            print(traceback.format_exc())
            print("\n Fatal error! Exiting...")

            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)
            sys.exit(0)
        if failed == 0:
            print("Solarr finished. Exiting...")
            slskd.transfers.remove_completed_downloads()
        else:
            if remove_wanted_on_failure:
                print(str(failed) + ": releases failed and were removed from wanted list. View \"failure_list.txt\" for list of failed albums.")
            else:
                print(str(failed) + ": releases failed while downloading and are still wanted.")
            slskd.transfers.remove_completed_downloads()
    else:
        print("No releases wanted. Exiting...")

finally:
    # Remove the lock file after activity is done
    if os.path.exists(lock_file_path) and not is_docker():
        os.remove(lock_file_path)
