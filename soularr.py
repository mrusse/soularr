import difflib
import os
from pyarr import LidarrAPI
import slskd_api

def album_match(lidarr_tracks, slskd_tracks):
    counted = []

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

with open('slskd.auth', 'r') as file:
    slskd_api_key = file.read().replace('\n', '')

with open('lidarr.auth', 'r') as file:
    lidarr_api_key = file.read().replace('\n', '')

host_url = 'http://192.168.2.190:8686'
slskd = slskd_api.SlskdClient('http://192.168.2.190:5030', slskd_api_key, '/')
lidarr = LidarrAPI(host_url, lidarr_api_key)


artistName = lidarr.get_wanted()['records'][0]['artist']['artistName']
artistID = lidarr.get_wanted()['records'][0]['artistId']
albumID = lidarr.get_wanted()['records'][0]['id']

tracks = lidarr.get_tracks(artistId = artistID, albumId = albumID)
track_num = len(tracks)

for track in tracks:
    querry = artistName + " " + track['trackNumber'] + " " + track['title'] + ".flac"
    search = slskd.searches.search_text(searchText = querry, searchTimeout = 5000, filterResponses=True)

    while(True):
        if slskd.searches.state(search['id'])['state'] != 'InProgress':
            break

    for result in slskd.searches.search_responses(search['id']):
        username = result['username']
        files = result['files']

        for file in files:
            if('.flac' in file['filename']):
                file_dir = os.path.dirname(file['filename'])
                directory = slskd.users.directory(username = username, directory = file_dir)

                if(album_track_num(directory) == track_num):
                    if(album_match(tracks, directory['files'])):
                        for i in range(0,len(directory['files'])):
                            directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']
                        slskd.transfers.enqueue(username=username, files=directory['files'])
                        break
        else:
            continue
        break
    else:
        continue
    break

while(True):
    downloads = slskd.transfers.get_all_downloads()

    user_num = len(downloads) - 1
    dir_num = len(downloads[user_num]['directories']) - 1
    download_num = downloads[user_num]['directories'][dir_num]['fileCount'] - 1
    last_download_state = downloads[user_num]['directories'][dir_num]['files'][download_num]['state']

    if(last_download_state == 'Completed, Succeeded'):
        print("FINISHED DOWNLOADING")
        break

print(lidarr.post_command(name = 'DownloadedAlbumsScan', path = '/data/Shaggy'))