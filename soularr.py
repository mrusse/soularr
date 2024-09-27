import re
import os
import time
import shutil
import difflib
import operator
import traceback
import configparser

import music_tag
import slskd_api
from pyarr import LidarrAPI

def album_match(lidarr_tracks, slskd_tracks, username):
    counted = []
    mp3 = False
    total_match = 0.0

    for lidarr_track in lidarr_tracks:
        lidarr_filename = lidarr_track['title'] + ".flac"
        best_match = 0.0

        for slskd_track in slskd_tracks:
            slskd_filename = slskd_track['filename']
            if(".mp3" in slskd_filename):
                mp3 = True
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            if ratio > best_match:
                best_match = ratio

        if best_match > 0.5:
            counted.append(lidarr_filename)
            total_match += best_match

    if(len(counted) == len(lidarr_tracks) and not mp3 and username not in ignored_users):
        print("\nFound match from user: " + username +" for " + str(len(counted)) + " tracks!")
        print("Average sequence match ratio: " + str(total_match/len(counted)))
        print("SUCCESSFUL MATCH \n-------------------")
        return True
    
    return False

def album_track_num(directory):
    files = directory['files']
    count = 0
    for file in files:
        if(".flac" in file['filename']):
            count += 1
    return count

def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:"/\\|?*]', '', folder_name)
    return valid_characters.strip()

def cancel_and_delete(delete_dir, directory):
    for bad_file in directory['files']:
        downloads = slskd.transfers.get_all_downloads()

        for user in downloads:
            for dir in user['directories']:
                for file in dir['files']:
                    if bad_file['filename'] == file['filename']:
                        slskd.transfers.cancel_download(username = user['username'], id = file['id'])
                        time.sleep(.2)

    os.chdir(slskd_download_dir)
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

        if(release['format'][1] == 'x' and allow_multi_disc):
            format_accepted = release['format'].split("x", 1)[1]
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
                  + ", Mediums: " + str(release['mediumCount']))
            
            return release
    
    for release in releases:
        if release['trackCount'] == most_common_trackcount:
            default_release = release

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
            if('.flac' in file['filename']):
                file_dir = file['filename'].rsplit("\\",1)[0]

                try:
                    directory = slskd.users.directory(username = username, directory = file_dir)
                except:
                    continue

                if album_track_num(directory) == track_num:
                    if album_match(tracks, directory['files'], username):
                        for i in range(0,len(directory['files'])):
                            directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']

                        folder_data =	{
                            "artist_name": artist_name,
                            "release": release,
                            "dir": file_dir.split("\\")[-1],
                            "discnumber": track['mediumNumber'] 
                        }
                        grab_list.append(folder_data)

                        try:
                            slskd.transfers.enqueue(username = username, files = directory['files'])
                            return True
                        except Exception:
                            ignored_users.append(username)
                            grab_list.remove(folder_data)
                            print("Error enqueueing tracks! Adding " + username + " to ignored users list.")
                            #print(traceback.format_exc())
                            continue
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

        if(len(release['media']) == 1):
            album_title = lidarr.get_album(album_id)['title']
            querry = album_title
            print("Searching album: " + querry)
            success = search_and_download(grab_list, querry, all_tracks, all_tracks[0], artist_name, release)

        if not success:
            for media in release['media']:
                tracks = []
                for track in all_tracks:
                    if track['mediumNumber'] == media['mediumNumber']:
                        tracks.append(track)

                for track in tracks:
                    querry = artist_name + " " + track['title']
                    print("Searching track: " + querry)
                    success = search_and_download(grab_list, querry, tracks, track, artist_name, release)

                    if success:
                        break

                if not success:
                    print("ERROR: Failed to grab albumID: " + str(album_id) + " for artist: " + artist_name)
                    failed_download += 1
            
    print("Downloads added: ")
    downloads = slskd.transfers.get_all_downloads()

    for download in downloads:
        username = download['username']
        for dir in download['directories']:
            print("Username: " + username + " Directory: " + dir['directory'])

    print("-------------------")
    print("Waiting for downloads... monitor at: " + slskd_host_url + "/downloads")

    while True:
        downloads = slskd.transfers.get_all_downloads()
        unfinished = 0
        for user in downloads:
            for directory in user['directories']:
                for file in directory['files']:
                    if not 'Completed' in file['state']:
                        unfinished += 1

        if(unfinished == 0):
            print("All tracks finished downloading!")
            time.sleep(5)
            break
    
    os.chdir(slskd_download_dir)
    commands = []
    grab_list.sort(key=operator.itemgetter('artist_name'))

    for artist_folder in grab_list:
        artist_name = artist_folder['artist_name']
        folder = artist_folder['dir']

        if artist_folder['release']['mediumCount'] > 1:
            for filename in os.listdir(folder):
                album_name = lidarr.get_album(albumIds = artist_folder['release']['albumId'])['title']

                if(".flac" in filename):
                    song = music_tag.load_file(os.path.join(folder,filename))
                    song['album'] = album_name
                    song['discnumber'] = artist_folder['discnumber']
                    song.save()

                if not os.path.exists(artist_name):
                    new_dir = os.path.join(artist_name,sanitize_folder_name(album_name))
                    os.mkdir(artist_name)
                    os.mkdir(new_dir)

                shutil.move(os.path.join(folder,filename),new_dir)
            shutil.rmtree(folder)

        else:
            shutil.move(folder,artist_name)

    artist_folders = next(os.walk('.'))[1]

    for artist_folder in artist_folders:
        command = lidarr.post_command(name = 'DownloadedAlbumsScan', path = '/data/' + artist_folder)
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
        except:
            print("Error printing lidarr task message. Printing full task.")
            print(current_task)
            
    return failed_download

#------------------------------------------#
config = configparser.ConfigParser()
config.read('config.ini')

slskd_api_key = config['Slskd']['api_key']
lidarr_api_key = config['Lidarr']['api_key']

slskd_download_dir = config['Slskd']['download_dir']

lidarr_host_url = config['Lidarr']['host_url']
slskd_host_url = config['Slskd']['host_url']

search_settings = config['Search Settings']

release_settings = config['Release Settings']
use_most_common_tracknum = release_settings.getboolean('use_most_common_tracknum')
allow_multi_disc = release_settings.getboolean('allow_multi_disc')

accepted_countries = release_settings['accepted_countries'].split(",")
accepted_formats = release_settings['accepted_formats'].split(",")

slskd = slskd_api.SlskdClient(slskd_host_url, slskd_api_key, '/')
lidarr = LidarrAPI(lidarr_host_url, lidarr_api_key)

ignored_users = []

for i in range(0,5):
    wanted = lidarr.get_wanted(sort_dir='ascending',sort_key='albums.title')['records']
    if len(wanted) > 0:
        try:
            failed = grab_most_wanted(wanted)
        except Exception: 
            print(traceback.format_exc())
            print("\n Fatal error! Deleting all partial downloads and restarting.")

            downloads = slskd.transfers.get_all_downloads()

            for user in downloads:
                for dir in user['directories']:
                    for file in dir['files']:
                        slskd.transfers.cancel_download(username = user['username'], id = file['id'], remove= True)
                        time.sleep(.2)
            
            for item in os.listdir(slskd_download_dir):
                item_path = os.path.join(slskd_download_dir, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            
            continue
        if failed == 0:
            print("Solarr finished. Exiting...")
            break
        else:
            print(str(failed) + ": releases failed while downloading. Retying in 10 seconds...")
    else:
        print("No releases wanted. Exiting...")
        break
    
    time.sleep(10)