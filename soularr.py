import difflib
import time
import os
import shutil
import sys
from pyarr import LidarrAPI
import slskd_api

def album_match(lidarr_tracks, slskd_tracks):
    counted = []

    #TODO: This loop should find the max ratio match not just the first one that is > .499
    for lidarr_track in lidarr_tracks:
        lidarr_filename = lidarr_track['title'] + ".flac"

        for slskd_track in slskd_tracks:
            slskd_filename = slskd_track['filename']
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            if(difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio() > 0.499 and not lidarr_filename in counted):
                counted.append(lidarr_filename)
                print("Lidarr Filename: " + lidarr_filename + "\nSoulseek Filename: " + slskd_filename + "\nDiff Ratio: " + str(ratio) + "\n-------------------")
                break

    print("\nNum Matched: " + str(len(counted)) + " vs Total Num: " + str(len(lidarr_tracks)))

    if(len(counted) == len(lidarr_tracks)):
        print("SUCCESSFUL MATCH \n-------------------\n")
        return True
    print("FAILED MATCH \n-------------------\n")
    return False

def album_track_num(directory):
    files = directory['files']
    count = 0
    for file in files:
        if(".flac" in file['filename']):
            count += 1
    return count

def move_folders(folder, target_folder):
    os.makedirs(target_folder, exist_ok=True)

    for item in os.listdir(folder):
        source_path = os.path.join(folder, item)
        target_path = os.path.join(target_folder, item)

        if not os.path.isdir(source_path):
            shutil.copy2(source_path, target_path)

    #shutil.rmtree(folder)

def grab_most_wanted(albums):
    grab_list = []

    for album in albums:
        artistName = album['artist']['artistName']
        artistID = album['artistId']
        albumID = album['id']

        tracks = lidarr.get_tracks(artistId = artistID, albumId = albumID)
        track_num = len(tracks)

        for track in tracks:
            querry = artistName + " " + track['title']
            search = slskd.searches.search_text(searchText = querry, searchTimeout = 5000, filterResponses=True)

            while(True):
                if slskd.searches.state(search['id'])['state'] != 'InProgress':
                    break

            for result in slskd.searches.search_responses(search['id']):
                username = result['username']
                files = result['files']

                for file in files:
                    if('.flac' in file['filename']):
                        file_dir = file['filename'].rsplit("\\",1)[0]

                        try:
                            directory = slskd.users.directory(username = username, directory = file_dir)
                        except:
                            continue

                        if(album_track_num(directory) == track_num):
                            if(album_match(tracks, directory['files'])):
                                for i in range(0,len(directory['files'])):
                                    directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']
                                grab_list.append(file_dir.split("\\")[-1] + "|" + artistName)

                                try:
                                    slskd.transfers.enqueue(username=username, files=directory['files'])
                                except:
                                    for bad_file in directory['files']:
                                        slskd.transfers.cancel_download(username = username, id = bad_file['id'], remove = True)
                                        os.chdir(slskd_download_dir)
                                        shutil.rmtree(file_dir.split("\\")[-1])
                                    continue
                                
                                break
                else:
                    continue
                break
            else:
                continue
            break

    while(True):
        downloads = slskd.transfers.get_all_downloads()
        unfinished = 0
        for user in downloads:
            for dir in user['directories']:
                for file in dir['files']:
                    if file['state'] != 'Completed, Succeeded':
                        unfinished += 1
                    if file['state'] == 'Completed, Errored':
                        username = file['username']
                        slskd.transfers.enqueue(username=username, files=[file])

        if(unfinished == 0):
            print("FINISHED DOWNLOADING")
            time.sleep(10)
            break
    
    os.chdir(slskd_download_dir)
    for artist_folder in grab_list:
        artistName = artist_folder.split("|")[1]
        folder = artist_folder.split("|")[0]

        shutil.move(folder,artistName)
        time.sleep(10)
        print("LIDARR IMPORT")
        lidarr.post_command(name = 'DownloadedAlbumsScan', path = '/data/' + artistName)
        time.sleep(10)

with open('slskd.auth', 'r') as file:
    slskd_api_key = file.read().replace('\n', '')

with open('lidarr.auth', 'r') as file:
    lidarr_api_key = file.read().replace('\n', '')

slskd_download_dir = sys.argv[1]

host_url = 'http://192.168.2.190:8686'
slskd = slskd_api.SlskdClient('http://192.168.2.190:5030', slskd_api_key, '/')
lidarr = LidarrAPI(host_url, lidarr_api_key)

wanted = lidarr.get_wanted(sort_dir='ascending',sort_key='albums.title')['records']
if(len(wanted) > 0):
    grab_most_wanted(wanted)